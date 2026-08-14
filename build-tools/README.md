# Build and release tooling

`build.ps1` is the single entry point for a complete Windows release build. It
coordinates the native bridge, PyInstaller core, optional Supertonic payloads,
metadata verification, and Inno Setup installer.

```powershell
.\build-tools\build.ps1
```

The subdirectories are organized by responsibility:

- `app/` contains the PyInstaller definition and Windows application metadata.
- `installer/` contains the Inno Setup definition, compiler wrapper, and
  isolated smoke test.
- `native/` contains the native bridge build scripts.
- `runtime/` contains installer-time deployment of the pinned Microsoft Speech
  runtime.
- `supertonic/` contains creation and atomic installation of the optional
  dependency and model archives.
- `tools/` contains shared staging, licence collection, icon generation, and
  release verification tools.

Source-controlled build logic lives here. Generated intermediate files go to
`.build/`, while portable applications, installers, checksums, and optional
payloads go to `dist/`.

To rebuild only the installer from an existing portable build and payloads:

```powershell
.\build-tools\installer\build_installer.ps1
.\build-tools\installer\smoke_test.ps1
```

[`docs/DEPENDENCY_AUDIT.md`](../docs/DEPENDENCY_AUDIT.md) records release-size
decisions. [`docs/INSTALLATION_NOTICE.txt`](../docs/INSTALLATION_NOTICE.txt) is
displayed by Setup and must remain consistent with the installer's network and
storage behavior.
