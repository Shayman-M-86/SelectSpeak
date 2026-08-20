# SelectSpeak

Select text anywhere in Windows, press `Alt+S`, and hear it read aloud
using a locally installed Narrator Natural Voice when native voice support
is available, with the built-in SAPI voice as an automatic fallback. The tray app includes pause, resume, stop,
replay, clipboard mode, word highlighting, and hotkey rebinding. Global
shortcut registration, selection capture, and shortcut recording are handled
by a small native Windows bridge.

Project policies: [privacy](PRIVACY.md), [security](SECURITY.md),
[contributing](CONTRIBUTING.md), [code of conduct](CODE_OF_CONDUCT.md), and
[code signing](docs/CODE_SIGNING_POLICY.md).

## Requirements

- 64-bit Windows 10 version 1809 or later, or Windows 11
- An internet connection during setup and when adding optional Supertonic support

## User installation

Download and run:

```text
SelectSpeak-Setup-0.1.3.exe
```

The installer does not require administrator rights. It installs SelectSpeak
to `%LOCALAPPDATA%\Programs\SelectSpeak`, adds it to the Start Menu, and offers
optional desktop and sign-in startup shortcuts. SelectSpeak can be launched at
the end of the installation. An internet connection is required: setup uses its
pinned NuGet client to install the Microsoft Speech SDK runtime into
`SelectSpeak\native` before the application is launched. Before files are
installed, Setup displays a notice describing this download, optional
Supertonic downloads, local data storage, and the privacy policy.

The standard installation leaves the neural Python stack and model out. Choose
the optional **Supertonic Neural Voice** component for a full installation. If
it is not selected initially, choosing Supertonic inside SelectSpeak downloads
and reopens the same version of Setup with that component preselected. Setup
installs the dependencies into `SelectSpeak\dependencies\supertonic`, installs
the model into the user-data directory, and restarts SelectSpeak. No second
application executable or system Python installation is used.

Quit SelectSpeak from its tray menu before installing an update. The stable
installer identity lets a newer release upgrade the existing application in
place while retaining the previously selected shortcut options.

A PyInstaller folder is produced as input to the installer:

```text
dist/SelectSpeak/
├── SelectSpeak.exe
├── _internal/
├── dependencies/                 # present only after Supertonic is selected
├── native/
└── licenses/
```

It intentionally contains only SelectSpeak's native bridge. The installer adds
the Speech SDK runtime, so this intermediate folder is not the user-facing
portable distribution.

SelectSpeak stores writable state outside the application folder:

```text
%LOCALAPPDATA%\SelectSpeak\
├── settings.json
├── logs\selectspeak.log
└── models\supertonic3\           # present only after Supertonic is selected
```

Settings use a versioned schema and persist the selected backend and Natural
Voice, hotkeys, speech settings, Supertonic options, OCR language, clipboard
mode, auto-hide preference, and speech diagnostics preference. Installer
upgrades and normal uninstall both preserve this directory. It can be removed
manually when a complete data reset is wanted.

## Developer setup

Open PowerShell in the project folder and run:

```powershell
.\scripts\install-dev-dependencies.ps1
```

This developer setup script requires WinGet. It provisions `uv`, a managed
Python 3.13 installation, all Python
packages, Visual C++ Build Tools and CMake when needed, and the single native
bridge. It also downloads the local Supertonic ONNX voice model, then verifies
imports and runs the test, lint, and type-check suites. It is safe to run again
when updating an existing installation.

To install, start SelectSpeak, and add it to Windows startup in one command:

```powershell
.\scripts\install-dev-dependencies.ps1 -Launch -AddToStartup
```

This developer setup script requires WinGet. It provisions uv, a managed Python 3.13 installation, all required Python packages, Visual C++ Build Tools and CMake when needed, and builds the native bridge. It also downloads the local Supertonic ONNX voice model, then verifies the installation by running the test, lint, and type-check suites. The script is safe to run again when updating an existing installation.

To install SelectSpeak, launch it, and add it to Windows startup in one command:

.\scripts\install-dev-dependencies.ps1 -Launch -AddToStartup

