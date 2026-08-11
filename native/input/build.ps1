[CmdletBinding()]
param(
    [switch]$InstallPrerequisites
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outputRoot = Join-Path $projectRoot ".runtime\input"
$buildRoot = Join-Path $PSScriptRoot "build"

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

Run:
    .\native\input\build.ps1 -InstallPrerequisites
"@
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
& $cmake -S $PSScriptRoot -B $buildRoot -A x64
if ($LASTEXITCODE) { throw "CMake configuration failed with exit code $LASTEXITCODE" }
& $cmake --build $buildRoot --config Release
if ($LASTEXITCODE) { throw "Native build failed with exit code $LASTEXITCODE" }

$bridge = Get-ChildItem -Recurse -LiteralPath $buildRoot `
    -Filter "selectspeak_input.dll" | Select-Object -First 1
if (-not $bridge) { throw "The build completed without producing the input DLL" }
Copy-Item -LiteralPath $bridge.FullName -Destination $outputRoot -Force
Write-Host "Native input runtime created at $outputRoot"
