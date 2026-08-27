from __future__ import annotations

import json
import sys
from pathlib import Path

BRIDGE_NATIVE = {
    "selectspeak_native.dll",
}
# The player faults inside WinUI on launch, with no managed exception, if its
# compiled XAML is absent - so the resources are checked, not just the exe.
PLAYER_REQUIRED = (
    "SelectSpeak.UI.exe",
    "SelectSpeak.UI.dll",
    "SelectSpeak.UI.pri",
    "App.xbf",
    "Views/PlayerWindow.xbf",
    "Views/SettingsWindow.xbf",
)
SPEECH_RUNTIME = {
    "Microsoft.CognitiveServices.Speech.core.dll",
    "Microsoft.CognitiveServices.Speech.extension.embedded.tts.dll",
    "Microsoft.CognitiveServices.Speech.extension.onnxruntime.dll",
}
FORBIDDEN_BUNDLED_DEPENDENCIES = {
    "_soundfile.pyd",
    "_soundfile_data",
    "hf_xet",
    "hf_xet.pyd",
    "mfc140u.dll",
    "win32ui.pyd",
    "numpy",
    "numpy.libs",
    "onnxruntime",
    "supertonic",
}


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    require_speech_runtime = "--require-speech-runtime" in sys.argv[2:]
    required = (
        root / "SelectSpeak.exe",
        root / "_internal",
        root / "native",
        root / "ui",
        root / "licenses",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Portable distribution is incomplete: {', '.join(missing)}")
    actual_native = {path.name for path in (root / "native").iterdir() if path.is_file()}
    expected_native = BRIDGE_NATIVE | (SPEECH_RUNTIME if require_speech_runtime else set())
    if actual_native != expected_native:
        raise SystemExit(
            "Native allowlist mismatch: "
            + json.dumps(
                {
                    "missing": sorted(expected_native - actual_native),
                    "unexpected": sorted(actual_native - expected_native),
                }
            )
        )
    missing_player = [name for name in PLAYER_REQUIRED if not (root / "ui" / name).is_file()]
    if missing_player:
        raise SystemExit(f"The player is incomplete: {', '.join(missing_player)}")
    # Debug symbols are build output; a release should not carry them.
    player_symbols = [path.name for path in (root / "ui").rglob("*.pdb")]
    if player_symbols:
        raise SystemExit(f"Player debug symbols found: {sorted(player_symbols)}")

    forbidden = [path for path in root.rglob("*") if path.name.casefold() in {"voices", ".runtime"}]
    if forbidden:
        raise SystemExit(f"Forbidden release content found: {forbidden}")
    bundled_dependency_leaks = [
        path
        for path in root.rglob("*")
        if path.name.casefold() in FORBIDDEN_BUNDLED_DEPENDENCIES or path.name.casefold().startswith("_avif.")
    ]
    if bundled_dependency_leaks:
        raise SystemExit(f"Excluded dependency content found: {bundled_dependency_leaks}")
    print(f"Portable layout verified: {root}")


if __name__ == "__main__":
    main()
