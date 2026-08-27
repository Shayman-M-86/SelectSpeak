[CmdletBinding()]
param(
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$buildToolsRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $buildToolsRoot
$project = Join-Path $projectRoot "src\winui\SelectSpeak.UI\SelectSpeak.UI.csproj"
$outputRoot = Join-Path $projectRoot ".build\winui\bin\$Configuration\net8.0-windows10.0.19041.0\win-x64"

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw "The .NET SDK is required to build the SelectSpeak player. Install it with: winget install --id Microsoft.DotNet.SDK.10 --exact"
}

# IMPORTANT: build, never publish.
#
# `dotnet publish` drops this project's compiled XAML - SelectSpeak.UI.pri and
# every .xbf - even though the XAML compiler runs and emits them into obj\.
# The resulting executable then faults inside Microsoft.UI.Xaml.dll on launch
# with no managed exception to catch. `dotnet build` copies them correctly.
#
# The player is framework-dependent by design: Setup installs the .NET Desktop
# Runtime and the Windows App Runtime rather than SelectSpeak carrying ~170 MB
# of Microsoft runtime in every download.
& dotnet build $project --configuration $Configuration --nologo -warnaserror
if ($LASTEXITCODE) { throw "The SelectSpeak player build failed." }

# The launch failure above is silent, so the resources are checked here rather
# than discovered by a user whose player never appears.
$requiredResources = @(
    "SelectSpeak.UI.exe",
    "SelectSpeak.UI.dll",
    "SelectSpeak.UI.pri",
    "App.xbf",
    "Views\PlayerWindow.xbf",
    "Views\SettingsWindow.xbf"
)
$missing = @($requiredResources | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $outputRoot $_) -PathType Leaf)
})
if ($missing.Count) {
    throw "The player built without its compiled XAML: $($missing -join ', ')"
}

Write-Host "SelectSpeak player built at $outputRoot" -ForegroundColor Green
