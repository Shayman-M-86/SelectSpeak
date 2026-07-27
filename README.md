# SelectSpeak

Select text anywhere in Windows, press `Alt+S`, and hear it read aloud
using the built-in SAPI voice. The tray app includes pause, resume, stop,
replay, clipboard mode, word highlighting, and hotkey rebinding. Global
keyboard input and simulated copy events are handled by `pynput`.

## Requirements

- Windows 10 or 11
- [uv](https://docs.astral.sh/uv/)
- Python 3.11 or newer

## Run

```powershell
uv sync
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
- Click **Mode: Selection** / **Mode: Clipboard** to choose whether the hotkey
  copies the current selection or reads the existing clipboard directly.
- Click the displayed hotkey to bind a different key combination for the
  current session.
- Use the tray icon to show the player or quit.

The rebound hotkey and clipboard mode are not persisted between launches.
After updating the application, choose **Quit** from the tray icon before
starting it again; closing the player window only hides the existing process.

## Debug log

Every launch appends structured JSON Lines events to `selectspeak.log` in the
directory where SelectSpeak was started. The supplied `run.vbs` sets that
directory to the repository root, so the log normally appears beside `main.py`.

The log records application lifecycle, threads, hotkey registration and
activation, clipboard sequence changes, capture decisions, text lengths and
short text previews, speech generations, SAPI state, UI updates, tray actions,
and exceptions. Because previews can contain selected or clipboard text, treat
the log as potentially sensitive.

Set `SELECTSPEAK_LOG_FILE` to an absolute path before launching if you want the
single log file written somewhere else. Delete the file whenever you want to
begin a fresh trace.

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
src/selectspeak/clipboard.py
src/selectspeak/hotkeys.py
src/selectspeak/speaker.py
src/selectspeak/ui/         Player window and system tray
```
