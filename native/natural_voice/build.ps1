[CmdletBinding()]
param(
    [switch]$InstallPrerequisites
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runtimeRoot = Join-Path $projectRoot ".runtime"
$cacheRoot = Join-Path $projectRoot ".cache\natural_voice"
$toolsRoot = Join-Path $cacheRoot "tools"
$outputRoot = Join-Path $runtimeRoot "natural_voice"
$packagesRoot = Join-Path $cacheRoot "packages"
$buildRoot = Join-Path $PSScriptRoot "build"
$nuget = Join-Path $toolsRoot "nuget.exe"
$nugetSha256 = "0790BB7A0C898E44B70F2B65E3070B4DB8AF23897E38B8653D72D268B6E8BB11"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "build_helpers.ps1")
$cmake = Get-SelectSpeakCMake -InstallPrerequisites:$InstallPrerequisites

New-Item -ItemType Directory -Force -Path $toolsRoot, $outputRoot | Out-Null
if (-not (Test-Path -LiteralPath $nuget)) {
    [Net.ServicePointManager]::SecurityProtocol = `
        [Net.ServicePointManager]::SecurityProtocol -bor `
        [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://dist.nuget.org/win-x86-commandline/v6.12.1/nuget.exe" -OutFile $nuget
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nuget).Hash -ne $nugetSha256) {
    throw "The downloaded NuGet executable did not match its pinned SHA-256 hash"
}

& $nuget install (Join-Path $PSScriptRoot "packages.config") `
    -OutputDirectory $packagesRoot -NonInteractive
if ($LASTEXITCODE) { throw "NuGet restore failed with exit code $LASTEXITCODE" }

$speechSdkRoot = Join-Path $packagesRoot `
    "Microsoft.CognitiveServices.Speech.1.41.1"
& $cmake -S $PSScriptRoot -B $buildRoot -A x64 `
    "-DSPEECHSDK_ROOT=$speechSdkRoot"
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
