<#
.SYNOPSIS
    Rebuild SelectSpeak.UI and run SelectSpeak against it.

.DESCRIPTION
    run.ps1 launches the UI on its own, which proves the XAML parses but shows
    nothing useful: the UI is deliberately dumb, so with no backend connected
    the reader keeps its placeholder, the transport buttons do nothing, and the
    gear cannot open settings - the gear asks Python to open it, and Python is
    what replies with show_settings.

    So this builds the UI and then starts the real application with
    SELECTSPEAK_UI=winui, which launches the UI itself and drives it.

    SelectSpeak allows one instance, so quit any copy in the tray first.

.EXAMPLE
    .\preview.ps1

.EXAMPLE
    .\preview.ps1 -NoBuild
    Skip the rebuild and just run.
#>
[CmdletBinding()]
param(
    # Skip the build and just run.
    [switch]$NoBuild
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$project = Join-Path $PSScriptRoot 'SelectSpeak.UI.csproj'

if (-not $NoBuild) {
    # The backend launches the UI, but a running instance still locks the
    # output, so a stale binary would silently survive the build.
    Get-Process -Name 'SelectSpeak.UI', 'XamlCompiler' -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "stopping $($_.ProcessName) (pid $($_.Id))" -ForegroundColor DarkGray
        Stop-Process -Id $_.Id -Force
    }
    Start-Sleep -Milliseconds 400

    Write-Host 'building...' -ForegroundColor Cyan
    $output = & dotnet build $project -c Debug --nologo -nodeReuse:false 2>&1
    if ($LASTEXITCODE -ne 0) {
        $output | Where-Object { $_ -match 'error' } | ForEach-Object {
            Write-Host $_ -ForegroundColor Red
        }
        Write-Host 'BUILD FAILED' -ForegroundColor Red
        exit 1
    }
    if ($output | Where-Object { $_ -match 'MSB3026|MSB3027' }) {
        Write-Host 'BUILD STALE: output file was locked, binary not updated' -ForegroundColor Red
        exit 1
    }
}

# The repo's virtualenv, not whichever python is on PATH: the backend needs
# pywin32 for the clipboard and the named pipe, and a system interpreter fails
# at import with ModuleNotFoundError: No module named 'win32clipboard'.
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "no virtualenv at $python" -ForegroundColor Red
    Write-Host 'Create one with: uv sync' -ForegroundColor Yellow
    exit 1
}

# One instance at a time: a copy already in the tray holds the mutex, and this
# would exit immediately with nothing on screen.
$running = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '-m\s+selectspeak' }
if ($running) {
    Write-Host 'SelectSpeak is already running; quit it from the tray first.' -ForegroundColor Yellow
    Write-Host "  (pid $($running.ProcessId -join ', '))" -ForegroundColor DarkGray
    exit 1
}

$env:PYTHONPATH = Join-Path $root 'src\python'
$env:SELECTSPEAK_UI = 'winui'

Write-Host 'starting SelectSpeak with the WinUI player...' -ForegroundColor Cyan
Write-Host 'Ctrl+C here closes both the backend and the UI.' -ForegroundColor DarkGray
& $python -m selectspeak
