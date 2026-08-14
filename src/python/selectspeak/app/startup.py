from __future__ import annotations

import ctypes
import json
import logging
import os
from pathlib import Path
from types import TracebackType

from ..config import DEFAULT_CONFIG
from ..config.paths import log_dir
from ..config.settings import SettingsStore
from ..infrastructure.logging import configure_logging
from ..native import NATIVE_API_VERSION, get_native_bridge, shutdown_native_bridge

logger = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\SelectSpeak"


class SingleInstance:
    """Own the process-wide Windows mutex used by SelectSpeak."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self.handle: int | None = None
        self.already_running = False

    def __enter__(self) -> SingleInstance:
        kernel = ctypes.windll.kernel32
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel.CreateMutexW(None, True, self.name)
        if not handle:
            raise ctypes.WinError()
        self.handle = int(handle)
        self.already_running = kernel.GetLastError() == ERROR_ALREADY_EXISTS
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self.handle is None:
            return
        kernel = ctypes.windll.kernel32
        if not self.already_running:
            kernel.ReleaseMutex(ctypes.c_void_p(self.handle))
        kernel.CloseHandle(ctypes.c_void_p(self.handle))
        self.handle = None


def run_application() -> None:
    settings = SettingsStore()
    log_path = None
    try:
        if _run_supertonic_packaging_probe():
            return
        config = settings.load(DEFAULT_CONFIG)
        log_path = configure_logging(config.logging)
        logger.info("app.entrypoint log_file=%s", log_path)
        with SingleInstance() as instance:
            if instance.already_running:
                logger.info("app.second_instance.exiting")
                return
            settings.save(config)
            bridge = get_native_bridge(config.native_dll)
            logger.info(
                "native.preflight.completed api_version=%s path=%s",
                NATIVE_API_VERSION,
                bridge.path,
            )
            from .application import main as run

            run(config, settings)
    except Exception as error:
        logger.exception("app.startup.failed")
        location = log_path or log_dir() / "selectspeak.log"
        show_startup_error(
            f"SelectSpeak could not initialize its Windows runtime.\n\n{error}\n\nSee:\n{location}"
        )
    finally:
        shutdown_native_bridge()


def _run_supertonic_packaging_probe() -> bool:
    """Exercise the external neural layer when requested by release verification."""
    output_value = os.environ.get("SELECTSPEAK_SUPERTONIC_PROBE_OUTPUT")
    if not output_value:
        return False
    output = Path(output_value).resolve()
    result: dict[str, object]
    try:
        from ..speech.optional_dependencies import activate_supertonic_dependencies

        activate_supertonic_dependencies()
        import numpy
        import onnxruntime
        import supertonic
        from supertonic import TTS

        model_root = os.environ.get("SELECTSPEAK_SUPERTONIC_PROBE_MODEL")
        if not model_root:
            raise RuntimeError("SELECTSPEAK_SUPERTONIC_PROBE_MODEL is required.")
        engine = TTS(model_dir=Path(model_root).resolve(), auto_download=False)
        result = {
            "status": "ok",
            "numpy": numpy.__version__,
            "onnxruntime": onnxruntime.__version__,
            "supertonic": supertonic.__version__,
            "sample_rate": engine.sample_rate,
        }
    except Exception as error:
        result = {
            "status": "error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return True


def show_startup_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "SelectSpeak", 0x10)
    except Exception:
        # A console developer run still receives the logged traceback.
        pass
