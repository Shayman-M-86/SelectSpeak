[CmdletBinding()]
param(
    [switch]$SkipNativeBuild,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$distRoot = Join-Path $projectRoot "dist\SelectSpeak"
$nativeStage = Join-Path $projectRoot "build\staging\native"
$licenseStage = Join-Path $projectRoot "build\staging\licenses"
$icon = Join-Path $projectRoot "build\packaging\SelectSpeak.ico"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run .\install.ps1 before building a release."
}
if (-not $SkipNativeBuild) {
    & (Join-Path $projectRoot "native\build.ps1")
    if ($LASTEXITCODE) { throw "Native release build failed." }
}
& (Join-Path $PSScriptRoot "stage_native.ps1")

if (Test-Path -LiteralPath $licenseStage) {
    Remove-Item -LiteralPath $licenseStage -Recurse -Force
}
New-Item -ItemType Directory -Path $licenseStage -Force | Out-Null
Copy-Item -LiteralPath `
    (Join-Path $projectRoot "native\natural_voice\THIRD_PARTY_NOTICES.md") `
    -Destination $licenseStage
Copy-Item -LiteralPath `
    (Join-Path $projectRoot "native\natural_voice\LICENSE.TTS-anywhere.txt") `
    -Destination $licenseStage
& $python (Join-Path $PSScriptRoot "collect_licenses.py") $licenseStage
if ($LASTEXITCODE) { throw "License collection failed." }

& $python (Join-Path $PSScriptRoot "create_icon.py") $icon
if ($LASTEXITCODE) { throw "Icon generation failed." }

& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $projectRoot "dist") `
    --workpath (Join-Path $projectRoot "build\pyinstaller") `
    (Join-Path $PSScriptRoot "SelectSpeak.spec")
if ($LASTEXITCODE) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Copy-Item -LiteralPath $nativeStage -Destination (Join-Path $distRoot "native") `
    -Recurse -Force
Copy-Item -LiteralPath $licenseStage -Destination (Join-Path $distRoot "licenses") `
    -Recurse -Force
& $python (Join-Path $PSScriptRoot "verify_dist.py") $distRoot
if ($LASTEXITCODE) { throw "Portable distribution verification failed." }
Write-Host "Portable SelectSpeak build created at $distRoot" -ForegroundColor Green
if (-not $SkipInstaller) {
    & (Join-Path $PSScriptRoot "build_installer.ps1") -PortablePath $distRoot
    if ($LASTEXITCODE) { throw "Installer build failed." }
}
