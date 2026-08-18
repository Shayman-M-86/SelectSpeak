<#
.SYNOPSIS
    Rebuild SelectSpeak.UI and relaunch it.

.DESCRIPTION
    WinUI 3 has no XAML hot reload outside Visual Studio, so every XAML change
    needs a rebuild. This stops any running instance first, because a live
    process holds the output DLL and the copy step fails silently, leaving the
    old binary in place - which looks exactly like the change having no effect.

    A clean `dotnet build` does not prove the XAML is valid: invalid properties
    compile fine and only fail when the window is created. So this reports
    whether the app actually stayed running.
#>
[CmdletBinding()]
param(
    # Leave the app running and return immediately.
    [switch]$NoWait
)

$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'SelectSpeak.UI.csproj'
$exe = Join-Path $PSScriptRoot '.build\bin\Debug\net8.0-windows10.0.19041.0\win-x64\SelectSpeak.UI.exe'

# The app locks its own output; the XAML compiler and MSBuild node reuse keep
# separate processes alive that lock the intermediate assembly. All three have
# to go, or the build "succeeds" against a stale binary.
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

# A locked output file only warns, so the build "succeeds" with a stale exe.
if ($output | Where-Object { $_ -match 'MSB3026|MSB3027' }) {
    Write-Host 'BUILD STALE: output file was locked, binary not updated' -ForegroundColor Red
    exit 1
}

Write-Host 'launching...' -ForegroundColor Cyan
$process = Start-Process -FilePath $exe -PassThru

if ($NoWait) {
    Write-Host "running (pid $($process.Id))" -ForegroundColor Green
    exit 0
}

# XAML parse errors kill the process within the first second or so.
Start-Sleep -Seconds 3
if ($process.HasExited) {
    Write-Host "CRASHED on startup, exit code 0x$('{0:X}' -f $process.ExitCode)" -ForegroundColor Red
    Write-Host 'A XamlParseException usually means an invalid property or resource name.' -ForegroundColor Yellow
    exit 1
}

Write-Host "running (pid $($process.Id))" -ForegroundColor Green
