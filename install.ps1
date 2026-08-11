[CmdletBinding()]
param(
    [switch]$AddToStartup,
    [switch]$RemoveFromStartup,
    [switch]$Launch,
    [switch]$SkipNaturalVoice,
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonVersion = "3.13"

function Add-SelectSpeakToStartup {
    $startupFolder = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startupFolder "SelectSpeak.lnk"
    $runScript = Join-Path $projectRoot "run.vbs"
    $pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
    $inputBridge = Join-Path $projectRoot `
        ".runtime\input\selectspeak_input.dll"

    foreach ($requiredFile in @($runScript, $pythonw, $inputBridge)) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "SelectSpeak is not fully installed. Missing: $requiredFile"
        }
    }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot "System32\wscript.exe"
    $shortcut.Arguments = '"' + $runScript + '"'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = "SelectSpeak - text-to-speech hotkey"
    $shortcut.Save()
    Write-Host "SelectSpeak added to startup: $shortcutPath" `
        -ForegroundColor Green
}

function Remove-SelectSpeakFromStartup {
    $shortcutPath = Join-Path `
        ([Environment]::GetFolderPath("Startup")) "SelectSpeak.lnk"
    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        Remove-Item -LiteralPath $shortcutPath
        Write-Host "SelectSpeak removed from startup." -ForegroundColor Green
    } else {
        Write-Host "SelectSpeak was not in the startup folder." `
            -ForegroundColor Yellow
    }
}

function Find-Uv {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($command -and $command.CommandType -eq "Application") {
        return [string]$command.Source
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
    )
    $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $packageRoot -PathType Container) {
        $packageUv = Get-ChildItem -Path $packageRoot `
            -Filter "uv.exe" -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*astral-sh.uv*" } |
            Select-Object -First 1
        if ($packageUv) {
            $candidates += $packageUv.FullName
        }
    }
    return $candidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}

function Install-Uv {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw @"
WinGet is required for first-time setup but was not found.
Install Microsoft's App Installer, then run .\install.ps1 again.
"@
    }
    Write-Host "Installing uv..." -ForegroundColor Cyan
    & $winget.Source install --id astral-sh.uv --exact --source winget `
        --accept-package-agreements --accept-source-agreements | Out-Host
    if ($LASTEXITCODE) {
        throw "uv installation failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    Write-Host $Description -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "SelectSpeak requires 64-bit Windows."
}
if ($AddToStartup -and $RemoveFromStartup) {
    throw "Use either -AddToStartup or -RemoveFromStartup, not both."
}
if ($RemoveFromStartup) {
    Remove-SelectSpeakFromStartup
    return
}

$previousLocation = Get-Location
try {
    Set-Location -LiteralPath $projectRoot

    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $running = @()
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $running = @(Get-Process -Name python, pythonw `
            -ErrorAction SilentlyContinue | Where-Object {
                $_.Path -eq $venvPython -or
                $_.Path -eq (Join-Path $projectRoot `
                    ".venv\Scripts\pythonw.exe")
            })
        foreach ($process in $running) {
            Stop-Process -Id $process.Id -Force
        }
        if ($running.Count) {
            Write-Host "Stopped the running SelectSpeak instance for upgrade."
        }
    }

    $uv = Find-Uv | Select-Object -First 1
    if (-not $uv) {
        Install-Uv
        $uv = Find-Uv | Select-Object -First 1
    }
    if (-not $uv) {
        throw "uv was installed but could not be located. Open a new PowerShell window and rerun .\install.ps1."
    }

    Invoke-Checked "Installing Python $pythonVersion..." {
        & $uv python install $pythonVersion
    }
    Invoke-Checked "Creating the Python environment and installing dependencies..." {
        & $uv sync --frozen --python $pythonVersion
    }

    Write-Host "Building the native input bridge..." -ForegroundColor Cyan
    & (Join-Path $projectRoot "native\input\build.ps1") -InstallPrerequisites

    if (-not $SkipNaturalVoice) {
        Write-Host "Building the optional Natural Voice bridge..." -ForegroundColor Cyan
        & (Join-Path $projectRoot "native\natural_voice\build.ps1") `
            -InstallPrerequisites
    }

    $requiredFiles = @(
        $venvPython,
        (Join-Path $projectRoot ".venv\Scripts\pythonw.exe"),
        (Join-Path $projectRoot ".runtime\input\selectspeak_input.dll")
    )
    if (-not $SkipNaturalVoice) {
        $requiredFiles += (Join-Path $projectRoot `
            ".runtime\natural_voice\selectspeak_natural_voice.dll")
    }
    foreach ($file in $requiredFiles) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Installation did not produce required file: $file"
        }
    }

    Invoke-Checked "Verifying application imports..." {
        & $venvPython -c `
            "import PIL, pystray, win32api; import selectspeak; print('Imports OK')"
    }
    if (-not $SkipChecks) {
        Invoke-Checked "Running tests..." {
            & $venvPython -m pytest -q
        }
        Invoke-Checked "Running lint checks..." {
            & (Join-Path $projectRoot ".venv\Scripts\ruff.exe") check src tests
        }
        Invoke-Checked "Running type checks..." {
            & (Join-Path $projectRoot ".venv\Scripts\ty.exe") check
        }
    }

    if ($AddToStartup) {
        Add-SelectSpeakToStartup
    }

    if ($Launch -or $running.Count) {
        Start-Process -FilePath (Join-Path $projectRoot ".venv\Scripts\pythonw.exe") `
            -ArgumentList (Join-Path $projectRoot "main.py") `
            -WorkingDirectory $projectRoot -WindowStyle Hidden
        Write-Host "SelectSpeak started." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "SelectSpeak installation completed successfully." `
        -ForegroundColor Green
    if (-not $Launch -and -not $running.Count) {
        Write-Host "Double-click run.vbs to start it."
    }
    if (-not $SkipNaturalVoice) {
        Write-Host "Natural Voice requires a compatible Narrator voice installed in Windows."
    }
} finally {
    Set-Location -LiteralPath $previousLocation
}
