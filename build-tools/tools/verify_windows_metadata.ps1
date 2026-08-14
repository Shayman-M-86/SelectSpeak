[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string[]]$Files,
    [Parameter(Mandatory)]
    [string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"

foreach ($file in $Files) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Metadata target does not exist: $file"
    }
    $info = (Get-Item -LiteralPath $file).VersionInfo
    $productName = ([string]$info.ProductName).Trim()
    $productVersion = ([string]$info.ProductVersion).Trim()
    $companyName = ([string]$info.CompanyName).Trim()
    if ($productName -ne "SelectSpeak") {
        throw "Unexpected ProductName '$($info.ProductName)' in $file"
    }
    if ($productVersion -ne $ExpectedVersion) {
        throw "Unexpected ProductVersion '$($info.ProductVersion)' in $file; expected $ExpectedVersion"
    }
    if ($companyName -ne "SelectSpeak Project") {
        throw "Unexpected CompanyName '$($info.CompanyName)' in $file"
    }
    Write-Host "Verified Windows metadata: $file" -ForegroundColor Green
}
