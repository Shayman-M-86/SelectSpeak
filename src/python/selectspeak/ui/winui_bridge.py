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
import threading
from collections.abc import Callable
from queue import Empty, SimpleQueue

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


class WinUiPlayer:
    """Drive the WinUI reader over a named pipe.

    Method names mirror the Tk ``PlayerWindow`` so the application layer does
    not need to know which renderer is in use.
    """

    def __init__(
        self,
        *,
        app_name: str = "SelectSpeak",
        pipe_name: str = PIPE_NAME,
        on_play: Callable[[], None] | None = None,
        on_read: Callable[[], None] | None = None,
        on_pause: Callable[[], None] | None = None,
        on_resume: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self._app_name = app_name
        self._pipe_name = pipe_name
        self._handlers: dict[str, Callable[[], None] | None] = {
            "play": on_play,
            "read": on_read,
            "pause": on_pause,
            "resume": on_resume,
            "stop": on_stop,
        }
        self._callbacks: SimpleQueue[Callable[[], None]] = SimpleQueue()
        self._pipe: int | None = None
        self._lock = threading.Lock()
        self._running = False
        self._connected = threading.Event()
        self._thread: threading.Thread | None = None
        self._reader_text = ""

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._serve, name="WinUiBridge", daemon=True)
        self._thread.start()
        logger.info("winui_bridge.started pipe=%s", self._pipe_name)

    def stop(self) -> None:
        self._running = False
        self._close_pipe()
        logger.info("winui_bridge.stopped")

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
                return
            try:
                import win32file

                win32file.WriteFile(pipe, line.encode("utf-8"))
            except Exception:
                logger.debug("winui_bridge.write_failed type=%s", message_type)

    def show(self) -> None:
        self._send("show")

    def hide(self) -> None:
        self._send("hide")

    def set_status(self, text: str) -> None:
        self._send("set_status", text=text)

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
        if text and text != self._reader_text:
            self.set_reader_text(text)
        self._send("set_playback", speaking=speaking, paused=paused)

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
            import win32file

            win32file.CloseHandle(pipe)
        except Exception:
            logger.debug("winui_bridge.close_failed")

    def _serve(self) -> None:
        import pywintypes
        import win32file
        import win32pipe

        while self._running:
            pipe = None
            try:
                # A default descriptor is equivalent to passing NULL for `sa`.
                security = pywintypes.SECURITY_ATTRIBUTES()
                pipe = win32pipe.CreateNamedPipe(
                    _PIPE_PATH.format(self._pipe_name),
                    _PIPE_ACCESS_DUPLEX,
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

                win32pipe.ConnectNamedPipe(pipe, None)
                with self._lock:
                    self._pipe = pipe
                self._connected.set()
                logger.info("winui_bridge.client_connected")

                buffer = b""
                while self._running:
                    try:
                        _result, data = win32file.ReadFile(pipe, _BUFFER_SIZE)
                        # A byte-mode pipe yields bytes, though the stub says str.
                        chunk = data.encode("utf-8") if isinstance(data, str) else bytes(data)
                    except pywintypes.error as error:
                        if error.winerror in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                            break
                        raise
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
