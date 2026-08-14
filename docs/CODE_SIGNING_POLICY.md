# Code signing policy

## Status

SelectSpeak is preparing to apply for open-source code signing. No build should
be represented as signed by SignPath Foundation until enrollment is approved
and its signature can be verified in the file's Windows properties.

For releases signed through that program, the project will use the required
credit:

> Free code signing provided by [SignPath.io](https://signpath.io/), certificate
> by [SignPath Foundation](https://signpath.org/).

Unsigned releases will remain clearly identified as unsigned.

## Roles

- Committer and reviewer: [Shayman-M-86](https://github.com/Shayman-M-86)
- Signing approver: [Shayman-M-86](https://github.com/Shayman-M-86)

External contributions require maintainer review. Every signing request must be
manually approved by the signing approver after the release source, version,
tests, installer contents, and checksums have been reviewed. Multi-factor
authentication is required for repository and signing-service access.

## Release rules

- Only SelectSpeak-owned binaries are submitted for a SelectSpeak signature.
- Upstream tools and libraries, including NuGet and Microsoft runtime DLLs, are
  not signed with the SelectSpeak signing identity.
- Product names and product versions must agree across SelectSpeak-owned release
  binaries.
- The signed artifact must be derived from the reviewed public source and the
  same automated build definition used for the release.
- A signing request requires manual approval and must not bypass the signing
  service's origin or policy checks.

See `PRIVACY.md` for the application's network and data-handling behavior and
`SECURITY.md` for vulnerability reporting.
