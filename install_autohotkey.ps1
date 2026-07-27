$ErrorActionPreference = "Stop"

$version = "2.0.26"
$expectedHash = "43522aa3122a57784ac5db30abf85c2244475c36acd7796e2c993355f9e926ae"
$url = "https://github.com/AutoHotkey/AutoHotkey/releases/download/v$version/AutoHotkey_$version.zip"
$runtimeDirectory = Join-Path $PSScriptRoot ".runtime\autohotkey"
$temporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
    "selectspeak-autohotkey-" + [guid]::NewGuid().ToString("N")
)
$archivePath = Join-Path $temporaryDirectory "autohotkey.zip"
$extractPath = Join-Path $temporaryDirectory "extracted"

try {
    New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
    Write-Host "Downloading AutoHotkey v$version..."
    Invoke-WebRequest -Uri $url -OutFile $archivePath

    $actualHash = (Get-FileHash -Algorithm SHA256 -Path $archivePath).Hash.ToLower()
    if ($actualHash -ne $expectedHash) {
        throw "AutoHotkey archive hash did not match the pinned SHA-256."
    }

    Expand-Archive -Path $archivePath -DestinationPath $extractPath
    New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
    Copy-Item (
        Join-Path $extractPath "AutoHotkey64.exe"
    ) (
        Join-Path $runtimeDirectory "AutoHotkey64.exe"
    ) -Force
    Copy-Item (
        Join-Path $extractPath "license.txt"
    ) (
        Join-Path $runtimeDirectory "license.txt"
    ) -Force

    Write-Host "Installed portable AutoHotkey v$version in $runtimeDirectory"
} finally {
    if (Test-Path $temporaryDirectory) {
        Remove-Item -Recurse -Force $temporaryDirectory
    }
}
