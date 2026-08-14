# Release checklist

This checklist covers local release preparation. The trusted hosted build and
code-signing workflow will be added separately.

## Repository

- [ ] Confirm the repository is public.
- [ ] Confirm GitHub detects the root MIT `LICENSE`.
- [ ] Review `PRIVACY.md`, `SECURITY.md`, and the code signing policy.
- [ ] Update the version in `pyproject.toml` and all generated metadata.
- [ ] Review third-party dependency and model licences.

## Verification

- [ ] Run Ruff lint and format checks, pytest, ty, and `uv build`.
- [ ] Build and run the native tests.
- [ ] Build the portable directory and installer from a clean checkout.
- [ ] Confirm SelectSpeak-owned EXE and DLL product names and versions agree.
- [ ] Run the isolated installer install/upgrade/uninstall smoke test.
- [ ] Confirm the installer displays its download and privacy notice.
- [ ] Scan the release files with current security tools.

## Unsigned release

- [ ] Publish the version tag.
- [ ] Upload Setup, its `.sha256` file, and both matching Supertonic archives.
- [ ] Mark the release and installer as unsigned until signing is operational.
- [ ] Document functionality, requirements, downloads, known limitations, and
      the code signing policy on the release page.
- [ ] Test installation from the published assets on a clean supported system.
