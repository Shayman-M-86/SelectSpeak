import logging
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from .keymap import to_autohotkey_hotkey
from .logging_setup import log_event, log_exception, text_preview

logger = logging.getLogger(__name__)

_RUNTIME_RELATIVE_PATH = Path(".runtime/autohotkey/AutoHotkey64.exe")
_READY_TIMEOUT_SECONDS = 3.0


def find_autohotkey() -> Path:
    configured = os.environ.get("SELECTSPEAK_AUTOHOTKEY")
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(configured) if configured else None,
        Path.cwd() / _RUNTIME_RELATIVE_PATH,
        project_root / _RUNTIME_RELATIVE_PATH,
        Path(r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"),
        Path(r"C:\Program Files\AutoHotkey\AutoHotkey.exe"),
    ]
    discovered = shutil.which("AutoHotkeyV2.exe") or shutil.which("AutoHotkey64.exe")
    if discovered:
        candidates.append(Path(discovered))

    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            resolved = candidate.resolve()
            log_event(
                logger,
                logging.INFO,
                "autohotkey.runtime.found",
                executable=str(resolved),
            )
            return resolved

    log_event(
        logger,
        logging.ERROR,
        "autohotkey.runtime.missing",
        expected_portable_path=str(project_root / _RUNTIME_RELATIVE_PATH),
    )
    raise RuntimeError("AutoHotkey v2 was not found. Run install_autohotkey.ps1 first.")


def build_sidecar_script(hotkey: str) -> str:
    ahk_hotkey, trigger_key = to_autohotkey_hotkey(hotkey)
    return f"""#Requires AutoHotkey v2.0
#SingleInstance Force
#UseHook True

A_MenuMaskKey := "vkE8"
capturePath := A_Args[1]
commandPath := A_Args[2]
captureSequence := 0
captureInProgress := false

SetTimer(CheckForCaptureRequest, 50)
FileAppend("READY`n", "*", "UTF-8-RAW")

{ahk_hotkey}::CaptureSelection(true)

CheckForCaptureRequest()
{{
    global commandPath

    if !FileExist(commandPath)
        return

    try FileDelete(commandPath)
    CaptureSelection(false)
}}

CaptureSelection(waitForRelease)
{{
    global captureInProgress, capturePath, captureSequence

    if captureInProgress
        return

    captureInProgress := true

    try {{
        savedClipboard := ClipboardAll()
        captured := false
        selectedText := ""

        try {{
            A_Clipboard := ""
            SendEvent "{{Blind}}{{LControl up}}{{RControl up}}{{LAlt up}}{{RAlt up}}"
                . "{{LShift up}}{{RShift up}}{{LWin up}}{{RWin up}}"
                . "{{Ctrl down}}c{{Ctrl up}}"

            if ClipWait(1) {{
                selectedText := A_Clipboard
                captured := true
            }}
        }} finally {{
            A_Clipboard := savedClipboard
        }}

        captureSequence += 1
        try FileDelete(capturePath)

        if captured {{
            FileAppend(selectedText, capturePath, "UTF-8-RAW")
            FileAppend(
                "CAPTURED`t" captureSequence "`n",
                "*",
                "UTF-8-RAW"
            )
        }} else {{
            FileAppend("", capturePath, "UTF-8-RAW")
            FileAppend(
                "EMPTY`t" captureSequence "`n",
                "*",
                "UTF-8-RAW"
            )
        }}

        if waitForRelease
            KeyWait "{trigger_key}"
    }} catch Error as err {{
        FileAppend("ERROR`t" err.Message "`n", "*", "UTF-8-RAW")
    }} finally {{
        captureInProgress := false
    }}
}}
"""


