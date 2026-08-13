# Runtime dependency audit

The release keeps the direct imports used by the current application:

- `pywin32` for the independent Windows SAPI backend and COM initialization.
- `Pillow` and `pystray` for the tray icon.
- `supertonic`, `numpy`, `onnxruntime`, `soundfile`, and the Supertonic download
  dependencies for the optional local neural backend.

No Python hotkey, clipboard, or OCR package remains. Those capabilities use the
unified native Windows bridge. The release excludes development tools and the
unused Supertonic web-server extras.
