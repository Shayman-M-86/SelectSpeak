[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$NuGetPath,
    [Parameter(Mandatory = $true)][string]$PackagesConfig,
    [Parameter(Mandatory = $true)][string]$Destination
)

$ErrorActionPreference = "Stop"
$workRoot = Join-Path ([IO.Path]::GetTempPath()) `
    ("ssrt-" + [Guid]::NewGuid().ToString("N"))
$packagesRoot = Join-Path $workRoot "packages"
$runtimeFiles = @(
    "Microsoft.CognitiveServices.Speech.core.dll",
    "Microsoft.CognitiveServices.Speech.extension.embedded.tts.dll",
    "Microsoft.CognitiveServices.Speech.extension.onnxruntime.dll"
)

try {
    New-Item -ItemType Directory -Path $packagesRoot -Force | Out-Null
    & $NuGetPath install $PackagesConfig -OutputDirectory $packagesRoot `
        -Source "https://api.nuget.org/v3/index.json" `
        -NonInteractive -DisableParallelProcessing
    if ($LASTEXITCODE) {
        throw "NuGet restore failed with exit code $LASTEXITCODE"
    }

    $sources = @{}
    foreach ($name in $runtimeFiles) {
        $source = Get-ChildItem -Directory -LiteralPath $packagesRoot |
            ForEach-Object {
                Join-Path $_.FullName "runtimes\win-x64\native\$name"
            } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if (-not $source) {
            throw "NuGet did not provide the required runtime file: $name"
        }
        $sources[$name] = $source
    }

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($name in $runtimeFiles) {
        Copy-Item -LiteralPath $sources[$name] `
            -Destination (Join-Path $Destination $name) -Force
    }
} finally {
    if (Test-Path -LiteralPath $workRoot -PathType Container) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
    }
}