Use -SkipNaturalVoice if you only want the SAPI backend and do not want to build the optional direct Natural Voice integration. Use -SkipSupertonicModel to defer downloading the model until Supertonic is first selected. Use -SkipChecks to omit developer checks during installation.

The input bridge attempts UI Automation first, then falls back to SendInput, clipboard sequence polling, and an eager multi-format clipboard snapshot. Normal text capture and OCR shortcuts share a single native message thread. OCR is responsible only for the frozen-screen selector and Windows' local text-recognition functionality. The bridge uses RegisterHotKey during normal operation and temporarily installs a low-level keyboard hook only while recording a new shortcut.

Set SELECTSPEAK_NATIVE_DLL to use the unified native DLL from another location.

Direct Natural Voice backend

SelectSpeak includes an optional native backend for compatible Microsoft Narrator Natural Voices. It communicates directly with Microsoft's locally installed speech components, allowing SelectSpeak to stream PCM audio and receive accurate word-boundary events without routing synthesis through SAPI.

The development setup builds this backend by default. Compatible Natural Voices installed through Windows Settings are discovered dynamically. If the backend or a compatible voice is unavailable, SelectSpeak automatically falls back to SAPI.

To remain compatible with different installed Windows speech-runtime and voice-package versions, the bridge obtains the runtime information required by Microsoft's locally installed speech components from the installed speech extension at runtime. The bridge keeps this information in memory only; it does not persist, log, upload, or transmit it. The backend does not require the user to supply external speech-service credentials.

This integration uses internal, version-sensitive Windows speech interfaces rather than a stable public Microsoft API. It may require maintenance when Microsoft changes the speech runtime or voice-package implementation.

AppConfig.speech_backend defaults to "auto": SelectSpeak uses the Natural Voice backend when it is available and compatible, otherwise it uses SAPI. Set it to "natural" to require the Natural Voice backend, "sapi" to disable it, or "supertonic" to start with the neural engine selected. AppConfig.native_dll can also point to an alternate unified DLL path.

Supertonic defaults to its F4 voice at 8 inference steps. Voice, language, quality steps, and speed can be configured through the supertonic_voice, supertonic_language, supertonic_steps, and supertonic_speed fields in AppConfig.

The Natural Voice integration currently targets Speech SDK 1.41.1 for compatibility with the supported Windows speech components. Microsoft Speech SDK and voice-package licensing terms are separate from this project's source license. See src/native/natural_voice/THIRD_PARTY_NOTICES.md.

## Development run

```powershell
.\scripts\run-dev.ps1
```

This is the main way to run SelectSpeak from a checkout. It runs the native and
player builds, which compile only what changed, and then starts the application.
Use `-NoBuild` to start without building, `-Release` for a Release player, and
`-Detached` to return once it is running.

Double-click `scripts/run.vbs` for the same thing without a console window; it
calls `run-dev.ps1 -Detached`.

Developers can also run `uv run selectspeak`, which builds nothing.

To update every source-controlled release-version field before building a new
release, run:

```powershell
.\scripts\bump_version.ps1
```

The script displays the current version and prompts for the new one. For an
unattended update, pass it directly, for example
`.\scripts\bump_version.ps1 -Version 0.1.3`. Commit the resulting changes before
creating the matching `v<version>` tag.

Press `Alt+D` to freeze the current desktop and drag around text. SelectSpeak
recognizes the selected pixels locally with `Windows.Media.Ocr`, passes the text
directly to Python, and immediately reads it without changing the clipboard or
launching PowerToys. Press Escape or right-click to cancel. Change the shortcut
with `ocr_hotkey`; optionally set `ocr_language` to a Windows language tag such
as `"en-AU"`. When unset, SelectSpeak tries the foreground keyboard language,
then English, then the Windows profile OCR languages.

The native OCR layout analyzer uses recognized word rectangles to join ordinary
visual wrapping while retaining likely paragraphs, headings, bullet rows,
hanging indentation, and column changes. Paragraph spacing is preserved through
speech normalization, giving the chunker meaningful structural boundaries.

## Start automatically

