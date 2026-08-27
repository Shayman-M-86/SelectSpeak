# Runtime dependency audit

The standard release keeps the direct imports used by the core application:

- `pywin32` for the Windows tray integration.
- `Pillow` and `pystray` for the tray icon.
- The Supertonic backend adapter remains in the core, but its third-party
  imports stay lazy until the optional dependency layer is activated.

No Python hotkey, clipboard, or OCR package remains. Those capabilities use the
unified native Windows bridge. The release excludes development tools and the
unused Supertonic web-server extras.

The release payload contains only SelectSpeak's own native bridge. During setup,
the pinned NuGet client restores the pinned Microsoft Speech SDK packages and
copies only Speech core, Embedded TTS, and ONNX Runtime into the installed
`native` directory. The development-only `build-tools/native/build.ps1 -DevRuntime` path
stages those same three DLLs under `.runtime/native` for repository runs.

## Measured release footprint

The 2026-08-14 baseline PyInstaller directory was 129.66 MiB and the compressed
installer was 39.29 MiB. The main contents of that directory were:

- ONNX Runtime: 34.55 MiB.
- NumPy (package and OpenBLAS): 26.06 MiB.
- Pillow: 12.70 MiB, including a 7.47 MiB unused AVIF codec.
- Hugging Face Xet: 9.06 MiB.
- Pythonwin: 6.41 MiB.
- CPython itself: at least 5.84 MiB for `python313.dll`, plus the standard
  library and extension modules.
- SoundFile/libsndfile: approximately 2.5 MiB including CFFI.

After the first safe exclusions below, the verified PyInstaller directory was
104.11 MiB and the installer was 34.08 MiB. Separating the complete neural stack
reduced the final core directory to 32.43 MiB and the web installer to 14.33
MiB. Relative to the original baseline, those are reductions of 97.23 MiB
(75.0%) and 24.96 MiB (63.5%) respectively.

The Natural Voice runtime installed during setup adds 15.30 MiB. The optional
Supertonic dependency layer is 27.52 MiB compressed and 89.63 MiB installed.
The curated model archive is 354.18 MiB compressed and 382.71 MiB installed.
Neither optional archive is part of the 14.33 MiB setup executable; Setup
downloads them only when its Supertonic component is selected.

## Optional dependency layer

The core build explicitly excludes `supertonic`, NumPy, ONNX Runtime, and
Hugging Face Hub. Release packaging resolves their pinned wheel dependency
closure into `SelectSpeak-Supertonic-Dependencies-<version>-win-x64.zip`, while
omitting SoundFile, CFFI, and Xet because SelectSpeak neither saves audio nor
requires the optional transfer accelerator. A manifest pins the layer format,
CPython ABI, platform, package names, and versions.

Setup verifies each release archive against the SHA-256 compiled into the
installer, expands into a temporary sibling directory, validates required
files, and atomically replaces the installed component. At startup the same
`SelectSpeak.exe` adds this directory and its native-library folders to the
running interpreter before the lazy Supertonic import. A frozen release probe
confirmed that this external layer initializes NumPy 2.5.2, ONNX Runtime 1.28.0,
Supertonic 1.3.1, and all four model sessions in process.

## Safe frozen-build exclusions

- SoundFile is used only by Supertonic's `save_audio()` convenience method.
  SelectSpeak consumes the generated NumPy waveform directly, so the frozen app
  excludes SoundFile, libsndfile, and their CFFI bridge.
- `hf_xet` is an optional Hugging Face transfer accelerator. Model downloads
  retain the normal HTTP path without its 9 MiB extension.
- Pillow's AVIF plugin is unused because SelectSpeak only draws an in-memory
  tray image.
- Pythonwin's MFC GUI is reached through `win32com` type-library tooling, which
  SelectSpeak does not use.

These exclusions preserve Natural Voice, Supertonic synthesis, tray, clipboard,
hotkey, and OCR features. Supertonic is now an installer-managed
component rather than a separate edition or executable.
