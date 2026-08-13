[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$MsixPath,
    [string]$DestinationRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sourcePath = (Resolve-Path -LiteralPath $MsixPath -ErrorAction Stop).Path

if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw "Natural Voice package is not a file: $sourcePath"
}
$extension = [IO.Path]::GetExtension($sourcePath)
if ($extension -notin @(".msix", ".appx")) {
    throw "Natural Voice package must be an .msix or .appx file: $sourcePath"
}
if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path $projectRoot ".runtime\native\voices"
}
$voiceRoot = [IO.Path]::GetFullPath($DestinationRoot)
New-Item -ItemType Directory -Path $voiceRoot -Force | Out-Null
$voiceRootPrefix = $voiceRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + `
    [IO.Path]::DirectorySeparatorChar

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($sourcePath)
$targetCreated = $false
try {
    $manifestEntry = $archive.GetEntry("AppxManifest.xml")
    if (-not $manifestEntry) {
        throw "Natural Voice package has no AppxManifest.xml: $sourcePath"
    }
    $reader = [IO.StreamReader]::new($manifestEntry.Open())
    try {
        [xml]$manifest = $reader.ReadToEnd()
    } finally {
        $reader.Dispose()
    }

    $identity = $manifest.Package.Identity
    $name = [string]$identity.Name
    $version = [string]$identity.Version
    $architecture = [string]$identity.ProcessorArchitecture
    if (-not $name.StartsWith("MicrosoftWindows.Voice.")) {
        throw "Package is not a Microsoft Windows voice package: $name"
    }
    foreach ($component in @($name, $version, $architecture)) {
        if (-not $component -or $component -notmatch "^[A-Za-z0-9._-]+$") {
            throw "Package manifest contains an unsafe identity component."
        }
    }

    $folderName = "${name}_${version}_${architecture}"
    $targetPath = [IO.Path]::GetFullPath((Join-Path $voiceRoot $folderName))
    if (-not $targetPath.StartsWith(
            $voiceRootPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Refusing to extract outside the Natural Voice runtime folder."
    }

    $tokenPath = Join-Path $targetPath "Tokens.xml"
    if (Test-Path -LiteralPath $targetPath -PathType Container) {
        if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) {
            throw "Pinned voice folder already exists but is incomplete: $targetPath"
        }
        Write-Host "Natural Voice is already pinned at $targetPath" `
            -ForegroundColor Green
        Write-Output $targetPath
        return
    }

    New-Item -ItemType Directory -Path $targetPath | Out-Null
    $targetCreated = $true
    $targetPrefix = $targetPath.TrimEnd([IO.Path]::DirectorySeparatorChar) + `
        [IO.Path]::DirectorySeparatorChar

    foreach ($entry in $archive.Entries) {
        if (-not $entry.FullName) {
            continue
        }
        $entryPath = [IO.Path]::GetFullPath(
            (Join-Path $targetPath $entry.FullName)
        )
        if (-not $entryPath.StartsWith(
                $targetPrefix,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "Package contains a path outside its extraction folder."
        }
        if (-not $entry.Name) {
            New-Item -ItemType Directory -Path $entryPath -Force | Out-Null
            continue
        }
        $entryParent = Split-Path -Parent $entryPath
        New-Item -ItemType Directory -Path $entryParent -Force | Out-Null
        $inputStream = $entry.Open()
        $outputStream = [IO.File]::Create($entryPath)
        try {
            $inputStream.CopyTo($outputStream)
        } finally {
            $outputStream.Dispose()
            $inputStream.Dispose()
        }
    }

    if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) {
        throw "Extracted package has no Tokens.xml and cannot be used as a voice."
    }
    Write-Host "Pinned Natural Voice $name $version at $targetPath" `
        -ForegroundColor Green
    Write-Output $targetPath
} catch {
    if ($targetCreated -and
        (Test-Path -LiteralPath $targetPath -PathType Container)) {
        $resolvedTarget = [IO.Path]::GetFullPath($targetPath)
        if ($resolvedTarget.StartsWith(
                $voiceRootPrefix,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
        }
    }
    throw
} finally {
    $archive.Dispose()
}
