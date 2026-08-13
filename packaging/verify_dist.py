from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_NATIVE = {
    "selectspeak_native.dll",
    "Microsoft.CognitiveServices.Speech.core.dll",
    "Microsoft.CognitiveServices.Speech.extension.audio.sys.dll",
    "Microsoft.CognitiveServices.Speech.extension.codec.dll",
    "Microsoft.CognitiveServices.Speech.extension.embedded.tts.dll",
    "Microsoft.CognitiveServices.Speech.extension.kws.dll",
    "Microsoft.CognitiveServices.Speech.extension.kws.ort.dll",
    "Microsoft.CognitiveServices.Speech.extension.lu.dll",
    "Microsoft.CognitiveServices.Speech.extension.onnxruntime.dll",
    "Microsoft.CognitiveServices.Speech.extension.telemetry.dll",
}


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    required = (root / "SelectSpeak.exe", root / "_internal", root / "native", root / "licenses")
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Portable distribution is incomplete: {', '.join(missing)}")
    actual_native = {path.name for path in (root / "native").iterdir() if path.is_file()}
    if actual_native != EXPECTED_NATIVE:
        raise SystemExit(
            "Native allowlist mismatch: "
            + json.dumps(
                {
                    "missing": sorted(EXPECTED_NATIVE - actual_native),
                    "unexpected": sorted(actual_native - EXPECTED_NATIVE),
                }
            )
        )
    forbidden = [path for path in root.rglob("*") if path.name.casefold() in {"voices", ".runtime"}]
    if forbidden:
        raise SystemExit(f"Forbidden release content found: {forbidden}")
    print(f"Portable layout verified: {root}")


if __name__ == "__main__":
    main()