Select **Start SelectSpeak when I sign in** while running the Windows installer.
For a developer checkout, pass `-AddToStartup` to `scripts/install-dev-dependencies.ps1`. To remove that
development shortcut later,
run:

```powershell
.\scripts\install-dev-dependencies.ps1 -RemoveFromStartup
```

## Controls

- Select text and press `Alt+S` to read it.
- Press the hotkey again on the same selection while it is speaking to stop;
  press it once more after stopping to read the selection again. Selecting
  different text replaces the current reading immediately.
- Use the transport buttons to pause, resume and stop the current reading. The
  player never takes foreground focus from the application being read.
- Open **Settings** with the gear button to change:
  - **Read the clipboard instead of the selection.** Off by default: the
    shortcut reads selected text when available and falls back to the existing
    clipboard when nothing is selected. On, it always reads the clipboard.
  - **Voice.** Any discovered Windows Natural Voice, the configured local
    Supertonic model, or the Windows SAPI fallback. The first switch to
    Supertonic can take a moment while its ONNX model loads into memory.
  - **Shortcuts.** Both the read and screen-capture shortcuts are recorded in
    place; a combination another application already holds is refused and the
    shortcut in force is kept.
  - **Auto hide.** Enabled by default, so the player puts itself away when
    reading finishes.
  - **Speech diagnostics.** Collects adaptive chunk boundaries, synthesis
    timing, playback runway, queue delay, and underruns.
- Use the tray icon to show the player or quit.

## Text processing

Before speech starts, the speech-normalization pipeline converts copied structure into
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
The reader preserves those interpreted lines
visually, restores detected bullet markers with hanging indentation, and
highlights the active word within the structured preview. Visual bullet markers
are removed before each segment is sent to the speech engine. When Windows
preserves list rows but drops their markers, list-shaped multiline blocks are
inferred from their heading and sentence structure.

The rebound hotkey, clipboard mode, selected backend/voice, and UI preferences
are persisted in `%LOCALAPPDATA%\SelectSpeak\settings.json`. Code-level
`AppConfig` values remain the defaults for a new profile.
After updating the application, choose **Quit** from the tray icon before
starting it again; closing the player window only hides the existing process.

## Debug log

Logging is controlled by `AppConfig` in `src/python/selectspeak/config/models.py` and writes to
`%LOCALAPPDATA%\SelectSpeak\logs\selectspeak.log` by default. The entry point
configures logging once; individual modules use their ordinary
`logging.getLogger(__name__)` logger and let records propagate to that central
handler.

The structured JSON Lines diagnostic switch is:

```python
logging_enabled: bool = False
log_file: str = ""  # defaults to %LOCALAPPDATA%\SelectSpeak\logs\selectspeak.log
```

Logging is disabled for a new profile. If enabled for troubleshooting, the
diagnostic log can contain selected or clipboard text previews, so treat it as
potentially sensitive and disable it again when the trace is complete. Logs are
stored locally and are never uploaded automatically.

