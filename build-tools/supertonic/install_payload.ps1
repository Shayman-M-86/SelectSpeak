[CmdletBinding()]
param(
    [string]$LayerArchive,
    [string]$LayerDestination,
    [string]$ModelArchive,
    [string]$ModelDestination
)

$ErrorActionPreference = "Stop"

function Install-VerifiedArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Archive,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Manifest,
        [Parameter(Mandatory = $true)][string[]]$RequiredFiles
    )

    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
        throw "Optional component archive not found: $Archive"
    }
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = Join-Path $parent ("." + (Split-Path -Leaf $Destination) +
        "-" + [Guid]::NewGuid().ToString("N") + ".tmp")
    $backup = "$Destination.previous"
    try {
        Expand-Archive -LiteralPath $Archive -DestinationPath $temporary -Force
        if (-not (Test-Path -LiteralPath (Join-Path $temporary $Manifest) -PathType Leaf)) {
            throw "Optional component manifest is missing: $Manifest"
        }
        foreach ($relative in $RequiredFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $temporary $relative) -PathType Leaf)) {
                throw "Optional component is incomplete: $relative"
            }
        }
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $backup -Recurse -Force
        }
        if (Test-Path -LiteralPath $Destination) {
            Move-Item -LiteralPath $Destination -Destination $backup
        }
        Move-Item -LiteralPath $temporary -Destination $Destination
        if (Test-Path -LiteralPath $backup) {
            Remove-Item -LiteralPath $backup -Recurse -Force
        }
    } catch {
        if (-not (Test-Path -LiteralPath $Destination) -and
            (Test-Path -LiteralPath $backup)) {
            Move-Item -LiteralPath $backup -Destination $Destination
        }
        throw
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Recurse -Force
        }
    }
}

if (-not $LayerArchive -and -not $ModelArchive) {
    throw "No Supertonic payload was provided."
}
if ($LayerArchive) {
    if (-not $LayerDestination) { throw "LayerDestination is required with LayerArchive." }
    Install-VerifiedArchive `
        -Archive $LayerArchive `
        -Destination $LayerDestination `
        -Manifest "supertonic-layer.json" `
        -RequiredFiles @(
            "supertonic\__init__.py",
            "numpy\__init__.py",
            "onnxruntime\__init__.py"
        )
}
if ($ModelArchive) {
    if (-not $ModelDestination) { throw "ModelDestination is required with ModelArchive." }
    Install-VerifiedArchive `
        -Archive $ModelArchive `
        -Destination $ModelDestination `
        -Manifest "supertonic-model.json" `
        -RequiredFiles @(
            "onnx\tts.json",
            "onnx\unicode_indexer.json",
            "onnx\duration_predictor.onnx",
            "onnx\text_encoder.onnx",
            "onnx\vector_estimator.onnx",
            "onnx\vocoder.onnx",
            "voice_styles\F1.json",
            "voice_styles\F2.json",
            "voice_styles\F3.json",
            "voice_styles\F4.json",
            "voice_styles\F5.json",
            "voice_styles\M1.json",
            "voice_styles\M2.json",
            "voice_styles\M3.json",
            "voice_styles\M4.json",
            "voice_styles\M5.json"
        )
}
