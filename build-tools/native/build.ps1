[CmdletBinding()]
param(
    [switch]$InstallPrerequisites,
    [switch]$SkipNaturalVoice,
    [switch]$DevRuntime,
    # Skip the native unit tests. CI and release builds run them; a developer
    # relaunching the application does not need them every time.
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$buildToolsRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $buildToolsRoot
$nativeSourceRoot = Join-Path $projectRoot "src\native"
$runtimeRoot = Join-Path $projectRoot ".runtime"
$outputRoot = Join-Path $runtimeRoot "native"
$cacheRoot = Join-Path $projectRoot ".cache\natural_voice"
$toolsRoot = Join-Path $cacheRoot "tools"
$packagesRoot = Join-Path $cacheRoot "packages"
$buildRoot = Join-Path $projectRoot ".build\native"
$nuget = Join-Path $toolsRoot "nuget.exe"
$nugetSha256 = "0790BB7A0C898E44B70F2B65E3070B4DB8AF23897E38B8653D72D268B6E8BB11"
$projectMetadata = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
$versionMatch = [regex]::Match($projectMetadata, '(?m)^version\s*=\s*"(?<version>[^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the application version from pyproject.toml."
}
$version = $versionMatch.Groups["version"].Value.Split("-", 2)[0]
. (Join-Path $PSScriptRoot "build_helpers.ps1")
$cmake = Get-SelectSpeakCMake -InstallPrerequisites:$InstallPrerequisites

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$speechRuntimeFiles = @(
    "Microsoft.CognitiveServices.Speech.core.dll",
    "Microsoft.CognitiveServices.Speech.extension.embedded.tts.dll",
    "Microsoft.CognitiveServices.Speech.extension.onnxruntime.dll"
)
$unusedSpeechRuntimeFiles = @(
    "Microsoft.CognitiveServices.Speech.extension.audio.sys.dll",
    "Microsoft.CognitiveServices.Speech.extension.codec.dll",
    "Microsoft.CognitiveServices.Speech.extension.kws.dll",
    "Microsoft.CognitiveServices.Speech.extension.kws.ort.dll",
    "Microsoft.CognitiveServices.Speech.extension.lu.dll",
    "Microsoft.CognitiveServices.Speech.extension.telemetry.dll"
)
foreach ($name in $unusedSpeechRuntimeFiles) {
    $path = Join-Path $outputRoot $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}
$configureArguments = @(
    "-S", $nativeSourceRoot,
    "-B", $buildRoot,
    "-A", "x64",
    "-DSELECTSPEAK_VERSION=$version",
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

    & $nuget install (Join-Path $nativeSourceRoot "natural_voice\packages.config") `
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
if (-not $SkipTests) {
    $ctest = Join-Path (Split-Path -Parent $cmake) "ctest.exe"
    if (-not (Test-Path -LiteralPath $ctest -PathType Leaf)) {
        throw "CMake was found without its CTest executable: $ctest"
    }
    & $ctest --test-dir $buildRoot -C Release --output-on-failure
    if ($LASTEXITCODE) { throw "Native tests failed with exit code $LASTEXITCODE" }
}

$bridge = Get-ChildItem -Recurse -LiteralPath $buildRoot `
    -Filter "selectspeak_native.dll" | Select-Object -First 1
if (-not $bridge) { throw "The build completed without producing the native DLL" }
Copy-Item -LiteralPath $bridge.FullName -Destination $outputRoot -Force

if ($DevRuntime -and -not $SkipNaturalVoice) {
    foreach ($name in $speechRuntimeFiles) {
        $source = Get-ChildItem -Directory -LiteralPath $packagesRoot |
            ForEach-Object {
                Join-Path $_.FullName "runtimes\win-x64\native\$name"
            } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if (-not $source) {
            throw "NuGet restore did not provide the development runtime file: $name"
        }
        Copy-Item -LiteralPath $source -Destination $outputRoot -Force
    }
}

$kind = if ($DevRuntime -and -not $SkipNaturalVoice) {
    "bridge and development runtime"
} else {
    "bridge"
}
Write-Host "SelectSpeak $kind created at $outputRoot"
