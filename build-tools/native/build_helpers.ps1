function Find-SelectSpeakCMake {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} `
        "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        return $null
    }

    $installation = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath | Select-Object -First 1
    if (-not $installation) {
        return $null
    }

    $pathCommand = Get-Command cmake -ErrorAction SilentlyContinue
    if ($pathCommand -and $pathCommand.CommandType -eq "Application" -and
        (Test-Path -LiteralPath $pathCommand.Source -PathType Leaf)) {
        return [string]$pathCommand.Source
    }

    $bundled = Join-Path $installation `
        "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
    if (Test-Path -LiteralPath $bundled -PathType Leaf) {
        return $bundled
    }
    return $null
}

function Install-SelectSpeakNativeToolchain {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "WinGet is required to install the Visual C++ build toolchain."
    }
    Write-Host "Installing Visual Studio 2022 C++ Build Tools and CMake..."
    & $winget.Source install --id Microsoft.VisualStudio.2022.BuildTools `
        --exact --source winget --accept-package-agreements `
        --accept-source-agreements --override `
        "--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.CMake.Project --includeRecommended" `
        | Out-Host
    if ($LASTEXITCODE) {
        throw "Build Tools installation failed with exit code $LASTEXITCODE"
    }
}

function Get-SelectSpeakCMake {
    param([switch]$InstallPrerequisites)

    $cmake = Find-SelectSpeakCMake | Select-Object -First 1
    if (-not $cmake -and $InstallPrerequisites) {
        Install-SelectSpeakNativeToolchain
        $cmake = Find-SelectSpeakCMake | Select-Object -First 1
    }
    if (-not $cmake -or -not (Test-Path -LiteralPath $cmake -PathType Leaf)) {
        throw @"
The Visual C++ toolchain and CMake were not found.

Run the developer installer:
    .\scripts\install.ps1
"@
    }
    return $cmake
}
