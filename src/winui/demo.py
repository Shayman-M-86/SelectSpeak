"""Minimal end-to-end slice: Python speech driving the WinUI 3 reader.

Run the WinUI app first (or let this script launch it), then:

    python src/winui/demo.py

Python owns everything: it speaks the text, decides when playback starts and
stops, and pushes word positions. The UI only renders.
"""

from __future__ import annotations

import logging
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from selectspeak.ui.winui_bridge import WinUiPlayer  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("demo")

SAMPLE = (
    "SelectSpeak reads whatever you have selected out loud, and this first "
    "paragraph is long enough to wrap onto a second line so the highlight can "
    "be checked at a line boundary.\n"
    "• This bullet is also deliberately long so that it wraps onto a second "
    "display line for testing\n"
    "• Second bullet is short\n"
    "• Third bullet also wraps because it is written to be long enough to "
    "spill over the width of the panel\n"
)

UI_EXE = (
    ROOT
    / "src"
    / "winui"
    / "SelectSpeak.UI"
    / "bin"
    / "Debug"
    / "net8.0-windows10.0.19041.0"
    / "win-x64"
    / "SelectSpeak.UI.exe"
)


def launch_ui() -> subprocess.Popen[bytes] | None:
    if not UI_EXE.exists():
        logger.error("UI not built. Run: dotnet build src/winui/SelectSpeak.UI")
        return None
    logger.info("launching %s", UI_EXE.name)
    return subprocess.Popen([str(UI_EXE)])


def main() -> int:
    player = WinUiPlayer(
        on_read=lambda: logger.info("intent: read"),
        on_play=lambda: logger.info("intent: play"),
        on_pause=lambda: logger.info("intent: pause"),
        on_resume=lambda: logger.info("intent: resume"),
        on_stop=lambda: logger.info("intent: stop"),
    )
    player.start()

    process = launch_ui()
    if process is None:
        return 1

    if not player.wait_for_ui(15):
        logger.error("UI did not connect")
        process.terminate()
        return 1
    logger.info("UI connected")

    player.set_reader_text(SAMPLE)

    # Walk the words the way the speech pipeline reports boundaries, looping
    # so the window always shows a live highlight while the demo is open.
    words = []
    cursor = 0
    for token in SAMPLE.split():
        index = SAMPLE.find(token, cursor)
        if index < 0:
            continue
        words.append((index, len(token)))
        cursor = index + len(token)

    while process.poll() is None:
        player.set_status("Reading the sample passage…")
        player.set_playback(speaking=True, text=SAMPLE)
        for index, length in words:
            if process.poll() is not None:
                break
            player.highlight_word(index, length)
            player.drain_callbacks()
            time.sleep(0.2)
        player.set_playback(speaking=False)
        player.set_status("Finished. Press Read to run the passage again.")
        player.drain_callbacks()
        time.sleep(1.0)

    try:
        while process.poll() is None:
            player.drain_callbacks()
            time.sleep(0.05)
    except KeyboardInterrupt:
        process.terminate()
    finally:
        player.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
