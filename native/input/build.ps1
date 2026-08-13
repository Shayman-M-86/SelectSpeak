[CmdletBinding()]
param(
    [switch]$InstallPrerequisites
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$outputRoot = Join-Path $projectRoot ".runtime\input"
$buildRoot = Join-Path $PSScriptRoot "build"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "build_helpers.ps1")
$cmake = Get-SelectSpeakCMake -InstallPrerequisites:$InstallPrerequisites

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
& $cmake -S $PSScriptRoot -B $buildRoot -A x64
if ($LASTEXITCODE) { throw "CMake configuration failed with exit code $LASTEXITCODE" }
& $cmake --build $buildRoot --config Release
if ($LASTEXITCODE) { throw "Native build failed with exit code $LASTEXITCODE" }
$ctest = Join-Path (Split-Path -Parent $cmake) "ctest.exe"
if (-not (Test-Path -LiteralPath $ctest -PathType Leaf)) {
    throw "CMake was found without its CTest executable: $ctest"
}
& $ctest --test-dir $buildRoot -C Release --output-on-failure
if ($LASTEXITCODE) { throw "Native tests failed with exit code $LASTEXITCODE" }

$bridge = Get-ChildItem -Recurse -LiteralPath $buildRoot `
    -Filter "selectspeak_input.dll" | Select-Object -First 1
if (-not $bridge) { throw "The build completed without producing the input DLL" }
Copy-Item -LiteralPath $bridge.FullName -Destination $outputRoot -Force
Write-Host "Native input runtime created at $outputRoot"
