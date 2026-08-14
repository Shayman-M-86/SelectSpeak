[CmdletBinding()]
param(
    [switch]$SkipNativeBuild,
    [switch]$SkipInstaller,
    [switch]$SkipSupertonicPayload,
    [string]$SupertonicModelSource
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$distRoot = Join-Path $projectRoot "dist\SelectSpeak"
$nativeStage = Join-Path $projectRoot "build\staging\native"
$licenseStage = Join-Path $projectRoot "build\staging\licenses"
$icon = Join-Path $projectRoot "build\packaging\SelectSpeak.ico"
$projectMetadata = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
$versionMatch = [regex]::Match($projectMetadata, '(?m)^version\s*=\s*"(?<version>[^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the application version from pyproject.toml."
}
$version = $versionMatch.Groups["version"].Value
$layerArchive = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Dependencies-$version-win-x64.zip"
$modelArchive = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Model-$version.zip"

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

if (-not $SkipSupertonicPayload) {
    $payloadArguments = @(
        (Join-Path $PSScriptRoot "build_supertonic_payload.py"),
        "--layer-output", $layerArchive,
        "--model-output", $modelArchive,
        "--staging-root", (Join-Path $projectRoot "build\staging\supertonic")
    )
    if ($SupertonicModelSource) {
        $payloadArguments += @("--model-source", $SupertonicModelSource)
    }
    & $python @payloadArguments
    if ($LASTEXITCODE) { throw "Supertonic payload build failed." }

    $probeOutput = Join-Path $projectRoot "build\supertonic-frozen-probe.json"
    if (Test-Path -LiteralPath $probeOutput) {
        Remove-Item -LiteralPath $probeOutput -Force
    }
    $probeEnvironment = @{
        SELECTSPEAK_SUPERTONIC_DEPENDENCIES = Join-Path $projectRoot `
            "build\staging\supertonic\dependencies"
        SELECTSPEAK_SUPERTONIC_PROBE_MODEL = Join-Path $projectRoot `
            "build\staging\supertonic\model"
        SELECTSPEAK_SUPERTONIC_PROBE_OUTPUT = $probeOutput
    }
    $previousProbeEnvironment = @{}
    foreach ($name in $probeEnvironment.Keys) {
        $previousProbeEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $probeEnvironment[$name], "Process")
    }
    try {
        $probe = Start-Process -FilePath (Join-Path $distRoot "SelectSpeak.exe") `
            -WorkingDirectory $distRoot -WindowStyle Hidden -PassThru
        if (-not $probe.WaitForExit(60000)) {
            Stop-Process -Id $probe.Id -Force -ErrorAction SilentlyContinue
            throw "The frozen Supertonic dependency probe timed out."
        }
    } finally {
        foreach ($name in $previousProbeEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $previousProbeEnvironment[$name],
                "Process"
            )
        }
    }
    if (-not (Test-Path -LiteralPath $probeOutput -PathType Leaf)) {
        throw "The frozen Supertonic dependency probe did not produce a result."
    }
    $probeResult = Get-Content -LiteralPath $probeOutput -Raw | ConvertFrom-Json
    if ($probeResult.status -ne "ok") {
        throw "The frozen Supertonic dependency probe failed: $($probeResult.message)"
    }
    Write-Host "Frozen Supertonic dependency layer verified." -ForegroundColor Green
}
if (-not $SkipInstaller) {
    & (Join-Path $PSScriptRoot "build_installer.ps1") `
        -PortablePath $distRoot `
        -SupertonicLayerPath $layerArchive `
        -SupertonicModelPath $modelArchive
    if ($LASTEXITCODE) { throw "Installer build failed." }
}
