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
- `security/` contains the locked Python and NuGet dependency vulnerability
  audit.
- `supertonic/` contains creation and atomic installation of the optional
  dependency and model archives.
- `tools/` contains shared staging, licence collection, icon generation, and
  release verification tools.

Source-controlled build logic lives here. Generated intermediate files go to
`.build/`, while portable applications, installers, checksums, and optional
payloads go to `dist/`.

Run the dependency security audit before a release:

```powershell
.\build-tools\security\audit_dependencies.ps1
```

To rebuild only the installer from an existing portable build and payloads:

```powershell
.\build-tools\installer\build_installer.ps1
.\build-tools\installer\smoke_test.ps1
```

[`docs/DEPENDENCY_AUDIT.md`](../docs/DEPENDENCY_AUDIT.md) records release-size
decisions. [`docs/INSTALLATION_NOTICE.txt`](../docs/INSTALLATION_NOTICE.txt) is
displayed by Setup and must remain consistent with the installer's network and
storage behavior.

GitHub-hosted automation lives in `.github/workflows/`:

- `ci.yml` runs Ruff, formatting, ty, pytest, the Python package build, and the
  locked Python and NuGet dependency audits for pull requests and pushes to
  `main`. Audit reports are retained as workflow artifacts.
- `distribution.yml` performs the complete unsigned Windows release build and
  installer smoke test only when manually dispatched from the matching version
  tag. It uploads Setup, its checksum, and both matching Supertonic payload
  archives as a workflow artifact, then creates an unsigned draft GitHub Release
  for manual review and publication.
