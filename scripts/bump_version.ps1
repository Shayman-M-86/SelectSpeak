[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectMetadata = [IO.File]::ReadAllText((Join-Path $projectRoot "pyproject.toml"))
$currentVersionMatch = [regex]::Match(
    $projectMetadata,
    '(?m)^version\s*=\s*"(?<version>\d+\.\d+\.\d+)"\s*$'
)
if (-not $currentVersionMatch.Success) {
    throw "Could not read the current version from pyproject.toml."
}
$currentVersion = $currentVersionMatch.Groups["version"].Value
Write-Host "Current SelectSpeak version: $currentVersion" -ForegroundColor Cyan

if (-not $Version) {
    $Version = Read-Host "Enter the new version (major.minor.patch)"
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use major.minor.patch, for example 0.1.3."
}

$numericVersion = "$Version.0"
$versionParts = @($Version.Split(".") | ForEach-Object { [int]$_ })
if ($versionParts.Where({ $_ -gt 65535 }).Count) {
    throw "Each version component must be between 0 and 65535."
}
$versionTuple = "($($versionParts -join ', '), 0)"
$updates = [ordered]@{}

function Set-VersionValue {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $path = Join-Path $projectRoot $RelativePath
    $text = if ($updates.Contains($path)) {
        [string]$updates[$path]
    } else {
        [IO.File]::ReadAllText($path)
    }
    $matches = [regex]::Matches($text, $Pattern)
    if ($matches.Count -ne 1) {
        throw "Expected one version field in $RelativePath but found $($matches.Count)."
    }
    $match = $matches[0]
    $valueGroup = $match.Groups["value"]
    if (-not $valueGroup.Success) {
        throw "Version pattern for $RelativePath has no named 'value' group."
    }
    $updates[$path] = $text.Substring(0, $valueGroup.Index) + $Value +
        $text.Substring($valueGroup.Index + $valueGroup.Length)
}

Set-VersionValue "pyproject.toml" `
    '(?m)^version\s*=\s*"(?<value>\d+\.\d+\.\d+)"\s*$' $Version
Set-VersionValue "uv.lock" `
    '(?ms)\[\[package\]\]\r?\nname = "selectspeak"\r?\nversion = "(?<value>\d+\.\d+\.\d+)"' $Version
Set-VersionValue "src\python\selectspeak\__init__.py" `
    '(?m)^__version__ = "(?<value>\d+\.\d+\.\d+)"\s*$' $Version
Set-VersionValue "src\native\CMakeLists.txt" `
    'set\(SELECTSPEAK_VERSION "(?<value>\d+\.\d+\.\d+)" CACHE STRING' $Version
Set-VersionValue "build-tools\app\SelectSpeak.manifest" `
    'version="(?<value>\d+\.\d+\.\d+\.\d+)"' $numericVersion
Set-VersionValue "build-tools\app\version_info.txt" `
    'filevers=(?<value>\(\d+, \d+, \d+, \d+\))' $versionTuple
Set-VersionValue "build-tools\app\version_info.txt" `
    'prodvers=(?<value>\(\d+, \d+, \d+, \d+\))' $versionTuple
Set-VersionValue "build-tools\app\version_info.txt" `
    'StringStruct\("FileVersion", "(?<value>\d+\.\d+\.\d+)"\)' $Version
Set-VersionValue "build-tools\app\version_info.txt" `
    'StringStruct\("ProductVersion", "(?<value>\d+\.\d+\.\d+)"\)' $Version
Set-VersionValue "build-tools\installer\SelectSpeak.iss" `
    '#define AppVersion "(?<value>\d+\.\d+\.\d+)"' $Version
Set-VersionValue "build-tools\installer\SelectSpeak.iss" `
    '#define AppNumericVersion "(?<value>\d+\.\d+\.\d+\.\d+)"' $numericVersion
Set-VersionValue "README.md" `
    'SelectSpeak-Setup-(?<value>\d+\.\d+\.\d+)\.exe' $Version

$utf8NoBom = New-Object Text.UTF8Encoding($false)
foreach ($path in $updates.Keys) {
    [IO.File]::WriteAllText($path, [string]$updates[$path], $utf8NoBom)
    $relativePath = $path.Substring($projectRoot.Length).TrimStart("\")
    Write-Host "Updated $relativePath"
}

Write-Host "SelectSpeak version is now $Version." -ForegroundColor Green
Write-Host "Run the test suite before committing and tagging v$Version."
