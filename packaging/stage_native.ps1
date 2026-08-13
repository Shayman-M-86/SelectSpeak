[CmdletBinding()]
param(
    [string]$Source,
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Source) {
    $Source = Join-Path $projectRoot ".runtime\native"
}
if (-not $Destination) {
    $Destination = Join-Path $projectRoot "build\staging\native"
}

$sourceRoot = [IO.Path]::GetFullPath($Source)
$destinationRoot = [IO.Path]::GetFullPath($Destination)
$stagingRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "build\staging"))
if (-not $destinationRoot.StartsWith(
        $stagingRoot.TrimEnd('\') + '\',
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Native staging destination must remain below $stagingRoot"
}
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "Native runtime has not been built: $sourceRoot"
}

$nativeFiles = @(
    "selectspeak_native.dll",
    "Microsoft.CognitiveServices.Speech.core.dll",
    "Microsoft.CognitiveServices.Speech.extension.audio.sys.dll",
    "Microsoft.CognitiveServices.Speech.extension.codec.dll",
    "Microsoft.CognitiveServices.Speech.extension.embedded.tts.dll",
    "Microsoft.CognitiveServices.Speech.extension.kws.dll",
    "Microsoft.CognitiveServices.Speech.extension.kws.ort.dll",
    "Microsoft.CognitiveServices.Speech.extension.lu.dll",
    "Microsoft.CognitiveServices.Speech.extension.onnxruntime.dll",
    "Microsoft.CognitiveServices.Speech.extension.telemetry.dll"
)

$missing = @($nativeFiles | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $sourceRoot $_) -PathType Leaf)
})
if ($missing.Count) {
    throw "Native release files are missing: $($missing -join ', ')"
}

if (Test-Path -LiteralPath $destinationRoot) {
    Remove-Item -LiteralPath $destinationRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
foreach ($name in $nativeFiles) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $name) `
        -Destination (Join-Path $destinationRoot $name)
}

$manifest = foreach ($name in $nativeFiles) {
    $file = Get-Item -LiteralPath (Join-Path $destinationRoot $name)
    [ordered]@{
        name = $name
        size = $file.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    }
}
$manifest | ConvertTo-Json | Set-Content `
    -LiteralPath (Join-Path (Split-Path -Parent $destinationRoot) "native-manifest.json") `
    -Encoding UTF8
Write-Host "Staged $($nativeFiles.Count) allowlisted native files at $destinationRoot"