## Development

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run ty check --python-platform win32
.\build-tools\security\audit_dependencies.ps1
uv build
```

To create the Windows application and installer:

```powershell
.\build-tools\build.ps1
```

That single command builds the native bridge, the WinUI player, the portable
`dist\SelectSpeak` folder, and `dist\SelectSpeak-Setup-<version>.exe`. For the
portable folder alone, add `-SkipInstaller`.

The optional Supertonic archives are large and change far less often than the
application version, so an ordinary build reuses whichever pair is already in
`dist\`, reporting when their version differs. Pass `-RebuildSupertonicPayload`
to regenerate them, which a real release needs because their download links are
published under the release tag; `-ReleaseReady` turns a reused mismatch into an
error rather than a warning. Add `-SkipNativeBuild` or `-SkipWinUiBuild` to
reuse those build outputs.

GitHub Actions mirrors these checks on GitHub-hosted Windows runners. `CI` runs
the lint, test, package, and dependency-security jobs for pull requests and every
push to `main`. `Distribution` runs only when started manually from the matching
`v<version>` tag. It performs the complete build and installer smoke test,
retains the unsigned Setup, checksum, and optional Supertonic archives as one
workflow artifact, and creates an unsigned draft GitHub Release containing the
same four files. Review and publish that draft manually. The workflow does not
sign files.

This rebuilds and stages only the SelectSpeak native bridge, collects third-party
notices, creates and verifies the slim PyInstaller core, builds the versioned
Supertonic dependency and model ZIPs, and compiles
`dist\SelectSpeak-Setup-<version>.exe` with Inno Setup 6. The draft release keeps
Setup, its `.sha256` file, and both ZIP archives together under the matching
`v<version>` tag. Setup contains
the pinned NuGet client and package manifest, then obtains the pinned Microsoft
Speech SDK DLLs during installation. It downloads the hash-pinned Supertonic
ZIPs only when that component is selected.

Inno Setup is a release-build dependency. Install it with:

```powershell
winget install --id JRSoftware.InnoSetup --exact
```

When the installer-source folder already exists, the installer alone can be rebuilt and
tested with:

```powershell
.\build-tools\installer\build_installer.ps1
.\build-tools\installer\smoke_test.ps1
```

The smoke test uses an isolated installation directory, starts the installed
application, repeats the installation as an upgrade, uninstalls it, and verifies
that its isolated user settings remain intact.

## Project structure

```text
src/                        Product source, grouped by implementation language
├── python/selectspeak/     Installable Python application package and entry point
│   ├── app/                Application lifecycle, startup, and voice selection
│   ├── audio/              Playback-session coordination
│   ├── config/             Configuration models, settings, and runtime paths
│   ├── infrastructure/     Cross-cutting logging infrastructure
│   ├── native/             Python bindings for the unified native bridge
│   ├── input/              Capture, clipboard, hotkeys, and OCR integration
│   ├── speech/             Speech contracts, engines, processing, and playback
│   └── ui/                 Player window, diagnostics, theme, and tray
└── native/                 C++ bridge source, CMake project, input, and voices

build-tools/                Source-controlled build and release tooling
├── build.ps1               Complete Windows release entry point
├── app/                    PyInstaller definition and Windows app metadata
├── installer/              Inno Setup definition, compiler wrapper, smoke test
├── native/                 Native build and toolchain scripts
├── runtime/                Installer-time Microsoft Speech runtime deployment
├── supertonic/             Optional dependency/model payload tooling
└── tools/                  Staging, notices, icons, and verification utilities

scripts/                    Developer and user convenience launchers
├── install-dev-dependencies.ps1  Complete development setup and upgrade
├── run-dev.ps1             Rebuild what changed, then run from the checkout
├── run.vbs                 Console-free wrapper over run-dev.ps1
└── bump_version.ps1        Update every source-controlled version field

docs/                       Engineering, release, signing, and installer notices
.build/                     Ignored generated intermediate files
dist/                       Ignored distributable applications and installers
```

## Privacy and security

Selected text, clipboard contents, OCR images, and generated speech remain on
the local computer. SelectSpeak has no telemetry or advertising. Setup makes
disclosed network requests for its pinned Microsoft Speech runtime and, when
selected, optional Supertonic files. See the full [privacy policy](PRIVACY.md)
and [security policy](SECURITY.md).

## Code signing policy

The project's roles, release rules, privacy reference, and current signing
status are documented in the [code signing policy](docs/CODE_SIGNING_POLICY.md).
SelectSpeak is not yet claiming that its releases are signed. If enrollment is
approved, signed releases will carry the statement: “Free code signing provided
by SignPath.io, certificate by SignPath Foundation.”

## License

SelectSpeak is released under the [MIT License](LICENSE). Third-party components
and models remain subject to their respective licences and notices.

## Acknowledgements

Thanks to
[NaturalVoiceSAPIAdapter](https://github.com/gexgd0419/NaturalVoiceSAPIAdapter)
and [TTS Anywhere](https://github.com/yosef0H4/TTS-anywhere) for sharing their
work. Their exploration of Windows Natural Voices and text-to-speech integration
helped inspire parts of SelectSpeak's independently developed implementation.
