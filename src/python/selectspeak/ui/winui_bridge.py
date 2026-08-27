"""A PlayerWindow that renders through the WinUI 3 process.

This is a spike: it implements the slice of the PlayerWindow contract needed to
read text aloud with word highlighting, and no more. Python keeps every
decision; the UI only draws what it is sent and reports which button was
pressed.

The transport is newline-delimited JSON over a named pipe. Python is the server
so the UI can be started, stopped and restarted independently.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import threading
from collections.abc import Callable
from queue import Empty, SimpleQueue
from typing import Any, cast

import pywintypes
import win32event
import win32file
import win32pipe

from ..config.paths import app_dir, is_frozen
from ..speech.voices import VoiceOption
from .hints import shortcut_label, voice_error_summary
from .process_job import ChildProcessJob

logger = logging.getLogger(__name__)

PIPE_NAME = "selectspeak-ui"
_PIPE_PATH = r"\\.\pipe\{}"

# Win32 constants for the named-pipe server.
_PIPE_ACCESS_DUPLEX = 0x00000003
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_UNLIMITED_INSTANCES = 255
_BUFFER_SIZE = 65536
_ERROR_PIPE_CONNECTED = 535
_ERROR_BROKEN_PIPE = 109
_ERROR_NO_DATA = 232
_INVALID_HANDLE_VALUE = -1

# The handle must be overlapped. On a synchronous handle Windows serialises all
# I/O on it, so a WriteFile issued while the serve thread is parked in ReadFile
# queues behind that read - and because the UI only sends when a button is
# pressed, that read does not return. Every outbound message would deadlock.
_FILE_FLAG_OVERLAPPED = 0x40000000

# How long an overlapped read waits before looping, so a stopped bridge can
# notice `_running` went false instead of blocking forever.
_READ_POLL_MS = 250

# How often the main loop wakes to run queued UI intents. Tk polls every 20ms
# via `after`; this is the same idea with a timeout instead of a scheduler.
_CALLBACK_POLL_SECONDS = 0.02

_UI_EXE_NAME = "SelectSpeak.UI.exe"
_UI_DIRECTORY = "ui"

# Where `dotnet build` leaves the player in a source tree. Release first, so a
# developer who has built both gets the one a release would ship.
_UI_TARGET_SUBPATH = pathlib.Path("net8.0-windows10.0.19041.0/win-x64")
_UI_BUILD_CONFIGURATIONS = ("Release", "Debug")

# How long to wait for the UI to exit on shutdown before giving up on it.
_UI_EXIT_TIMEOUT_SECONDS = 5.0


def winui_executable() -> pathlib.Path | None:
    """Locate the WinUI player, or ``None`` when it has not been built.

    Frozen builds ship it in ``ui/`` beside the executable; from a source tree
    it comes from the .NET build output under ``.build/winui``. Both roots come
    from ``app_dir()``, so this agrees with where the native bridge is found.
    """
    override = os.environ.get("SELECTSPEAK_WINUI_EXE")
    if override:
        candidate = pathlib.Path(override)
        return candidate if candidate.is_file() else None

    root = app_dir()
    if is_frozen():
        candidate = root / _UI_DIRECTORY / _UI_EXE_NAME
        return candidate if candidate.is_file() else None

    build_root = root / ".build" / "winui" / "bin"
    for configuration in _UI_BUILD_CONFIGURATIONS:
        candidate = build_root / configuration / _UI_TARGET_SUBPATH / _UI_EXE_NAME
        if candidate.is_file():
            return candidate
    return None


class WinUiPlayer:
    """Drive the WinUI reader over a named pipe.

    Method names mirror the Tk ``PlayerWindow`` so the application layer does
    not need to know which renderer is in use.
    """

    # Which field carries the value, for the intents that report one.
    _VALUE_FIELDS = {
        "set_hotkey": "hotkey",
        "set_ocr_hotkey": "hotkey",
        "select_voice": "voice",
    }

    def __init__(
        self,
        *,
        app_name: str = "SelectSpeak",
        pipe_name: str = PIPE_NAME,
        hotkey: str = "alt+s",
        ocr_hotkey: str = "alt+d",
        auto_hide: bool = True,
        debug_enabled: bool = False,
        on_play: Callable[[], None] | None = None,
        on_read: Callable[[], None] | None = None,
        on_pause: Callable[[], None] | None = None,
        on_resume: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_toggle_playback: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_toggle_clipboard: Callable[[], None] | None = None,
        on_toggle_auto_hide: Callable[[], None] | None = None,
        on_toggle_debug: Callable[[], None] | None = None,
        on_set_hotkey: Callable[[str], None] | None = None,
        on_set_ocr_hotkey: Callable[[str], None] | None = None,
        on_select_voice: Callable[[str], None] | None = None,
    ) -> None:
        self._app_name = app_name
        self._pipe_name = pipe_name
        self._handlers: dict[str, Callable[[], None] | None] = {
            # The WinUI player has one transport button, so it reports that the
            # button was pressed and lets Python decide what that means. The
            # explicit verbs stay for the Tk player, which has separate buttons.
            "toggle_playback": on_toggle_playback,
            "settings": on_settings,
            # Reported by the settings window. Python flips and persists the
            # value, then pushes the result back for the switch to render.
            "toggle_clipboard": on_toggle_clipboard,
            "toggle_auto_hide": on_toggle_auto_hide,
            "toggle_debug": on_toggle_debug,
            "play": on_play,
            "read": on_read,
            "pause": on_pause,
            "resume": on_resume,
            "stop": on_stop,
        }
        # The recorder here reads the keys, because its hook sees combinations
        # a focused window never would. The UI sends back the one the user
        # confirmed, which is why this intent carries a value.
        self._valued_handlers: dict[str, Callable[[str], None] | None] = {
            "set_hotkey": on_set_hotkey,
            "set_ocr_hotkey": on_set_ocr_hotkey,
            "select_voice": on_select_voice,
        }
        self._callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._pipe: int | None = None
        self._lock = threading.Lock()
        self._running = False
        self._connected = threading.Event()
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        # Set when no player could be started at all, which mainloop cannot
        # detect from _process because there is no process to have exited.
        self._launch_failed = False
        # Held for this object's lifetime: the job kills its members when the
        # last handle to it closes, which is what makes the player exit if this
        # process dies without running its shutdown path.
        self._job = ChildProcessJob()
        self._reader_text = ""
        self._hotkey = hotkey
        self._ocr_hotkey = ocr_hotkey
        self._clipboard_mode = False
        self._auto_hide = auto_hide
        self._debug_enabled = debug_enabled
        self._voice_label = ""
        self._voice_key = ""
        self._voice_options: tuple[VoiceOption, ...] = ()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._serve, name="WinUiBridge", daemon=True)
        self._thread.start()
        logger.info("winui_bridge.started pipe=%s", self._pipe_name)
        self._launch_ui()

    def _launch_ui(self) -> None:
        """Start the WinUI process, unless one is already connecting.

        The server is listening by the time this runs, so the UI connects on its
        first attempt rather than falling into its reconnect delay.
        """
        executable = winui_executable()
        if executable is None:
            logger.error("winui_bridge.executable_missing")
            self._abandon()
            return
        try:
            self._process = subprocess.Popen([str(executable)])
        except OSError:
            logger.exception("winui_bridge.launch_failed path=%s", executable)
            self._abandon()
            return
        # So the player cannot outlive a backend that never reaches _stop_ui,
        # such as a crash or a kill from Task Manager.
        self._job.assign(self._process.pid)
        logger.info("winui_bridge.ui_launched pid=%s", self._process.pid)

    def _abandon(self) -> None:
        """Give up when no player could be started.

        mainloop only exits for a process that started and then died, so a
        launch that never produced one would otherwise keep the backend alive
        with nothing to render to and no way for the user to reach it. This is
        a separate flag rather than _closed because mainloop clears that on
        entry, and the failure happens during start.
        """
        self._launch_failed = True
        self._closed.set()

    def stop(self) -> None:
        self._running = False
        self._close_pipe()
        self._stop_ui()
        logger.info("winui_bridge.stopped")

    def _stop_ui(self) -> None:
        """Close the UI process, so it does not outlive the backend."""
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=_UI_EXIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("winui_bridge.ui_kill pid=%s", process.pid)
            process.kill()

    def wait_for_ui(self, timeout: float = 10.0) -> bool:
        """Block until the UI connects, so a caller can sequence a demo."""
        return self._connected.wait(timeout)

    # -- outbound: state -> UI --------------------------------------------

    def _send(self, message_type: str, **fields: object) -> None:
        payload = {"type": message_type, **fields}
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            pipe = self._pipe
            if pipe is None:
                logger.warning("winui_bridge.send_dropped_disconnected type=%s", message_type)
                return
            logger.debug("winui_bridge.send type=%s", message_type)
            try:
                # Overlapped, because the handle is. The wait still makes this
                # call synchronous from the caller's point of view; what it
                # avoids is queueing behind the serve thread's pending read.
                overlapped = pywintypes.OVERLAPPED()
                overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
                try:
                    win32file.WriteFile(pipe, line.encode("utf-8"), overlapped)
                    win32event.WaitForSingleObject(overlapped.hEvent, win32event.INFINITE)
                    win32file.GetOverlappedResult(pipe, overlapped, False)
                finally:
                    win32file.CloseHandle(overlapped.hEvent)
            except Exception:
                logger.debug("winui_bridge.write_failed type=%s", message_type)

    def show(self) -> None:
        self._send("show")

    def hide(self) -> None:
        self._send("hide")

    def send_shortcut(self) -> None:
        """Name the read shortcut, which is all the player displays."""
        self._send("set_shortcut", hotkey=shortcut_label(self._hotkey))

    def set_reader_text(self, text: str) -> None:
        self._reader_text = text
        self._send("set_text", text=text)

    def highlight_word(self, position: int, length: int) -> None:
        self._send("highlight_word", position=position, length=length)

    def resize(self, width: int, height: int) -> None:
        """Set an exact window size, as OverlappedPresenter allows."""
        self._send("resize", width=width, height=height)

    def set_chrome(self, *, border: bool = True, title_bar: bool = True) -> None:
        """Show or remove the window border and caption."""
        self._send("set_chrome", border=border, title_bar=title_bar)

    def set_resizable(self, resizable: bool) -> None:
        self._send("set_resizable", resizable=resizable)

    def set_always_on_top(self, on_top: bool) -> None:
        self._send("set_always_on_top", on_top=on_top)

    def set_playback(self, *, speaking: bool, paused: bool = False, text: str = "") -> None:
        if speaking:
            if text and text != self._reader_text:
                self.set_reader_text(text)
            # Reading is under way, so the player comes back - otherwise a
            # window auto-hide put away at the end of the last read would stay
            # hidden through this one. Not while pausing: that is a window
            # already on screen, and hiding it by hand should stick.
            if not paused:
                self.show()
        else:
            # Finished or stopped, so the reader goes back to its resting
            # state. The backend still passes the text it was reading, but
            # there is nothing being read any more.
            self.set_reader_text("")
        self._send("set_playback", speaking=speaking, paused=paused)

        # Playback has ended, so the player has nothing left to show. Pausing
        # keeps it up, because reading is still in progress.
        if not speaking and self._auto_hide:
            self.hide()

    # -- messages the application layer sends ------------------------------
    #
    # The player shows one thing: the shortcut that starts a read. These are
    # accepted so the application layer can call them, but the WinUI player has
    # nowhere to put a sentence and deliberately does not invent one.

    def show_backend_loading(self, activity: str = "loading") -> None:
        """No-op: voice engine progress has no home in this player yet."""

    def show_backend_ready(self, label: str) -> None:
        """No-op: see show_backend_loading."""

    def show_backend_error(self, message: str) -> None:
        """Report a voice that would not load, in the settings window.

        Selecting one that fails reverts to the previous voice, so without this
        the picker silently snaps back and looks broken rather than reporting a
        real failure.
        """
        self._send("voice_error", text=voice_error_summary(message))

    def show_capture_complete(self, hotkey: str) -> None:
        self.set_hotkey(hotkey)

    # -- settings ----------------------------------------------------------
    #
    # Python owns these values and persists them, so each setter records the
    # new value and pushes the whole set back. The settings window holds no
    # state of its own; it renders what it is sent.

    @property
    def auto_hide(self) -> bool:
        return self._auto_hide

    @property
    def clipboard_mode(self) -> bool:
        return self._clipboard_mode

    @property
    def debug_enabled(self) -> bool:
        return self._debug_enabled

    def _settings_fields(self) -> dict[str, object]:
        return {
            "auto_hide": self._auto_hide,
            "clipboard_mode": self._clipboard_mode,
            "debug_enabled": self._debug_enabled,
            "hotkey": shortcut_label(self._hotkey),
            "ocr_hotkey": shortcut_label(self._ocr_hotkey),
            "voice": self._voice_label,
            "voice_key": self._voice_key,
            # The whole list travels with the settings, so the picker can be
            # rebuilt from any one message rather than needing them in order.
            "voices": [
                {"key": option.key, "label": option.label, "group": option.group}
                for option in self._voice_options
            ],
        }

    def send_settings(self) -> None:
        self._send("set_settings", **self._settings_fields())

    def open_settings(self) -> None:
        """Open the settings window, populated with the current values."""
        self._send("show_settings", **self._settings_fields())

    def set_hotkey(self, hotkey: str) -> None:
        self._hotkey = hotkey
        self.send_settings()
        # The player names the shortcut too, so it changes with the binding.
        self.send_shortcut()

    def set_ocr_hotkey(self, hotkey: str) -> None:
        # Only the settings window shows this one, so there is no player label
        # to refresh alongside it.
        self._ocr_hotkey = hotkey
        self.send_settings()

    def show_hotkey_error(self, message: str) -> None:
        """Report a shortcut that would not bind, in the settings window.

        A rejected shortcut reverts to the previous one, so without this the
        row silently snaps back and looks like the button did nothing.
        """
        self._send("hotkey_error", text=message)

    def set_clipboard_mode(self, enabled: bool) -> None:
        self._clipboard_mode = enabled
        self.send_settings()

    def set_auto_hide(self, enabled: bool) -> None:
        self._auto_hide = enabled
        self.send_settings()

    def set_debug_enabled(self, enabled: bool) -> None:
        self._debug_enabled = enabled
        self.send_settings()

    def set_voice_options(self, options: tuple[VoiceOption, ...], selected_key: str) -> None:
        self._voice_options = options
        selected = next(
            (option for option in options if option.key == selected_key),
            options[0] if options else None,
        )
        if selected is not None:
            self._voice_key = selected.key
            self._voice_label = selected.short_label
        self.send_settings()

    def set_voice_selection(self, key: str, label: str, *, activity: str = "") -> None:
        """Record the chosen voice, whether or not it has finished loading.

        Selecting one reports it twice: once while the engine loads, and again
        when it is ready. Both must be recorded - ignoring the first leaves the
        old key in place, so the next settings push snaps the picker back to
        the previous voice while the new one is still loading.
        """
        self._voice_key = key
        self._voice_label = label
        self.send_settings()

    def update_speech_debug(self, event: object) -> None:
        """Accepted so the application layer can call it; no panel yet."""

    def reset_speech_debug(self) -> None:
        """Accepted so the application layer can call it; no panel yet."""

    # -- lifecycle the application layer expects ---------------------------

    def mainloop(self) -> None:
        """Run until the UI process exits, draining intents as they arrive.

        Tk owns its loop; here Python does, so this is what keeps the process
        alive and runs queued callbacks on the main thread.
        """
        if self._launch_failed:
            logger.error("winui_bridge.mainloop.no_player")
            self.drain_callbacks()
            return
        self._closed.clear()
        while self._running and not self._closed.is_set():
            self.drain_callbacks()
            # The UI hides rather than closes, so an exit here means it crashed
            # or was killed. Either way there is nothing left to render to.
            process = self._process
            if process is not None and process.poll() is not None:
                logger.info("winui_bridge.ui_exited code=%s", process.returncode)
                break
            self._closed.wait(_CALLBACK_POLL_SECONDS)
        self.drain_callbacks()

    def destroy(self) -> None:
        self._closed.set()
        self.stop()

    # -- inbound: UI intent -> Python -------------------------------------

    def call_soon(self, callback: Callable[[], None]) -> None:
        self._callbacks.put(callback)

    def drain_callbacks(self) -> int:
        """Run queued UI intents on the caller's thread."""
        drained = 0
        try:
            while True:
                self._callbacks.get_nowait()()
                drained += 1
        except Empty:
            pass
        except Exception:
            logger.exception("winui_bridge.callback_failed")
        return drained

    def _dispatch(self, message: dict[str, object]) -> None:
        intent = message.get("type")
        if not isinstance(intent, str):
            return

        # Intents that carry a value are handled first; the rest are simple
        # "this button was pressed" reports with nothing to read.
        if intent in self._valued_handlers:
            valued = self._valued_handlers[intent]
            if valued is None:
                logger.info("winui_bridge.intent intent=%s handled=False", intent)
                return
            value = message.get(self._VALUE_FIELDS[intent])
            if not isinstance(value, str) or not value:
                logger.debug("winui_bridge.intent_missing_value intent=%s", intent)
                return
            logger.info("winui_bridge.intent intent=%s value=%s", intent, value)
            self.call_soon(lambda handler=valued, value=value: handler(value))
            return

        handler = self._handlers.get(intent)
        logger.info("winui_bridge.intent intent=%s handled=%s", intent, handler is not None)
        if handler is not None:
            self.call_soon(handler)

    # -- named pipe server -------------------------------------------------

    def _close_pipe(self) -> None:
        with self._lock:
            pipe = self._pipe
            self._pipe = None
        if pipe is None:
            return
        try:
            win32file.CloseHandle(pipe)
        except Exception:
            logger.debug("winui_bridge.close_failed")

    def _await_client(self, pipe: int) -> None:
        """Block until the UI connects, using an overlapped connect.

        ``ERROR_PIPE_CONNECTED`` means the client won the race and attached
        before the call, which is a success rather than a failure.
        """
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        try:
            try:
                win32pipe.ConnectNamedPipe(pipe, overlapped)
            except pywintypes.error as error:
                if error.winerror != _ERROR_PIPE_CONNECTED:
                    raise
                return
            while self._running:
                if (
                    win32event.WaitForSingleObject(overlapped.hEvent, _READ_POLL_MS)
                    != win32event.WAIT_TIMEOUT
                ):
                    win32file.GetOverlappedResult(pipe, overlapped, False)
                    return
        finally:
            win32file.CloseHandle(overlapped.hEvent)

    def _read_chunk(self, pipe: int) -> bytes | None:
        """One overlapped read. ``None`` means nothing arrived before the poll
        timeout, which lets a stopped bridge notice and exit.
        """
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        # The kernel writes into this buffer while the read is pending, so it
        # has to outlive the call rather than be a length the wrapper allocates.
        buffer = win32file.AllocateReadBuffer(_BUFFER_SIZE)
        try:
            win32file.ReadFile(pipe, buffer, overlapped)
            if win32event.WaitForSingleObject(overlapped.hEvent, _READ_POLL_MS) == win32event.WAIT_TIMEOUT:
                # Cancel and wait for the cancellation to land before the
                # buffer goes out of scope, or the kernel would keep writing
                # into memory this call no longer owns.
                win32file.CancelIo(pipe)
                win32event.WaitForSingleObject(overlapped.hEvent, win32event.INFINITE)
                return None
            count = win32file.GetOverlappedResult(pipe, overlapped, False)
            # PyOVERLAPPEDReadBuffer supports slicing at runtime, but the
            # types-pywin32 stub does not expose that part of its interface.
            read_buffer = cast(Any, buffer)
            return bytes(read_buffer[:count]) if count else b""
        finally:
            win32file.CloseHandle(overlapped.hEvent)

    def _serve(self) -> None:
        while self._running:
            pipe = None
            try:
                # A default descriptor is equivalent to passing NULL for `sa`.
                security = pywintypes.SECURITY_ATTRIBUTES()
                pipe = win32pipe.CreateNamedPipe(
                    _PIPE_PATH.format(self._pipe_name),
                    _PIPE_ACCESS_DUPLEX | _FILE_FLAG_OVERLAPPED,
                    _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT,
                    _PIPE_UNLIMITED_INSTANCES,
                    _BUFFER_SIZE,
                    _BUFFER_SIZE,
                    0,
                    security,
                )
                if int(pipe) == _INVALID_HANDLE_VALUE:
                    logger.error("winui_bridge.create_failed")
                    return

                self._await_client(pipe)
                with self._lock:
                    self._pipe = pipe
                self._connected.set()
                logger.info("winui_bridge.client_connected")
                # A reconnected UI starts blank, so give it the current state
                # rather than waiting for the next thing to change.
                self.send_settings()
                self.send_shortcut()

                buffer = b""
                while self._running:
                    try:
                        chunk = self._read_chunk(pipe)
                    except pywintypes.error as error:
                        if error.winerror in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                            break
                        raise
                    if chunk is None:
                        continue  # Poll timeout; nothing arrived yet.
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            self._dispatch(json.loads(line.decode("utf-8")))
                        except (ValueError, UnicodeDecodeError):
                            logger.debug("winui_bridge.bad_message")
            except Exception:
                if self._running:
                    logger.exception("winui_bridge.serve_failed")
            finally:
                self._connected.clear()
                with self._lock:
                    self._pipe = None
                if pipe is not None:
                    try:
                        win32file.CloseHandle(pipe)
                    except Exception:
                        logger.debug("winui_bridge.cleanup_failed")
                logger.info("winui_bridge.client_disconnected")
