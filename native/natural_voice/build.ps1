[CmdletBinding()]
param(
    [switch]$InstallPrerequisites
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runtimeRoot = Join-Path $projectRoot ".runtime"
$toolsRoot = Join-Path $runtimeRoot "tools"
$outputRoot = Join-Path $runtimeRoot "natural_voice"
$packagesRoot = Join-Path $PSScriptRoot "packages"
$buildRoot = Join-Path $PSScriptRoot "build"
$nuget = Join-Path $toolsRoot "nuget.exe"
$nugetSha256 = "0790BB7A0C898E44B70F2B65E3070B4DB8AF23897E38B8653D72D268B6E8BB11"

function Find-CMake {
    $pathCommand = Get-Command cmake -ErrorAction SilentlyContinue
    if ($pathCommand -and $pathCommand.CommandType -eq "Application" -and
        (Test-Path -LiteralPath $pathCommand.Source -PathType Leaf)) {
        return [string]$pathCommand.Source
    }

    $vswhere = Join-Path ${env:ProgramFiles(x86)} `
        "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere) {
        $installation = & $vswhere -latest -products * `
            -requires Microsoft.VisualStudio.Component.VC.CMake.Project `
            -property installationPath
        if ($installation) {
            $bundled = Join-Path $installation `
                "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
            if (Test-Path -LiteralPath $bundled) { return $bundled }
        }
    }
    return $null
}

$cmake = Find-CMake | Select-Object -First 1
if (-not $cmake -and $InstallPrerequisites) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "WinGet is required for automatic prerequisite installation."
    }
    Write-Host "Installing Visual Studio 2022 C++ Build Tools and CMake..."
    & $winget.Source install --id Microsoft.VisualStudio.2022.BuildTools `
        --exact --source winget --accept-package-agreements `
        --accept-source-agreements --override `
        "--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    if ($LASTEXITCODE) {
        throw "Build Tools installation failed with exit code $LASTEXITCODE"
    }
    $cmake = Find-CMake | Select-Object -First 1
}

if (-not $cmake -or -not (Test-Path -LiteralPath $cmake -PathType Leaf)) {
    throw @"
CMake and the Visual C++ toolchain were not found.

Run this script once with automatic prerequisite installation enabled:
    .\native\natural_voice\build.ps1 -InstallPrerequisites

This installs Visual Studio 2022 Build Tools with the C++ workload through WinGet.
"@
}

New-Item -ItemType Directory -Force -Path $toolsRoot, $outputRoot | Out-Null
if (-not (Test-Path -LiteralPath $nuget)) {
    Invoke-WebRequest -Uri "https://dist.nuget.org/win-x86-commandline/v6.12.1/nuget.exe" -OutFile $nuget
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nuget).Hash -ne $nugetSha256) {
    throw "The downloaded NuGet executable did not match its pinned SHA-256 hash"
}

& $nuget install (Join-Path $PSScriptRoot "packages.config") `
    -OutputDirectory $packagesRoot -NonInteractive
if ($LASTEXITCODE) { throw "NuGet restore failed with exit code $LASTEXITCODE" }

& $cmake -S $PSScriptRoot -B $buildRoot -A x64
if ($LASTEXITCODE) { throw "CMake configuration failed with exit code $LASTEXITCODE" }
& $cmake --build $buildRoot --config Release
if ($LASTEXITCODE) { throw "Native build failed with exit code $LASTEXITCODE" }

$bridge = Get-ChildItem -Recurse -LiteralPath $buildRoot `
    -Filter "selectspeak_natural_voice.dll" | Select-Object -First 1
if (-not $bridge) { throw "The build completed without producing the bridge DLL" }
Copy-Item -LiteralPath $bridge.FullName -Destination $outputRoot -Force

Get-ChildItem -Directory -LiteralPath $packagesRoot | ForEach-Object {
    $nativeRuntime = Join-Path $_.FullName "runtimes\win-x64\native"
    if (Test-Path -LiteralPath $nativeRuntime) {
        Copy-Item -Path (Join-Path $nativeRuntime "*") -Destination $outputRoot `
            -Recurse -Force
    }
}

Write-Host "Natural Voice runtime created at $outputRoot"
