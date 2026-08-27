# Release checklist

Replace the example version once, then run the steps in order from the repository root.
For a guided run through the same process, use `.\scripts\release.ps1`.

## 1. Prepare and merge the version bump

- [ ] Update every source-controlled version field with the version-bump script:

  ```powershell
  $Version = "0.1.3"
  .\scripts\bump_version.ps1 -Version $Version
  git diff --check
  ```

~~- [ ] Commit the generated version changes and merge them to `main` through the normal review process. Confirm the `CI` workflow passes on the merged commit.
- [ ] Add and review the release's user-visible changes and relevant known limitations in the matching version section of `CHANGELOG.md` before tagging. Leave `Unreleased` ready for future changes.~~

## 2. Tag the release

- [ ] Update local `main`, create the matching annotated tag, and push it:

  ```powershell
  git switch main
  git pull --ff-only origin main
  git tag -a "v$Version" -m "SelectSpeak $Version"
  git push origin "v$Version"
  ```

## 3. Build the release candidate

- [ ] On GitHub, open **Actions > Distribution > Run workflow**, select the `v$Version` tag, and start the workflow.

- [ ] Confirm both Distribution jobs pass and the workflow creates the unsigned draft GitHub Release. The workflow builds and verifies the portable app, installer, checksum, and matching Supertonic archives, including the installer lifecycle smoke test.

## 4. Review and publish

- [ ] Review the draft GitHub Release notes and make any necessary corrections. The workflow includes the matching `CHANGELOG.md` section automatically alongside the unsigned-release and installation boilerplate.
- [ ] Download the draft installer and manually verify on a clean supported Windows system that installation succeeds and the release's important user flows work, including text selection, speech playback, the configured hotkeys, OCR, and any changed functionality. Keep the release marked unsigned.
- [ ] Review the draft title and notes, then publish the draft from GitHub.
