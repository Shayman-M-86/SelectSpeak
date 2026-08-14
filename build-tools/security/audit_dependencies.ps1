[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$SkipNuGet,
    [ValidateSet("low", "moderate", "high", "critical")]
    [string]$NuGetAuditLevel = "low",
    [string]$NuGetPath
)

$ErrorActionPreference = "Stop"
$buildToolsRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $buildToolsRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$reportRoot = Join-Path $projectRoot ".build\security"
$packagesConfig = Join-Path $projectRoot "src\native\natural_voice\packages.config"
$nugetUri = "https://dist.nuget.org/win-x86-commandline/v6.12.1/nuget.exe"
$nugetHash = "0790BB7A0C898E44B70F2B65E3070B4DB8AF23897E38B8653D72D268B6E8BB11"

New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null

function Invoke-PythonDependencyAudit {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$AllExtras
    )

    $uvCommand = Get-Command "uv" -ErrorAction SilentlyContinue
    if (-not $uvCommand) {
        throw "uv is required. Run .\scripts\install.ps1 first."
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "The project environment is missing. Run .\scripts\install.ps1 first."
    }

    $requirements = Join-Path $reportRoot "$Name-requirements.txt"
    $report = Join-Path $reportRoot "$Name-python-audit.md"
    if (Test-Path -LiteralPath $report) {
        Remove-Item -LiteralPath $report -Force
    }
    $exportArguments = @(
        "export",
        "--locked",
        "--no-dev",
        "--no-emit-project",
        "--format", "requirements.txt",
        "--output-file", $requirements
    )
    if ($AllExtras) {
        $exportArguments += "--all-extras"
    }

    $exportOutput = & $uvCommand.Source @exportArguments 2>&1
    $exportExitCode = $LASTEXITCODE
    if ($exportExitCode) {
        $exportOutput | ForEach-Object { Write-Host $_ }
        throw "Could not export the locked $Name dependency set."
    }

    & $python -c "import pip_audit" 2>$null
    if ($LASTEXITCODE) {
        throw "pip-audit is missing. Run 'uv sync --locked --extra supertonic'."
    }

    Write-Host "Auditing locked Python dependencies: $Name" -ForegroundColor Cyan
    $auditOutput = & $python -m pip_audit `
        --strict `
        --progress-spinner off `
        --require-hashes `
        --disable-pip `
        --format markdown `
        --output $report `
        --requirement $requirements 2>&1
    $auditExitCode = $LASTEXITCODE
    $auditOutput | ForEach-Object { Write-Host $_ }
    if ($auditExitCode) {
        throw "Known vulnerabilities or an incomplete audit were reported for $Name. See $report"
    }
    if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
        @"
# Python dependency security audit: $Name

Audited: $(Get-Date -Format "yyyy-MM-ddTHH:mm:ssK")

No known vulnerabilities found.
"@ | Set-Content -LiteralPath $report -Encoding UTF8
    }
    Write-Host "Python dependency audit passed: $report" -ForegroundColor Green
}

function Invoke-NuGetDependencyAudit {
    $nuget = if ($NuGetPath) {
        [IO.Path]::GetFullPath($NuGetPath)
    } else {
        Join-Path $projectRoot ".cache\natural_voice\tools\nuget.exe"
    }
    if (-not (Test-Path -LiteralPath $nuget -PathType Leaf)) {
        $nugetDirectory = Split-Path -Parent $nuget
        New-Item -ItemType Directory -Path $nugetDirectory -Force | Out-Null
        [Net.ServicePointManager]::SecurityProtocol = `
            [Net.ServicePointManager]::SecurityProtocol -bor `
            [Net.SecurityProtocolType]::Tls12
        Write-Host "Downloading the pinned NuGet audit client." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $nugetUri -OutFile $nuget
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nuget).Hash -ne $nugetHash) {
        throw "The NuGet client did not match its pinned SHA-256 hash."
    }

    $packagesRoot = Join-Path $reportRoot "nuget-packages"
    if (Test-Path -LiteralPath $packagesRoot) {
        Remove-Item -LiteralPath $packagesRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $packagesRoot -Force | Out-Null
    $report = Join-Path $reportRoot "nuget-audit.txt"
    $previousAudit = [Environment]::GetEnvironmentVariable("NuGetAudit", "Process")
    $previousLevel = [Environment]::GetEnvironmentVariable("NuGetAuditLevel", "Process")
    [Environment]::SetEnvironmentVariable("NuGetAudit", "true", "Process")
    [Environment]::SetEnvironmentVariable("NuGetAuditLevel", $NuGetAuditLevel, "Process")
    try {
        Write-Host "Auditing pinned NuGet dependencies at level $NuGetAuditLevel" `
            -ForegroundColor Cyan
        $auditOutput = & $nuget install $packagesConfig `
            -OutputDirectory $packagesRoot `
            -Source "https://api.nuget.org/v3/index.json" `
            -NonInteractive `
            -DisableParallelProcessing `
            -Verbosity detailed 2>&1
        $auditExitCode = $LASTEXITCODE
    } finally {
        [Environment]::SetEnvironmentVariable("NuGetAudit", $previousAudit, "Process")
        [Environment]::SetEnvironmentVariable("NuGetAuditLevel", $previousLevel, "Process")
    }
    $auditText = $auditOutput | Out-String
    $auditText | Set-Content -LiteralPath $report -Encoding UTF8
    $auditOutput | ForEach-Object { Write-Host $_ }
    if ($auditExitCode) {
        throw "NuGet restore or vulnerability audit failed. See $report"
    }
    if ($auditText -match "NU190[0-5]") {
        throw "NuGet reported a vulnerability or incomplete audit. See $report"
    }
    Write-Host "NuGet dependency audit passed: $report" -ForegroundColor Green
}

if (-not $SkipPython) {
    Invoke-PythonDependencyAudit -Name "core"
    Invoke-PythonDependencyAudit -Name "full" -AllExtras
}
if (-not $SkipNuGet) {
    Invoke-NuGetDependencyAudit
}
if ($SkipPython -and $SkipNuGet) {
    throw "Every dependency audit was skipped."
}

Write-Host "Dependency security audit completed successfully." -ForegroundColor Green
