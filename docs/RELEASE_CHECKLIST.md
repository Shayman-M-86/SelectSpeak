# Release checklist

This checklist covers local release preparation and the trusted GitHub-hosted
unsigned distribution build. Code signing and release publication remain
separate approval steps.

## Repository

- [ ] Confirm the repository is public.
- [ ] Confirm GitHub detects the root MIT `LICENSE`.
- [ ] Review `PRIVACY.md`, `SECURITY.md`, and the code signing policy.
- [ ] Update the version in `pyproject.toml` and all generated metadata.
- [ ] Review third-party dependency and model licences.

## Verification

- [ ] Run Ruff lint and format checks, pytest, ty, and `uv build`.
- [ ] Run `build-tools\security\audit_dependencies.ps1` and review its reports.
- [ ] Confirm both jobs in the GitHub `CI` workflow pass.
- [ ] Build and run the native tests.
- [ ] Build the portable directory and installer from a clean checkout.
- [ ] Confirm SelectSpeak-owned EXE and DLL product names and versions agree.
- [ ] Run the isolated installer install/upgrade/uninstall smoke test.
- [ ] Confirm the installer displays its download and privacy notice.
- [ ] Scan the release files with current security tools.

## Unsigned release

- [ ] Publish the version tag.
- [ ] Manually start `Distribution` from the intended version commit.
- [ ] Confirm it completed on a GitHub-hosted Windows runner and passed its
      installer smoke test.
- [ ] Download and inspect the unsigned distribution workflow artifact.
- [ ] Upload Setup, its `.sha256` file, and both matching Supertonic archives.
- [ ] Mark the release and installer as unsigned until signing is operational.
- [ ] Document functionality, requirements, downloads, known limitations, and
      the code signing policy on the release page.
- [ ] Test installation from the published assets on a clean supported system.
