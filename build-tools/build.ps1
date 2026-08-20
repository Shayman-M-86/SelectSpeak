<#
    .SYNOPSIS
    Build SelectSpeak: the app, the native bridge, the player, and the installer.

    .DESCRIPTION
    This is the one command an ordinary build needs:

        .\build-tools\build.ps1

    It produces dist\SelectSpeak and dist\SelectSpeak-Setup-<version>.exe.

    The optional Supertonic payloads are large and rarely change, so they are
    reused when a compatible pair is already present rather than rebuilt every
    time. A release build regenerates them, because their download URLs are
    published under the release tag - see -RebuildSupertonicPayload.

    .PARAMETER SkipInstaller
    Build only the portable dist\SelectSpeak folder.

    .PARAMETER RebuildSupertonicPayload
    Rebuild the Supertonic dependency and model archives at the current
    version. Required for a real release; downloads roughly 371 MB.

    .PARAMETER ReleaseReady
    Fail rather than reusing payloads whose version does not match the
    application. The Distribution workflow uses this so a release can never
    ship an installer pointing at archives that will not exist.
#>
[CmdletBinding()]
param(
    [switch]$SkipNativeBuild,
    [switch]$SkipWinUiBuild,
    [switch]$SkipInstaller,
    [switch]$RebuildSupertonicPayload,
    [switch]$ReleaseReady,
    [string]$SupertonicModelSource,
    # Retained so existing scripts and habits keep working; reuse is now the
    # default, so this only suppresses the rebuild that -RebuildSupertonicPayload
    # asks for.
    [switch]$SkipSupertonicPayload
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$installerRoot = Join-Path $PSScriptRoot "installer"
$appBuildRoot = Join-Path $PSScriptRoot "app"
$toolsRoot = Join-Path $PSScriptRoot "tools"
$supertonicRoot = Join-Path $PSScriptRoot "supertonic"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$distRoot = Join-Path $projectRoot "dist\SelectSpeak"
$nativeStage = Join-Path $projectRoot ".build\staging\native"
$winuiStage = Join-Path $projectRoot ".build\staging\winui"
$licenseStage = Join-Path $projectRoot ".build\staging\licenses"
$icon = Join-Path $projectRoot ".build\packaging\SelectSpeak.ico"
$projectMetadata = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
$versionMatch = [regex]::Match($projectMetadata, '(?m)^version\s*=\s*"(?<version>[^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the application version from pyproject.toml."
}
$version = $versionMatch.Groups["version"].Value
$layerArchive = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Dependencies-$version-win-x64.zip"
$modelArchive = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Model-$version.zip"

function Find-SupertonicPayload {
    <#
        .SYNOPSIS
        Locate a usable Supertonic archive, preferring the current version.

        .DESCRIPTION
        These archives are hundreds of megabytes and change far less often than
        the application version, so an ordinary local build reuses whichever
        compatible pair is already in dist\ instead of downloading them again.
        The newest is chosen when several are present.
    #>
    param(
        [Parameter(Mandatory)][string]$Preferred,
        [Parameter(Mandatory)][string]$Pattern
    )

    if (Test-Path -LiteralPath $Preferred -PathType Leaf) {
        return $Preferred
    }
    $candidate = Get-ChildItem -LiteralPath (Join-Path $projectRoot "dist") -Filter $Pattern `
        -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }
    return ""
}

# A payload is rebuilt when asked for, and otherwise only when nothing usable
# exists. -SkipSupertonicPayload forces reuse even when a rebuild was requested.
$rebuildPayload = $RebuildSupertonicPayload -and (-not $SkipSupertonicPayload)
if (-not $rebuildPayload) {
    $resolvedLayer = Find-SupertonicPayload -Preferred $layerArchive `
        -Pattern "SelectSpeak-Supertonic-Dependencies-*-win-x64.zip"
    $resolvedModel = Find-SupertonicPayload -Preferred $modelArchive `
        -Pattern "SelectSpeak-Supertonic-Model-*.zip"
    if ($resolvedLayer -and $resolvedModel) {
        $layerArchive = $resolvedLayer
        $modelArchive = $resolvedModel
    } elseif (-not $SkipInstaller -and -not $SkipSupertonicPayload) {
        # Nothing to reuse, and the installer needs both, so build them.
        Write-Host "No Supertonic payload found; building it once." -ForegroundColor Yellow
        $rebuildPayload = $true
        $layerArchive = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Dependencies-$version-win-x64.zip"
        $modelArchive = Join-Path $projectRoot "dist\SelectSpeak-Supertonic-Model-$version.zip"
    }
}

# The installer publishes each payload's download URL under this release's tag,
# so a reused archive from another version would point at a file that is never
# uploaded. Harmless while testing locally, wrong in a release.
$payloadVersionMatches =
    ((Split-Path -Leaf $layerArchive) -eq "SelectSpeak-Supertonic-Dependencies-$version-win-x64.zip") -and
    ((Split-Path -Leaf $modelArchive) -eq "SelectSpeak-Supertonic-Model-$version.zip")
if (-not $rebuildPayload -and -not $payloadVersionMatches -and -not $SkipInstaller) {
    $message = "Reusing Supertonic payloads from another version: " +
        "$(Split-Path -Leaf $layerArchive), $(Split-Path -Leaf $modelArchive)."
    if ($ReleaseReady) {
        throw "$message Run with -RebuildSupertonicPayload to build them for $version."
    }
    Write-Host $message -ForegroundColor Yellow
    Write-Host ("  Fine for local testing. A release needs " +
        "-RebuildSupertonicPayload so the download links resolve.") -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run .\scripts\install.ps1 before building a release."
}
if (-not $SkipNativeBuild) {
    & (Join-Path $PSScriptRoot "native\build.ps1")
    if ($LASTEXITCODE) { throw "Native release build failed." }
}
& (Join-Path $toolsRoot "stage_native.ps1")

if (-not $SkipWinUiBuild) {
    & (Join-Path $PSScriptRoot "winui\build.ps1")
    if ($LASTEXITCODE) { throw "SelectSpeak player build failed." }
}
& (Join-Path $toolsRoot "stage_winui.ps1")

if (Test-Path -LiteralPath $licenseStage) {
    Remove-Item -LiteralPath $licenseStage -Recurse -Force
}
New-Item -ItemType Directory -Path $licenseStage -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") `
    -Destination (Join-Path $licenseStage "LICENSE.SelectSpeak.txt")
Copy-Item -LiteralPath (Join-Path $projectRoot "PRIVACY.md") `
    -Destination $licenseStage
Copy-Item -LiteralPath `
    (Join-Path $projectRoot "src\native\natural_voice\THIRD_PARTY_NOTICES.md") `
    -Destination $licenseStage
& $python (Join-Path $toolsRoot "collect_licenses.py") $licenseStage
if ($LASTEXITCODE) { throw "License collection failed." }

& $python (Join-Path $toolsRoot "create_icon.py") $icon
if ($LASTEXITCODE) { throw "Icon generation failed." }

& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $projectRoot "dist") `
    --workpath (Join-Path $projectRoot ".build\pyinstaller") `
    (Join-Path $appBuildRoot "SelectSpeak.spec")
if ($LASTEXITCODE) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

Copy-Item -LiteralPath $nativeStage -Destination (Join-Path $distRoot "native") `
    -Recurse -Force
Copy-Item -LiteralPath $winuiStage -Destination (Join-Path $distRoot "ui") `
    -Recurse -Force
Copy-Item -LiteralPath $licenseStage -Destination (Join-Path $distRoot "licenses") `
    -Recurse -Force
& (Join-Path $toolsRoot "verify_windows_metadata.ps1") `
    -Files @(
        (Join-Path $distRoot "SelectSpeak.exe"),
        (Join-Path $distRoot "native\selectspeak_native.dll"),
        (Join-Path $distRoot "ui\SelectSpeak.UI.exe")
    ) `
    -ExpectedVersion $version
if ($LASTEXITCODE) { throw "Windows metadata verification failed." }
& $python (Join-Path $toolsRoot "verify_dist.py") $distRoot
if ($LASTEXITCODE) { throw "Portable distribution verification failed." }
Write-Host "Portable SelectSpeak build created at $distRoot" -ForegroundColor Green

if ($rebuildPayload) {
    $payloadArguments = @(
        (Join-Path $supertonicRoot "build_payload.py"),
        "--layer-output", $layerArchive,
        "--model-output", $modelArchive,
        "--staging-root", (Join-Path $projectRoot ".build\staging\supertonic")
    )
    if ($SupertonicModelSource) {
        $payloadArguments += @("--model-source", $SupertonicModelSource)
    }
    & $python @payloadArguments
    if ($LASTEXITCODE) { throw "Supertonic payload build failed." }

    $probeOutput = Join-Path $projectRoot ".build\supertonic-frozen-probe.json"
    if (Test-Path -LiteralPath $probeOutput) {
        Remove-Item -LiteralPath $probeOutput -Force
    }
    $probeEnvironment = @{
        SELECTSPEAK_SUPERTONIC_DEPENDENCIES = Join-Path $projectRoot `
            ".build\staging\supertonic\dependencies"
        SELECTSPEAK_SUPERTONIC_PROBE_MODEL = Join-Path $projectRoot `
            ".build\staging\supertonic\model"
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
    & (Join-Path $installerRoot "build_installer.ps1") `
        -PortablePath $distRoot `
        -SupertonicLayerPath $layerArchive `
        -SupertonicModelPath $modelArchive
    if ($LASTEXITCODE) { throw "Installer build failed." }
}

Write-Host ""
Write-Host "SelectSpeak $version build complete." -ForegroundColor Green
Write-Host "  Portable:  $distRoot"
if (-not $SkipInstaller) {
    Write-Host "  Installer: $(Join-Path $projectRoot "dist\SelectSpeak-Setup-$version.exe")"
}
