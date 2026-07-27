# Adds SelectSpeak to the Windows startup folder so it runs at login.
# Run once: right-click -> "Run with PowerShell"

$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath  = Join-Path $startupFolder "SelectSpeak.lnk"
$runScript     = Join-Path $PSScriptRoot "run.vbs"

if (-not (Test-Path $runScript)) {
    Write-Host "ERROR: run.vbs not found next to this script." -ForegroundColor Red
    exit 1
}

$shell         = New-Object -ComObject WScript.Shell
$shortcut      = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath       = $runScript
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description      = "SelectSpeak - text-to-speech hotkey"
$shortcut.Save()

Write-Host "SelectSpeak added to startup." -ForegroundColor Green
Write-Host "  Shortcut : $shortcutPath"
Write-Host "  Target   : $runScript"
Write-Host ""
Write-Host "To remove, run uninstall_startup.ps1"
