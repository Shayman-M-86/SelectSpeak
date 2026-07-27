# SelectSpeak

Select text anywhere in Windows, press `Alt+S`, and hear it read aloud
using the built-in SAPI voice. The tray app includes pause, resume, stop,
replay, clipboard mode, word highlighting, and hotkey rebinding. Global
shortcut suppression and selection copying are handled by a generated
AutoHotkey v2 sidecar. `pynput` is used only while recording a new shortcut.

## Requirements

- Windows 10 or 11
- [uv](https://docs.astral.sh/uv/)
- Python 3.11 or newer
- AutoHotkey v2, installed portably with the supplied bootstrap

## First-time setup

Run these commands once from PowerShell:

```powershell
uv sync
.\install_autohotkey.ps1
```

The bootstrap downloads the official AutoHotkey v2.0.26 portable archive,
verifies its pinned SHA-256 hash, and copies only the 64-bit runtime and
license into the ignored `.runtime/autohotkey` directory. It does not perform
a machine-wide installation.

Set `SELECTSPEAK_AUTOHOTKEY` to an alternative `AutoHotkey64.exe` path if you
prefer to manage the runtime yourself.

## Run

```powershell
uv run main.py
```

You can also double-click `run.vbs` to launch without a console window.
The installed command `uv run selectspeak` reaches the same application entry
point.

## Start automatically

Run `install_startup.ps1` once from PowerShell. Run
`uninstall_startup.ps1` to remove the startup shortcut.

## Controls

- Select text and press `Alt+S` to read it.
- In **Mode: Auto**, the hotkey reads selected text when available and
  automatically falls back to the existing clipboard when nothing is selected.
- Click **Mode: Auto** to switch to **Mode: Clipboard** when you want to force
  clipboard reading.
- Click **Read** to perform the same capture and reading action as the global
  hotkey. The player remains visible without taking foreground focus from the
  source application.

## Text processing

Before speech starts, `text_processing.py` converts copied structure into
speech-friendly prose. It removes Markdown link destinations while keeping
their labels, shortens long filesystem paths to their filenames, separates
bulleted and numbered points with sentence pauses, strengthens semicolon
pauses, replaces underscores with spaces, strips Markdown heading markers,
turns copied line breaks into sentence pauses, preserves paragraph boundaries,
and collapses accidental whitespace. Structural lines are spoken separately
with a 700 millisecond silent gap, rather than relying on voice-specific
punctuation timing. The expanded reader preserves those interpreted lines
visually, restores detected bullet markers with hanging indentation, and
highlights the active word within the structured preview. Visual bullet markers
are removed before each segment is sent to the speech engine. When Windows
preserves list rows but drops their markers, list-shaped multiline blocks are
inferred from their heading and sentence structure.
- Click the displayed hotkey to bind a different key combination for the
  current session.
- Use the tray icon to show the player or quit.

The rebound hotkey and clipboard mode are not persisted between launches.
After updating the application, choose **Quit** from the tray icon before
starting it again; closing the player window only hides the existing process.

## Debug log

Logging is controlled only by `AppConfig` in `src/selectspeak/config.py`. It is
disabled by default, so SelectSpeak does not create or append to a log file
during normal use.

To temporarily enable the structured JSON Lines diagnostic log, change:

```python
logging_enabled: bool = True
log_file: str = "selectspeak.log"
```

The diagnostic log can contain selected or clipboard text previews, so treat
it as potentially sensitive. Set `logging_enabled` back to `False` when the
trace is complete.

## Development

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run ty check --python-platform win32
uv build
```

## Project structure

```text
main.py                     Root entry point
src/selectspeak/app.py      Application lifecycle and state coordination
src/selectspeak/autohotkey.py
src/selectspeak/clipboard.py
src/selectspeak/hotkeys.py
src/selectspeak/speaker.py
src/selectspeak/text_processing.py
src/selectspeak/ui/         Player window and system tray
```
