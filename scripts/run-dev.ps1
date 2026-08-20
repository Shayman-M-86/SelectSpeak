<#
.SYNOPSIS
    Run SelectSpeak from this checkout, building anything that changed.

.DESCRIPTION
    The one command for using or testing SelectSpeak during development.

    Python is interpreted, so a change to it needs no build. The native bridge
    and the WinUI player are compiled, so this runs their ordinary incremental
    builds every time and then starts the application. CMake and MSBuild do
    their own dependency tracking, so an unchanged tree costs little more than
    the time they take to decide there is nothing to do.

    Run .\scripts\install-dev-dependencies.ps1 first; this script builds, it
    does not provision toolchains.

.EXAMPLE
    .\scripts\run-dev.ps1
    Build whatever changed, then run.

.EXAMPLE
    .\scripts\run-dev.ps1 -NoBuild
    Start immediately, using whatever was built last.

.EXAMPLE
    .\scripts\run-dev.ps1 -Release
    Use a Release player build rather than Debug.
#>
[CmdletBinding()]
param(
    # Start without building anything first.
    [switch]$NoBuild,
    # Build and run the Release player instead of Debug.
    [switch]$Release,
    # Return once SelectSpeak is running, rather than staying attached.
    [switch]$Detached
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configuration = if ($Release) { "Release" } else { "Debug" }
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$nativeDll = Join-Path $projectRoot ".runtime\native\selectspeak_native.dll"
$playerProject = Join-Path $projectRoot "src\winui\SelectSpeak.UI\SelectSpeak.UI.csproj"
$playerExe = Join-Path $projectRoot `
    ".build\winui\bin\$configuration\net8.0-windows10.0.19041.0\win-x64\SelectSpeak.UI.exe"

# Provisioning belongs to install-dev-dependencies.ps1. This reports what is
# missing and stops, rather than half-installing it.
$speechSdk = Join-Path $projectRoot ".cache\natural_voice\packages\Microsoft.CognitiveServices.Speech.1.41.1"
$missing = @(
    @{ Path = $python; Name = "the Python environment" },
    @{ Path = $speechSdk; Name = "the Speech SDK packages" }
) | Where-Object { -not (Test-Path -LiteralPath $_.Path) }
if ($missing) {
    Write-Host "Development dependencies are missing: $(($missing.Name) -join ', ')." -ForegroundColor Red
    Write-Host "Run .\scripts\install-dev-dependencies.ps1 first." -ForegroundColor Yellow
    exit 1
}

# One instance at a time: a copy already in the tray owns the mutex, so a second
# would exit immediately with nothing on screen and no explanation.
$running = Get-CimInstance Win32_Process `
    -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match '-m\s+selectspeak' }
if ($running) {
    Write-Host "SelectSpeak is already running (pid $($running.ProcessId -join ', '))." -ForegroundColor Yellow
    Write-Host "Quit it from the tray icon first." -ForegroundColor Yellow
    exit 1
}

if (-not $NoBuild) {
    # CMake decides whether anything needs compiling. The native tests are left
    # to CI and release builds rather than repeated on every launch.
    & (Join-Path $projectRoot "build-tools\native\build.ps1") -DevRuntime -SkipTests
    if ($LASTEXITCODE) { throw "The native bridge failed to build." }

    # A running player locks its own output, and MSBuild then reports success
    # having copied nothing - which looks exactly like the edit doing nothing.
    # The XAML compiler and reused MSBuild nodes hold locks of their own.
    Get-Process -Name "SelectSpeak.UI", "XamlCompiler" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-Host "stopping $($_.ProcessName) (pid $($_.Id))" -ForegroundColor DarkGray
            Stop-Process -Id $_.Id -Force
        }
    Start-Sleep -Milliseconds 400

    $output = & dotnet build $playerProject --configuration $configuration `
        --nologo -nodeReuse:false 2>&1
    if ($LASTEXITCODE) {
        $output | Where-Object { $_ -match "error" } | ForEach-Object {
            Write-Host $_ -ForegroundColor Red
        }
        throw "The player failed to build."
    }
    # A locked output file is only a warning, so the build reports success with
    # a stale binary still in place.
    if ($output | Where-Object { $_ -match "MSB3026|MSB3027" }) {
        throw "The player build could not replace a locked file, so the binary is stale."
    }
}

foreach ($required in @($nativeDll, $playerExe)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        Write-Host "Missing build output: $required" -ForegroundColor Red
        Write-Host "Run without -NoBuild, or run .\scripts\install-dev-dependencies.ps1." -ForegroundColor Yellow
        exit 1
    }
}

# Name the player explicitly. The backend otherwise prefers a Release build, so
# a Debug run would silently start a stale Release binary instead of the change
# being tested.
$env:SELECTSPEAK_WINUI_EXE = $playerExe
$env:PYTHONPATH = Join-Path $projectRoot "src\python"

Write-Host "Starting SelectSpeak ($configuration player)..." -ForegroundColor Green
if ($Detached) {
    Start-Process -FilePath $pythonw -ArgumentList @("-m", "selectspeak") `
        -WorkingDirectory $projectRoot -WindowStyle Hidden
    Write-Host "SelectSpeak is running. Quit it from the tray icon." -ForegroundColor Green
    exit 0
}

Write-Host "Ctrl+C closes both the backend and the player." -ForegroundColor DarkGray
& $python -m selectspeak
