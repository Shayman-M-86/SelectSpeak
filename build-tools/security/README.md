# Dependency security audit

Run the release dependency audit from the repository root:

```powershell
.\build-tools\security\audit_dependencies.ps1
```

The command audits two Python sets from `uv.lock`: the core application and the
full application with every optional extra. It exports hashed requirements and
uses `pip-audit` in strict, non-resolving mode. It also restores the pinned
Microsoft Speech SDK `packages.config` with NuGet Audit enabled and treats
`NU1900` through `NU1905` as failures. Reports and temporary restore files are
written under the ignored `.build/security/` directory.

The audit requires internet access to retrieve current vulnerability data. Use
`-SkipPython` or `-SkipNuGet` only for focused local investigation; release
checks should run both. `-NuGetAuditLevel` accepts `low`, `moderate`, `high`, or
`critical` and defaults to `low`.

This is a known-vulnerability check, not a substitute for source review,
malware scanning, secret scanning, licence review, or testing the installer on
a clean Windows system.
