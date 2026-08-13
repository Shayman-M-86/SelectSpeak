[CmdletBinding()]
param(
    [string]$PortablePath,
    [string]$OutputPath,
    [string]$IsccPath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$portableRoot = if ($PortablePath) { $PortablePath } else { Join-Path $projectRoot "dist\SelectSpeak" }
$outputRoot = if ($OutputPath) { $OutputPath } else { Join-Path $projectRoot "dist" }
$icon = Join-Path $projectRoot "build\packaging\SelectSpeak.ico"
$definition = Join-Path $PSScriptRoot "SelectSpeak.iss"

function Find-InnoCompiler {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw "The requested Inno Setup compiler does not exist: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    throw @"
Inno Setup 6 is required to build the installer. Install it with:
winget install --id JRSoftware.InnoSetup --exact
"@
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run .\install.ps1 before building a release."
}
if (-not (Test-Path -LiteralPath $portableRoot -PathType Container)) {
    throw "Portable distribution not found: $portableRoot"
}

& $python (Join-Path $PSScriptRoot "verify_dist.py") $portableRoot
if ($LASTEXITCODE) { throw "Portable distribution verification failed." }

$projectMetadata = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
$versionMatch = [regex]::Match($projectMetadata, '(?m)^version\s*=\s*"(?<version>[^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the application version from pyproject.toml."
}
$version = $versionMatch.Groups["version"].Value
$releaseVersion = $version.Split("-", 2)[0]
$versionParts = @($releaseVersion.Split("."))
if ($versionParts.Count -gt 4 -or $versionParts.Where({ $_ -notmatch '^\d+$' }).Count) {
    throw "The release version cannot be converted to a Windows file version: $version"
}
while ($versionParts.Count -lt 4) {
    $versionParts += "0"
}
$numericVersion = $versionParts -join "."

if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    & $python (Join-Path $PSScriptRoot "create_icon.py") $icon
    if ($LASTEXITCODE) { throw "Icon generation failed." }
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$compiler = Find-InnoCompiler $IsccPath
$portableRoot = (Resolve-Path -LiteralPath $portableRoot).Path
$outputRoot = (Resolve-Path -LiteralPath $outputRoot).Path
$icon = (Resolve-Path -LiteralPath $icon).Path

& $compiler /Qp `
    "/DAppVersion=$version" `
    "/DAppNumericVersion=$numericVersion" `
    "/DSourceDir=$portableRoot" `
    "/DOutputDir=$outputRoot" `
    "/DSetupIcon=$icon" `
    $definition
if ($LASTEXITCODE) { throw "Inno Setup failed with exit code $LASTEXITCODE" }

$installer = Join-Path $outputRoot "SelectSpeak-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Inno Setup did not create the expected installer: $installer"
}
$installerInfo = Get-Item -LiteralPath $installer
if ($installerInfo.Length -lt 1MB) {
    throw "The generated installer is unexpectedly small: $($installerInfo.Length) bytes"
}
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$hashFile = "$installer.sha256"
"$hash  $($installerInfo.Name)" | Set-Content -LiteralPath $hashFile -Encoding ascii

Write-Host "SelectSpeak installer created at $installer" -ForegroundColor Green
Write-Host "SHA256: $hash" -ForegroundColor Green
