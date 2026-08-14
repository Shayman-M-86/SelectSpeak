# Contributing to SelectSpeak

Contributions are welcome through GitHub issues and pull requests.

## Before submitting a change

1. Keep the change focused and explain its user-visible effect.
2. Do not commit selected text, diagnostic logs, credentials, downloaded models,
   generated installers, or Microsoft runtime binaries.
3. Add or update tests for behavior changes.
4. Run the local checks:

   ```powershell
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest
   uv run ty check --python-platform win32
   uv build
   ```

Native changes should also be built with `build-tools\native\build.ps1`.
Installer changes should be checked with
`build-tools\installer\build_installer.ps1` and
`build-tools\installer\smoke_test.ps1` where practical. Generated intermediates
belong in `.build\`, and distributable artifacts belong in `dist\`; neither
directory should be committed.

## Review and licensing

External contributions require maintainer review. By submitting a contribution,
you agree that it may be distributed under the repository's MIT License and
that you have the right to provide it under those terms. Report vulnerabilities
using the private process in `SECURITY.md`, not through a pull request or public
issue.
