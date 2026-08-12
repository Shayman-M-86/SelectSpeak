# SelectSpeak

Select text anywhere in Windows, press `Alt+S`, and hear it read aloud
using a locally installed Narrator Natural Voice when the optional native bridge
is available, with the built-in SAPI voice as an automatic fallback. The tray app includes pause, resume, stop,
replay, clipboard mode, word highlighting, and hotkey rebinding. Global
shortcut registration, selection capture, and shortcut recording are handled
by a small native Windows bridge.

## Requirements

- 64-bit Windows 10 or 11
- An internet connection for first-time setup
- WinGet (included with Microsoft's App Installer on current Windows releases)

## First-time setup

Open PowerShell in the project folder and run:

```powershell
.\install.ps1
```

The installer provisions `uv`, a managed Python 3.13 installation, all Python
packages, Visual C++ Build Tools and CMake when needed, and both native
bridges. It also downloads the local Supertonic ONNX voice model, then verifies
imports and runs the test, lint, and type-check suites. It is safe to run again
when updating an existing installation.

To install, start SelectSpeak, and add it to Windows startup in one command:

```powershell
.\install.ps1 -Launch -AddToStartup
```

Use `-SkipNaturalVoice` only if you want the SAPI fallback without the optional
direct Natural Voice bridge. Use `-SkipSupertonicModel` to defer the model
download until Supertonic is first selected. Use `-SkipChecks` to omit developer
checks during installation.

The input bridge tries UI Automation first, then uses `SendInput`, clipboard
change notifications, and an eager multi-format clipboard snapshot as its
fallback. It uses `RegisterHotKey` during normal operation and installs a
low-level keyboard hook only while recording a new shortcut.

Set `SELECTSPEAK_INPUT_DLL` to use a native input DLL at another location.

### Direct Natural Voice backend

The in-house bridge bypasses SAPI and streams PCM plus exact word-boundary
events from Microsoft's embedded Speech SDK. The root installer builds this
bridge by default. Install a compatible Narrator Natural Voice from Windows
Settings to use it; otherwise SelectSpeak automatically falls back to SAPI.

`AppConfig.speech_backend` defaults to `"auto"`: SelectSpeak uses the bridge
when it is present and usable, otherwise it retains the current SAPI backend.
Set it to `"natural"` to require the bridge, `"sapi"` to disable it, or
`"supertonic"` to start with the neural engine selected. You may also set
`SELECTSPEAK_NATURAL_VOICE_DLL` to an alternate DLL path.

Supertonic defaults to its `F4` voice at 8 inference steps. The voice,
language, quality steps, and speed are configurable through the
`supertonic_voice`, `supertonic_language`, `supertonic_steps`, and
`supertonic_speed` fields in `AppConfig`.

For a compatible voice package extracted to a local folder, set
`AppConfig.natural_voice_path` to that folder. This bypasses installed-package
discovery and is useful with the last compatible package versions linked by the
upstream adapter project.

This depends on an unofficial, version-sensitive interface to Microsoft's
installed voice packages. The build pins Speech SDK 1.41.1 for compatibility;
the SDK and voice-model redistribution terms are separate from this project's
source license. See `native/natural_voice/THIRD_PARTY_NOTICES.md`.

## Run

Double-click `run.vbs` to launch without a console window. It uses the
project-local Python environment created by `install.ps1`, so `uv` does not
need to be on the launcher's `PATH`.

Developers can also run `uv run main.py` or `uv run selectspeak`.

Press `Alt+D` to open the configured OCR selector (`Win+Shift+T`). After you
select a region, SelectSpeak waits for the OCR service to update the clipboard
and immediately reads the recognized text. The shortcuts can be changed with
`ocr_hotkey` and `ocr_trigger_hotkey` in `AppConfig`.

## Start automatically

Pass `-AddToStartup` to the installer. To remove the startup shortcut later,
run:

```powershell
.\install.ps1 -RemoveFromStartup
```

## Controls

- Select text and press `Alt+S` to read it.
- Press the hotkey again on the same selection while it is speaking to stop;
  press it once more after stopping to read the selection again. Selecting
  different text replaces the current reading immediately.
- In **Mode: Auto**, the hotkey reads selected text when available and
  automatically falls back to the existing clipboard when nothing is selected.
- Click **Mode: Auto** to switch to **Mode: Clipboard** when you want to force
  clipboard reading.
- Click **Voice: Windows** to switch to the local Supertonic neural voice;
  click **Voice: Supertonic** to return to Windows Natural Voice/SAPI. The first
  switch can take a moment while the ONNX model loads into memory.
- Click **Auto hide: On** to keep the player open after speech finishes, or
  click it again to restore automatic hiding. Auto hide is enabled by default.
- Click **Debug: Off** to show adaptive chunk boundaries and live speech
  diagnostics. The active chunk is highlighted when its PCM reaches the
  playhead; the panel reports target/actual size, estimated and actual synthesis
  time, generated audio duration, playback runway, queue delay, and underruns.
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
and collapses accidental whitespace. A shared backend-independent segmenter
then splits every engine's input at structural lines and sentence boundaries,
with a 100-character safety limit for unusually long run-on sentences.
Natural Voice and Supertonic feed one shared persistent PCM player for the
entire request, so safety-limit chunks do not reopen the audio device or gain an
artificial pause. Real sentence and structural boundaries receive the shared
100 millisecond controlled pause. Both PCM backends use the same adaptive speech
pipeline: the first complete sentence is generated immediately, then later
chunks grow or shrink according to remaining playback runway and observed
generation speed, but never combines more than two complete sentences in one
chunk. The controller prefers sentence endings, permits semicolons and colons
under pressure, and uses commas only when the buffer is at risk.
Supertonic additionally trims model-generated edge silence. Lookahead is capped
at 12 seconds of ready audio to keep cancellation responsive and memory bounded.
The expanded reader preserves those interpreted lines
visually, restores detected bullet markers with hanging indentation, and
highlights the active word within the structured preview. Visual bullet markers
are removed before each segment is sent to the speech engine. When Windows
preserves list rows but drops their markers, list-shaped multiline blocks are
inferred from their heading and sentence structure.
- Click the displayed hotkey to bind a different key combination for the
  current session.
- Use the tray icon to show the player or quit.

The rebound hotkey, clipboard mode, and UI voice selection are not persisted
between launches. Set `AppConfig.speech_backend` to change the startup voice.
Set `AppConfig.speech_debug_enabled=True` to start with speech diagnostics open.
After updating the application, choose **Quit** from the tray icon before
starting it again; closing the player window only hides the existing process.

## Debug log

Logging is controlled only by `AppConfig` in `src/selectspeak/config.py`. It is
currently enabled while the Natural Voice integration is being diagnosed and
writes to `selectspeak.log`.

The structured JSON Lines diagnostic switch is:

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
install.ps1                 Complete first-time setup and upgrade script
main.py                     Root entry point
run.vbs                     Console-free launcher using the local environment
src/selectspeak/app.py      Application lifecycle and coordination
src/selectspeak/input/      Capture, clipboard, hotkeys, and native input
src/selectspeak/speech/     Speech contracts, processing, and playback
src/selectspeak/speech/backends/
                            SAPI, Natural Voice, and Supertonic adapters
src/selectspeak/ui/         Player window, diagnostics, theme, and tray
native/natural_voice/       Small C ABI bridge to local Natural Voices
native/input/               Native hotkey and selected-text capture bridge
native/build_helpers.ps1    Shared C++ toolchain discovery and installation
```