class AutoHotkeySidecar:
    def __init__(self, hotkey: str, handler: Callable[[str], None]) -> None:
        self.hotkey = hotkey
        self._handler = handler
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._process: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopping = False
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None:
                return
            executable = find_autohotkey()
            temporary_directory = tempfile.TemporaryDirectory(prefix="selectspeak-ahk-")
            directory = Path(temporary_directory.name)
            script_path = directory / "selectspeak-sidecar.ahk"
            capture_path = directory / "captured-selection.txt"
            command_path = directory / "capture-request"
            script_path.write_text(
                build_sidecar_script(self.hotkey),
                encoding="utf-8",
            )
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            log_event(
                logger,
                logging.INFO,
                "autohotkey.sidecar.starting",
                hotkey=self.hotkey,
                executable=str(executable),
                script_path=str(script_path),
            )
            try:
                process = subprocess.Popen(
                    [
                        str(executable),
                        str(script_path),
                        str(capture_path),
                        str(command_path),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creation_flags,
                )
            except Exception:
                temporary_directory.cleanup()
                log_exception(logger, "autohotkey.sidecar.start_failed")
                raise

            self._temporary_directory = temporary_directory
            self._capture_path = capture_path
            self._command_path = command_path
            self._process = process
            self._stopping = False
            self._ready.clear()
            self._reader_thread = threading.Thread(
                target=self._read_output,
                args=(process.stdout,),
                daemon=True,
                name="AutoHotkeySidecar",
            )
            self._reader_thread.start()

        if not self._ready.wait(_READY_TIMEOUT_SECONDS):
            return_code = process.poll()
            self.stop()
            raise RuntimeError(
                "AutoHotkey sidecar did not become ready"
                + (f" (exit code {return_code})" if return_code is not None else "")
            )
        log_event(
            logger,
            logging.INFO,
            "autohotkey.sidecar.started",
            hotkey=self.hotkey,
            process_id=process.pid,
        )

    def trigger(self) -> None:
        with self._lock:
            process = self._process
            command_path = self._command_path
        if process is None or process.poll() is not None:
            raise RuntimeError("AutoHotkey sidecar is not running")
        command_path.write_text("capture", encoding="ascii")
        log_event(
            logger,
            logging.INFO,
            "autohotkey.capture.requested",
            source="application_button",
        )

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            process = self._process
            temporary_directory = self._temporary_directory
            self._process = None
            self._temporary_directory = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if temporary_directory is not None:
            temporary_directory.cleanup()
        log_event(
            logger,
            logging.INFO,
            "autohotkey.sidecar.stopped",
            hotkey=self.hotkey,
        )

    def _read_output(self, stream: TextIO | None) -> None:
        if stream is None:
            log_event(logger, logging.ERROR, "autohotkey.sidecar.stdout_missing")
            return
        try:
            for raw_line in stream:
                line = raw_line.rstrip("\r\n")
                if line == "READY":
                    self._ready.set()
                    log_event(logger, logging.DEBUG, "autohotkey.sidecar.ready")
                    continue
                message, _, sequence = line.partition("\t")
                if message in {"CAPTURED", "EMPTY"}:
                    self._dispatch_capture(sequence, message == "CAPTURED")
                elif message == "ERROR":
                    log_event(
                        logger,
                        logging.ERROR,
                        "autohotkey.capture.error",
                        error=sequence,
                    )
                elif line:
                    log_event(
                        logger,
                        logging.WARNING,
                        "autohotkey.sidecar.output",
                        output=line,
                    )
        except Exception:
            log_exception(logger, "autohotkey.sidecar.reader_failed")
        finally:
            with self._lock:
                stopping = self._stopping
                process = self._process
            return_code = process.poll() if process is not None else None
            log_event(
                logger,
                logging.INFO if stopping else logging.ERROR,
                "autohotkey.sidecar.exited",
                expected=stopping,
                return_code=return_code,
            )

    def _dispatch_capture(self, sequence: str, captured: bool) -> None:
        try:
            text = self._capture_path.read_text(encoding="utf-8") if captured else ""
        except Exception:
            log_exception(
                logger,
                "autohotkey.capture.read_failed",
                sequence=sequence,
            )
            return
        log_event(
            logger,
            logging.INFO if captured else logging.WARNING,
            "autohotkey.capture.completed",
            sequence=sequence,
            captured=captured,
            text_length=len(text),
            text_preview=text_preview(text),
        )
        threading.Thread(
            target=self._run_handler,
            args=(text,),
            daemon=True,
            name=f"HotkeyCapture-{sequence}",
        ).start()

    def _run_handler(self, text: str) -> None:
        log_event(logger, logging.DEBUG, "hotkey.handler.started")
        try:
            self._handler(text)
        except Exception:
            log_exception(logger, "hotkey.handler.failed")
        else:
            log_event(logger, logging.DEBUG, "hotkey.handler.completed")
