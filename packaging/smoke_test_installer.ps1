[CmdletBinding()]
param(
    [string]$InstallerPath,
    [switch]$KeepInstalled
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$buildRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
$testRoot = [IO.Path]::GetFullPath((Join-Path $buildRoot "installer-smoke"))
$installRoot = Join-Path $testRoot "app"
$dataRoot = Join-Path $testRoot "user-data"
$installLog = Join-Path $testRoot "install.log"
$upgradeLog = Join-Path $testRoot "upgrade.log"
$uninstallLog = Join-Path $testRoot "uninstall.log"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A441CF57-CAEC-4C75-9E64-90EB3F806014}_is1"

if (-not $InstallerPath) {
    $installer = Get-ChildItem -LiteralPath (Join-Path $projectRoot "dist") `
        -Filter "SelectSpeak-Setup-*.exe" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $installer) { throw "No SelectSpeak installer was found in dist." }
    $InstallerPath = $installer.FullName
}
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Installer not found: $InstallerPath"
}
if (Get-Process "SelectSpeak" -ErrorAction SilentlyContinue) {
    throw "Quit every running SelectSpeak instance before the installer smoke test."
}
if (Test-Path -LiteralPath $uninstallKey) {
    $existing = Get-ItemProperty -LiteralPath $uninstallKey
    if ($existing.InstallLocation -and
        -not $existing.InstallLocation.StartsWith($testRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "A real SelectSpeak installation already exists at $($existing.InstallLocation)."
    }
    $existingUninstaller = $existing.UninstallString.Trim('"')
    if (-not (Test-Path -LiteralPath $existingUninstaller -PathType Leaf)) {
        throw "The previous smoke-test uninstaller is missing: $existingUninstaller"
    }
    $cleanup = Start-Process -FilePath $existingUninstaller `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
        -Wait -PassThru
    if ($cleanup.ExitCode) {
        throw "Could not remove the previous smoke-test installation."
    }
}
if (Test-Path -LiteralPath $uninstallKey) {
    throw "The previous smoke-test installation is still registered."
}
if (-not $testRoot.StartsWith("$buildRoot\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean an installer test path outside the build directory: $testRoot"
}
if (Test-Path -LiteralPath $testRoot) {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
$installArguments = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/DIR=`"$installRoot`"",
    "/MERGETASKS=!desktopicon,!startup",
    "/LOG=`"$installLog`""
)
$install = Start-Process -FilePath $InstallerPath -ArgumentList $installArguments -Wait -PassThru
if ($install.ExitCode) { throw "Silent installation failed with exit code $($install.ExitCode)." }

& $python (Join-Path $PSScriptRoot "verify_dist.py") $installRoot `
    --require-speech-runtime
if ($LASTEXITCODE) { throw "The installed application layout is invalid." }
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "SelectSpeak\SelectSpeak.lnk"
if (-not (Test-Path -LiteralPath $startMenuShortcut -PathType Leaf)) {
    throw "The Start Menu shortcut was not created."
}

$previousDataRoot = $env:SELECTSPEAK_USER_DATA_DIR
$env:SELECTSPEAK_USER_DATA_DIR = $dataRoot
try {
    $application = Start-Process -FilePath (Join-Path $installRoot "SelectSpeak.exe") `
        -WorkingDirectory $installRoot -WindowStyle Hidden -PassThru
} finally {
    $env:SELECTSPEAK_USER_DATA_DIR = $previousDataRoot
}
$deadline = [DateTime]::UtcNow.AddSeconds(30)
$settings = Join-Path $dataRoot "settings.json"
$log = Join-Path $dataRoot "logs\selectspeak.log"
$started = $false
while ([DateTime]::UtcNow -lt $deadline) {
    if (Test-Path -LiteralPath $log -PathType Leaf) {
        $started = Select-String -LiteralPath $log -Pattern "app.started" -Quiet
        if ($started) { break }
    }
    if ($application.HasExited) { break }
    Start-Sleep -Milliseconds 250
}
if (-not (Test-Path -LiteralPath $settings -PathType Leaf)) {
    Stop-Process -Id $application.Id -ErrorAction SilentlyContinue
    throw "The installed application did not create its settings file."
}
if (-not $started) {
    Stop-Process -Id $application.Id -ErrorAction SilentlyContinue
    throw "The installed application did not complete startup."
}
Stop-Process -Id $application.Id -ErrorAction SilentlyContinue
Wait-Process -Id $application.Id -Timeout 15 -ErrorAction SilentlyContinue
if (Get-Process -Id $application.Id -ErrorAction SilentlyContinue) {
    throw "The installed application did not stop before the upgrade test."
}

$upgradeArguments = @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/DIR=`"$installRoot`"",
    "/LOG=`"$upgradeLog`""
)
$upgrade = Start-Process -FilePath $InstallerPath -ArgumentList $upgradeArguments -Wait -PassThru
if ($upgrade.ExitCode) { throw "Silent upgrade failed with exit code $($upgrade.ExitCode)." }
& $python (Join-Path $PSScriptRoot "verify_dist.py") $installRoot `
    --require-speech-runtime
if ($LASTEXITCODE) { throw "The upgraded application layout is invalid." }

if ($KeepInstalled) {
    Write-Host "Installer smoke test passed; test installation retained at $installRoot" -ForegroundColor Green
    exit 0
}

$uninstaller = Join-Path $installRoot "unins000.exe"
if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
    throw "The installer did not create an uninstaller."
}
$uninstall = Start-Process -FilePath $uninstaller `
    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$uninstallLog`"") `
    -Wait -PassThru
if ($uninstall.ExitCode) { throw "Silent uninstall failed with exit code $($uninstall.ExitCode)." }
if (Test-Path -LiteralPath (Join-Path $installRoot "SelectSpeak.exe")) {
    throw "Uninstall left the application executable behind."
}
if (-not (Test-Path -LiteralPath $settings -PathType Leaf)) {
    throw "Uninstall removed the user's settings."
}
if (Test-Path -LiteralPath $startMenuShortcut) {
    throw "Uninstall left the Start Menu shortcut behind."
}
if (Test-Path -LiteralPath $uninstallKey) {
    throw "Uninstall left SelectSpeak registered in Windows Apps."
}

Write-Host "Installer install, startup, upgrade, and uninstall smoke tests passed." -ForegroundColor Green
Write-Host "Preserved test user data: $dataRoot" -ForegroundColor Green
