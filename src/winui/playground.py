"""Interactive playground for the WinUI 3 reader spike.

Launches the UI and drops you at a prompt so you can drive the window live:

    python src/winui/playground.py

Type `help` at the prompt for the command list.
"""

from __future__ import annotations

import logging
import pathlib
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "python"))

from selectspeak.ui.winui_bridge import WinUiPlayer  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

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

HELP = """
Commands
  read              play the sample once, highlighting each word
  loop              read on repeat until you press Enter
  text <words>      replace the reader contents
  hl <pos> <len>    highlight an exact character range
  status <words>    set the status line

  size <w> <h>      exact window size            (OverlappedPresenter)
  chrome on|off     border + title bar on or off
  resizable on|off  allow the user to drag the edges
  ontop on|off      always on top

  show / hide       show or hide the window
  state             print what Python thinks the UI is showing
  quit              close the UI and exit
"""


def words_of(text: str) -> list[tuple[int, int]]:
    """Character ranges of every word, as the speech pipeline reports them."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for token in text.split():
        index = text.find(token, cursor)
        if index < 0:
            continue
        spans.append((index, len(token)))
        cursor = index + len(token)
    return spans


def main() -> int:
    if not UI_EXE.exists():
        print("UI not built. Run: dotnet build src/winui/SelectSpeak.UI")
        return 1

    player = WinUiPlayer(
        on_read=lambda: print("\n  [UI] Read pressed"),
        on_play=lambda: print("\n  [UI] Play pressed"),
        on_pause=lambda: print("\n  [UI] Pause pressed"),
        on_resume=lambda: print("\n  [UI] Resume pressed"),
        on_stop=lambda: print("\n  [UI] Stop pressed"),
    )
    player.start()

    print("launching SelectSpeak.UI…")
    process = subprocess.Popen([str(UI_EXE)])
    if not player.wait_for_ui(15):
        print("UI did not connect")
        process.terminate()
        return 1

    state = {"text": SAMPLE}
    player.set_reader_text(SAMPLE)
    player.set_status("Ready. Type a command in the console.")

    # Keep UI intents flowing while you type.
    pumping = True

    def pump() -> None:
        while pumping:
            player.drain_callbacks()
            time.sleep(0.05)

    threading.Thread(target=pump, daemon=True, name="IntentPump").start()

    print(HELP)

    def read_once(delay: float = 0.18) -> None:
        player.set_playback(speaking=True, text=state["text"])
        for index, length in words_of(state["text"]):
            if process.poll() is not None:
                return
            player.highlight_word(index, length)
            time.sleep(delay)
        player.set_playback(speaking=False)

    try:
        while process.poll() is None:
            try:
                raw = input("winui> ").strip()
            except EOFError:
                break
            if not raw:
                continue
            command, _, argument = raw.partition(" ")
            command = command.lower()
            argument = argument.strip()

            if command in {"quit", "exit"}:
                break
            elif command == "help":
                print(HELP)
            elif command == "read":
                read_once()
            elif command == "loop":
                print("  looping — press Enter to stop")
                stop = threading.Event()
                threading.Thread(
                    target=lambda: (input(), stop.set()), daemon=True
                ).start()
                while not stop.is_set() and process.poll() is None:
                    read_once(0.14)
                player.set_playback(speaking=False)
            elif command == "text":
                state["text"] = argument.replace("\\n", "\n") or SAMPLE
                player.set_reader_text(state["text"])
            elif command == "hl":
                position, _, length = argument.partition(" ")
                player.highlight_word(int(position), int(length or 1))
            elif command == "status":
                player.set_status(argument)
            elif command == "size":
                width, _, height = argument.partition(" ")
                player.resize(int(width), int(height))
                print(f"  asked for {width}x{height}")
            elif command == "chrome":
                on = argument != "off"
                player.set_chrome(border=on, title_bar=on)
            elif command == "resizable":
                player.set_resizable(argument != "off")
            elif command == "ontop":
                player.set_always_on_top(argument != "off")
            elif command == "show":
                player.show()
            elif command == "hide":
                player.hide()
            elif command == "state":
                print(f"  text length : {len(state['text'])}")
                print(f"  words       : {len(words_of(state['text']))}")
            else:
                print(f"  unknown command: {command!r} (try 'help')")
    except KeyboardInterrupt:
        pass
    finally:
        pumping = False
        if process.poll() is None:
            process.terminate()
        player.stop()
    print("closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
