[CmdletBinding()]
param(
    [switch]$InstallPrerequisites,
    [switch]$SkipNaturalVoice
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".runtime"
$outputRoot = Join-Path $runtimeRoot "native"
$cacheRoot = Join-Path $projectRoot ".cache\natural_voice"
$toolsRoot = Join-Path $cacheRoot "tools"
$packagesRoot = Join-Path $cacheRoot "packages"
$buildRoot = Join-Path $PSScriptRoot "build"
$nuget = Join-Path $toolsRoot "nuget.exe"
$nugetSha256 = "0790BB7A0C898E44B70F2B65E3070B4DB8AF23897E38B8653D72D268B6E8BB11"
. (Join-Path $PSScriptRoot "build_helpers.ps1")
$cmake = Get-SelectSpeakCMake -InstallPrerequisites:$InstallPrerequisites

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$configureArguments = @(
    "-S", $PSScriptRoot,
    "-B", $buildRoot,
    "-A", "x64",
    "-DSELECTSPEAK_ENABLE_NATURAL_VOICE=$(-not $SkipNaturalVoice)"
)

if (-not $SkipNaturalVoice) {
    New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
    if (-not (Test-Path -LiteralPath $nuget -PathType Leaf)) {
        [Net.ServicePointManager]::SecurityProtocol = `
            [Net.ServicePointManager]::SecurityProtocol -bor `
            [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest `
            -Uri "https://dist.nuget.org/win-x86-commandline/v6.12.1/nuget.exe" `
            -OutFile $nuget
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nuget).Hash `
        -ne $nugetSha256) {
        throw "The downloaded NuGet executable did not match its pinned SHA-256 hash"
    }

    & $nuget install (Join-Path $PSScriptRoot "natural_voice\packages.config") `
        -OutputDirectory $packagesRoot -NonInteractive
    if ($LASTEXITCODE) {
        throw "NuGet restore failed with exit code $LASTEXITCODE"
    }
    $speechSdkRoot = Join-Path $packagesRoot `
        "Microsoft.CognitiveServices.Speech.1.41.1"
    $configureArguments += "-DSPEECHSDK_ROOT=$speechSdkRoot"
}

& $cmake @configureArguments
if ($LASTEXITCODE) {
    throw "CMake configuration failed with exit code $LASTEXITCODE"
}
& $cmake --build $buildRoot --config Release
if ($LASTEXITCODE) { throw "Native build failed with exit code $LASTEXITCODE" }
$ctest = Join-Path (Split-Path -Parent $cmake) "ctest.exe"
if (-not (Test-Path -LiteralPath $ctest -PathType Leaf)) {
    throw "CMake was found without its CTest executable: $ctest"
}
& $ctest --test-dir $buildRoot -C Release --output-on-failure
if ($LASTEXITCODE) { throw "Native tests failed with exit code $LASTEXITCODE" }

$bridge = Get-ChildItem -Recurse -LiteralPath $buildRoot `
    -Filter "selectspeak_native.dll" | Select-Object -First 1
if (-not $bridge) { throw "The build completed without producing the native DLL" }
Copy-Item -LiteralPath $bridge.FullName -Destination $outputRoot -Force

if (-not $SkipNaturalVoice) {
    Get-ChildItem -Directory -LiteralPath $packagesRoot | ForEach-Object {
        $nativeRuntime = Join-Path $_.FullName "runtimes\win-x64\native"
        if (Test-Path -LiteralPath $nativeRuntime -PathType Container) {
            Copy-Item -Path (Join-Path $nativeRuntime "*") `
                -Destination $outputRoot -Recurse -Force
        }
    }
}

Write-Host "SelectSpeak native runtime created at $outputRoot"
