[CmdletBinding()]
param(
    [string]$PortablePath,
    [string]$OutputPath,
    [string]$IsccPath,
    [string]$SupertonicLayerPath,
    [string]$SupertonicModelPath,
    [switch]$EmbedSupertonicPayload
)

$ErrorActionPreference = "Stop"
$buildToolsRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $buildToolsRoot
$toolsRoot = Join-Path $buildToolsRoot "tools"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$portableRoot = if ($PortablePath) { $PortablePath } else { Join-Path $projectRoot "dist\SelectSpeak" }
$outputRoot = if ($OutputPath) { $OutputPath } else { Join-Path $projectRoot "dist" }
$icon = Join-Path $projectRoot ".build\packaging\SelectSpeak.ico"
$definition = Join-Path $PSScriptRoot "SelectSpeak.iss"
$installerInfo = Join-Path $projectRoot "docs\INSTALLATION_NOTICE.txt"
$runtimeInstaller = Join-Path $buildToolsRoot "runtime\install_speech_runtime.ps1"
$runtimePackages = Join-Path $projectRoot "src\native\natural_voice\packages.config"
$supertonicInstaller = Join-Path $buildToolsRoot "supertonic\install_payload.ps1"
$nugetRoot = Join-Path $projectRoot ".cache\natural_voice\tools"
$nuget = Join-Path $nugetRoot "nuget.exe"
$nugetSha256 = "0790BB7A0C898E44B70F2B65E3070B4DB8AF23897E38B8653D72D268B6E8BB11"

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
    throw "Run .\scripts\install.ps1 before building a release."
}
if (-not (Test-Path -LiteralPath $portableRoot -PathType Container)) {
    throw "Portable distribution not found: $portableRoot"
}

New-Item -ItemType Directory -Path $nugetRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $nuget -PathType Leaf)) {
    [Net.ServicePointManager]::SecurityProtocol = `
        [Net.ServicePointManager]::SecurityProtocol -bor `
        [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest `
        -Uri "https://dist.nuget.org/win-x86-commandline/v6.12.1/nuget.exe" `
        -OutFile $nuget
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nuget).Hash -ne $nugetSha256) {
    throw "The NuGet executable did not match its pinned SHA-256 hash."
}

& $python (Join-Path $toolsRoot "verify_dist.py") $portableRoot
if ($LASTEXITCODE) { throw "Portable distribution verification failed." }

$projectMetadata = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
$versionMatch = [regex]::Match($projectMetadata, '(?m)^version\s*=\s*"(?<version>[^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the application version from pyproject.toml."
}
$version = $versionMatch.Groups["version"].Value
$defaultLayerPath = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Dependencies-$version-win-x64.zip"
$defaultModelPath = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Model-$version.zip"
$SupertonicLayerPath = if ($SupertonicLayerPath) { $SupertonicLayerPath } else { $defaultLayerPath }
$SupertonicModelPath = if ($SupertonicModelPath) { $SupertonicModelPath } else { $defaultModelPath }
foreach ($payload in @($SupertonicLayerPath, $SupertonicModelPath, $supertonicInstaller)) {
    if (-not (Test-Path -LiteralPath $payload -PathType Leaf)) {
        throw "Required Supertonic installer payload not found: $payload"
    }
}
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
    & $python (Join-Path $toolsRoot "create_icon.py") $icon
    if ($LASTEXITCODE) { throw "Icon generation failed." }
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$compiler = Find-InnoCompiler $IsccPath
$portableRoot = (Resolve-Path -LiteralPath $portableRoot).Path
$outputRoot = (Resolve-Path -LiteralPath $outputRoot).Path
$icon = (Resolve-Path -LiteralPath $icon).Path
$installerInfo = (Resolve-Path -LiteralPath $installerInfo).Path
$nuget = (Resolve-Path -LiteralPath $nuget).Path
$runtimeInstaller = (Resolve-Path -LiteralPath $runtimeInstaller).Path
$runtimePackages = (Resolve-Path -LiteralPath $runtimePackages).Path
$supertonicInstaller = (Resolve-Path -LiteralPath $supertonicInstaller).Path
$SupertonicLayerPath = (Resolve-Path -LiteralPath $SupertonicLayerPath).Path
$SupertonicModelPath = (Resolve-Path -LiteralPath $SupertonicModelPath).Path
$layerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SupertonicLayerPath).Hash.ToLowerInvariant()
$modelHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SupertonicModelPath).Hash.ToLowerInvariant()
$releaseBaseUrl = "https://github.com/Shayman-M-86/my-TTS/releases/download/v$version"
$compilerArguments = @(
    "/Qp",
    "/DAppVersion=$version",
    "/DAppNumericVersion=$numericVersion",
    "/DSourceDir=$portableRoot",
    "/DOutputDir=$outputRoot",
    "/DSetupIcon=$icon",
    "/DInstallerInfo=$installerInfo",
    "/DNuGetExe=$nuget",
    "/DRuntimeInstaller=$runtimeInstaller",
    "/DRuntimePackages=$runtimePackages",
    "/DSupertonicInstaller=$supertonicInstaller",
    "/DSupertonicLayerVersion=1",
    "/DSupertonicModelRevision=724fb5abbf5502583fb520898d45929e62f02c0b",
    "/DSupertonicLayerUrl=$releaseBaseUrl/$(Split-Path -Leaf $SupertonicLayerPath)",
    "/DSupertonicLayerFileName=$(Split-Path -Leaf $SupertonicLayerPath)",
    "/DSupertonicLayerSha256=$layerHash",
    "/DSupertonicModelUrl=$releaseBaseUrl/$(Split-Path -Leaf $SupertonicModelPath)",
    "/DSupertonicModelFileName=$(Split-Path -Leaf $SupertonicModelPath)",
    "/DSupertonicModelSha256=$modelHash"
)
if ($EmbedSupertonicPayload) {
    $compilerArguments += @(
        "/DEmbedSupertonicPayload=1",
        "/DSupertonicLayerArchive=$SupertonicLayerPath",
        "/DSupertonicModelArchive=$SupertonicModelPath"
    )
}
$compilerArguments += $definition

& $compiler @compilerArguments
if ($LASTEXITCODE) { throw "Inno Setup failed with exit code $LASTEXITCODE" }

$installer = Join-Path $outputRoot "SelectSpeak-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Inno Setup did not create the expected installer: $installer"
}
$installerInfo = Get-Item -LiteralPath $installer
if ($installerInfo.Length -lt 1MB) {
    throw "The generated installer is unexpectedly small: $($installerInfo.Length) bytes"
}
& (Join-Path $toolsRoot "verify_windows_metadata.ps1") `
    -Files $installer `
    -ExpectedVersion $version
if ($LASTEXITCODE) { throw "Installer metadata verification failed." }
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$hashFile = "$installer.sha256"
"$hash  $($installerInfo.Name)" | Set-Content -LiteralPath $hashFile -Encoding ascii

Write-Host "SelectSpeak installer created at $installer" -ForegroundColor Green
Write-Host "SHA256: $hash" -ForegroundColor Green
