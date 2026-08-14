# Runtime dependency audit

The release keeps the direct imports used by the current application:

- `pywin32` for the independent Windows SAPI backend and COM initialization.
- `Pillow` and `pystray` for the tray icon.
- `supertonic`, `numpy`, `onnxruntime`, `soundfile`, and the Supertonic download
  dependencies for the optional local neural backend.

No Python hotkey, clipboard, or OCR package remains. Those capabilities use the
unified native Windows bridge. The release excludes development tools and the
unused Supertonic web-server extras.

The release payload contains only SelectSpeak's own native bridge. During setup,
the pinned NuGet client restores the pinned Microsoft Speech SDK packages and
copies only Speech core, Embedded TTS, and ONNX Runtime into the installed
`native` directory. The development-only `native/build.ps1 -DevRuntime` path
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

After the safe exclusions below, the verified PyInstaller directory is 104.11
MiB (25.55 MiB or 19.7% smaller) and the installer is 34.08 MiB (5.21 MiB or
13.3% smaller).

The Natural Voice runtime installed during setup adds 15.30 MiB. A downloaded
Supertonic 3 model measured 384.83 MiB in the user data cache; that model is not
part of the installer, but it dominates disk usage after the optional backend
has been used.

## Safe frozen-build exclusions

- SoundFile is used only by Supertonic's `save_audio()` convenience method.
  SelectSpeak consumes the generated NumPy waveform directly, so the frozen app
  excludes SoundFile, libsndfile, and their CFFI bridge.
- `hf_xet` is an optional Hugging Face transfer accelerator. Model downloads
  retain the normal HTTP path without its 9 MiB extension.
- Pillow's AVIF plugin is unused because SelectSpeak only draws an in-memory
  tray image.
- Pythonwin's MFC GUI is reached through `win32com` type-library tooling, but
  SelectSpeak uses dynamic SAPI dispatch and does not use that tooling or GUI.

These exclusions preserve the SAPI, Natural Voice, Supertonic synthesis, tray,
clipboard, hotkey, and OCR features. Removing ONNX Runtime or NumPy would remove
Supertonic; removing the Microsoft Speech runtime would remove Natural Voice.
Those larger reductions therefore require an explicit product decision, such
as shipping separate lightweight and neural editions.
