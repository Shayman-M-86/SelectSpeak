"""Frozen-build verification probe, launched by build-tools/build.ps1.

The release build starts the packaged SelectSpeak.exe with
``SELECTSPEAK_SUPERTONIC_PROBE_OUTPUT`` set to confirm the frozen executable
can activate the optional Supertonic dependency layer and load its model
before shipping. This has to run through the real frozen entry point (import
machinery, DLL search paths, and dependency activation all behave differently
once packaged), so ``run_application`` still checks for the probe first, but
the probe's own logic lives here rather than inline in application startup.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def run_if_requested() -> bool:
    """Run the frozen-build Supertonic probe if requested, returning whether it ran."""
    output_value = os.environ.get("SELECTSPEAK_SUPERTONIC_PROBE_OUTPUT")
    if not output_value:
        return False
    output = Path(output_value).resolve()
    result: dict[str, object]
    try:
        from ..speech.supertonic_setup import activate_dependencies

        activate_dependencies()
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
