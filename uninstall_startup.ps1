# Removes SelectSpeak from the Windows startup folder.
# Run once: right-click -> "Run with PowerShell"

$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath  = Join-Path $startupFolder "SelectSpeak.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath
    Write-Host "SelectSpeak removed from startup." -ForegroundColor Green
} else {
    Write-Host "SelectSpeak was not in the startup folder." -ForegroundColor Yellow
}
