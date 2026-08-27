[CmdletBinding()]
param(
    [switch]$DetectOnly
)

# Install the Microsoft runtimes the SelectSpeak player needs, if they are not
# already present.
#
# SelectSpeak ships a framework-dependent player rather than carrying roughly
# 170 MB of Microsoft runtime in every download and every upgrade. These are the
# two runtimes that makes necessary. Both are ordinary Microsoft redistributables
# installed from Microsoft's own servers; neither is bundled in Setup.
#
# Detection accepts any compatible servicing version. A machine with .NET 8.0.25
# does not need 8.0.x reinstalled because the build used a different patch, and
# an existing installation is never modified or downgraded.

$ErrorActionPreference = "Stop"

# The major bands the player is built against. Servicing updates inside a band
# are compatible, so any 8.0.x Desktop Runtime and any 1.8 App Runtime will do.
$DesktopRuntimeMajorMinor = "8.0"
$AppRuntimeMajor = "1.8"

# Microsoft's stable aka.ms redirectors, which always resolve to the current
# servicing release rather than a version that ages out of support.
$DesktopRuntimeUrl = "https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe"
$AppRuntimeUrl = "https://aka.ms/windowsappsdk/1.8/latest/windowsappruntimeinstall-x64.exe"


function Test-DesktopRuntime {
    <#
        .SYNOPSIS
        Report whether a compatible .NET Desktop Runtime is installed.
    #>
    $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
    if (-not $dotnet) {
        return $false
    }
    $runtimes = & $dotnet.Source --list-runtimes 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }
    return [bool](
        $runtimes | Where-Object {
            $_ -match "^Microsoft\.WindowsDesktop\.App\s+$([regex]::Escape($DesktopRuntimeMajorMinor))\."
        }
    )
}

function Test-AppRuntime {
    <#
        .SYNOPSIS
        Report whether a compatible Windows App Runtime is installed.

        The framework is registered as an MSIX package per user, so this asks
        the package manager rather than looking for files on disk.
    #>
    $packages = Get-AppxPackage -Name "Microsoft.WindowsAppRuntime.$AppRuntimeMajor" `
        -ErrorAction SilentlyContinue
    return [bool]($packages | Where-Object { $_.Architecture -eq "X64" })
}

function Install-Runtime {
    param(
        [Parameter(Mandatory)][string]$DisplayName,
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$FileName,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $installer = Join-Path ([IO.Path]::GetTempPath()) $FileName
    Write-Host "Downloading $DisplayName from $Url"
    try {
        # TLS 1.2 explicitly: Windows PowerShell 5.1 does not always negotiate
        # it by default, and Microsoft's download hosts require it.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $Url -OutFile $installer -UseBasicParsing
    } catch {
        throw "$DisplayName could not be downloaded: $($_.Exception.Message)"
    }

    try {
        Write-Host "Installing $DisplayName"
        $process = Start-Process -FilePath $installer -ArgumentList $Arguments `
            -Wait -PassThru -WindowStyle Hidden
        # 1638 is "a newer version is already installed", which is a success for
        # our purposes: the machine already has what the player needs.
        if ($process.ExitCode -notin @(0, 1638, 3010)) {
            throw "$DisplayName setup exited with code $($process.ExitCode)."
        }
        if ($process.ExitCode -eq 3010) {
            Write-Host "$DisplayName installed; Windows requests a restart."
        }
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
}


$desktopRuntimePresent = Test-DesktopRuntime
$appRuntimePresent = Test-AppRuntime

Write-Host (".NET Desktop Runtime $DesktopRuntimeMajorMinor present: {0}" -f $desktopRuntimePresent)
Write-Host ("Windows App Runtime $AppRuntimeMajor present: {0}" -f $appRuntimePresent)

if ($DetectOnly) {
    if ($desktopRuntimePresent -and $appRuntimePresent) {
        exit 0
    }
    exit 1
}

if (-not $desktopRuntimePresent) {
    Install-Runtime `
        -DisplayName ".NET Desktop Runtime $DesktopRuntimeMajorMinor" `
        -Url $DesktopRuntimeUrl `
        -FileName "selectspeak-windowsdesktop-runtime.exe" `
        -Arguments @("/install", "/quiet", "/norestart")
}

if (-not $appRuntimePresent) {
    Install-Runtime `
        -DisplayName "Windows App Runtime $AppRuntimeMajor" `
        -Url $AppRuntimeUrl `
        -FileName "selectspeak-windowsappruntime.exe" `
        -Arguments @("--quiet")
}

# Re-check rather than trusting the exit codes: a silent install that reported
# success but left nothing usable would otherwise surface as a player that
# never appears, which is the failure this whole script exists to prevent.
if (-not (Test-DesktopRuntime)) {
    throw "The .NET Desktop Runtime $DesktopRuntimeMajorMinor is still not available after installation."
}
if (-not (Test-AppRuntime)) {
    throw "The Windows App Runtime $AppRuntimeMajor is still not available after installation."
}

Write-Host "SelectSpeak player runtimes are installed." -ForegroundColor Green
