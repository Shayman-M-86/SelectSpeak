[CmdletBinding()]
param(
    [string]$Source,
    [string]$Destination,
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$buildToolsRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $buildToolsRoot
if (-not $Source) {
    $Source = Join-Path $projectRoot ".build\winui\bin\$Configuration\net8.0-windows10.0.19041.0\win-x64"
}
if (-not $Destination) {
    $Destination = Join-Path $projectRoot ".build\staging\winui"
}

$sourceRoot = [IO.Path]::GetFullPath($Source)
$destinationRoot = [IO.Path]::GetFullPath($Destination)
$stagingRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot ".build\staging"))
if (-not $destinationRoot.StartsWith(
        $stagingRoot.TrimEnd('\') + '\',
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Player staging destination must remain below $stagingRoot"
}
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "The SelectSpeak player has not been built: $sourceRoot"
}

# Compiled XAML is the part that goes missing silently, so it is named
# explicitly rather than trusted to arrive with the rest of the folder.
$requiredFiles = @(
    "SelectSpeak.UI.exe",
    "SelectSpeak.UI.dll",
    "SelectSpeak.UI.pri",
    "App.xbf",
    "Views\PlayerWindow.xbf",
    "Views\SettingsWindow.xbf"
)
$missing = @($requiredFiles | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $sourceRoot $_) -PathType Leaf)
})
if ($missing.Count) {
    throw "The built player is missing required files: $($missing -join ', ')"
}

# Debug symbols are build output, not something a release ships.
$excludedExtensions = @(".pdb")

if (Test-Path -LiteralPath $destinationRoot) {
    Remove-Item -LiteralPath $destinationRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null

$staged = 0
foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File) {
    if ($excludedExtensions -contains $file.Extension.ToLowerInvariant()) {
        continue
    }
    $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart('\')
    $target = Join-Path $destinationRoot $relative
    $targetParent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $targetParent)) {
        New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
    }
    Copy-Item -LiteralPath $file.FullName -Destination $target
    $staged++
}

# Re-check after the copy: an exclusion rule that grew too broad would
# otherwise remove the compiled XAML and only fail at runtime.
$missingAfterCopy = @($requiredFiles | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $destinationRoot $_) -PathType Leaf)
})
if ($missingAfterCopy.Count) {
    throw "Staging dropped required player files: $($missingAfterCopy -join ', ')"
}

$manifest = foreach ($name in $requiredFiles) {
    $file = Get-Item -LiteralPath (Join-Path $destinationRoot $name)
    [ordered]@{
        name = $name
        size = $file.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash
    }
}
$manifest | ConvertTo-Json | Set-Content `
    -LiteralPath (Join-Path (Split-Path -Parent $destinationRoot) "winui-manifest.json") `
    -Encoding UTF8
Write-Host "Staged $staged player files at $destinationRoot"
