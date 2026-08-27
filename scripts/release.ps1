# Run from the repository root:
# .\scripts\release.ps1

<#
.SYNOPSIS
    Guide a SelectSpeak release from version preparation through publication review.

.DESCRIPTION
    Runs the repeatable release checklist steps in order. It prepares the
    version and changelog on feature, commits and pushes those changes, pauses
    for the feature-to-main merge and CI, then updates main and creates exactly
    one annotated release tag. Finally, it starts the Distribution workflow
    when GitHub CLI is available, or opens its GitHub page, and guides the
    remaining manual review and clean-system test.

    The script requires a clean worktree before it starts so it cannot absorb
    unrelated work into the release commit.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$featureBranch = "feature"
$mainBranch = "main"
$remote = "origin"
$gitExe = $null
$releaseFiles = @(
    "CHANGELOG.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "src/python/selectspeak/__init__.py",
    "src/native/CMakeLists.txt",
    "src/winui/SelectSpeak.UI/SelectSpeak.UI.csproj",
    "build-tools/app/SelectSpeak.manifest",
    "build-tools/app/version_info.txt",
    "build-tools/installer/SelectSpeak.iss"
)

function Write-Step {
    param(
        [Parameter(Mandatory = $true)][int]$Number,
        [Parameter(Mandatory = $true)][string]$Message
    )

    Write-Host ""
    Write-Host "Step ${Number}: $Message" -ForegroundColor Cyan
}

function Confirm-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [bool]$DefaultYes = $false
    )

    $suffix = if ($DefaultYes) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $answer = (Read-Host "$Prompt $suffix").Trim().ToLowerInvariant()
        if (-not $answer) {
            return $DefaultYes
        }
        if ($answer -in @("y", "yes")) {
            return $true
        }
        if ($answer -in @("n", "no")) {
            return $false
        }
        if ($answer -in @("q", "quit")) {
            throw "Release cancelled."
        }
        Write-Host "Enter y, n, or q." -ForegroundColor Yellow
    }
}

function Find-Git {
    $command = Get-Command git -CommandType Application -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "Git\cmd\git.exe"),
        (Join-Path $env:ProgramFiles "Git\bin\git.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Git\cmd\git.exe")
    )
    return $candidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string[]]$Arguments,
        [switch]$Capture
    )

    if ($Capture) {
        $output = @(& $script:gitExe @Arguments)
        if ($LASTEXITCODE) {
            throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
        }
        return $output
    }

    & $script:gitExe @Arguments
    if ($LASTEXITCODE) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Test-GitReference {
    param([Parameter(Mandatory = $true)][string]$Reference)

    & $script:gitExe show-ref --verify --quiet $Reference
    return $LASTEXITCODE -eq 0
}

function Get-ProjectVersion {
    $metadata = [IO.File]::ReadAllText((Join-Path $projectRoot "pyproject.toml"))
    $match = [regex]::Match(
        $metadata,
        '(?m)^version\s*=\s*"(?<version>\d+\.\d+\.\d+)"\s*$'
    )
    if (-not $match.Success) {
        throw "Could not read the current version from pyproject.toml."
    }
    return $match.Groups["version"].Value
}

function Read-ReleaseVersion {
    param([Parameter(Mandatory = $true)][string]$CurrentVersion)

    Write-Host "Current SelectSpeak version: $CurrentVersion"
    if (Confirm-Step "Release version $CurrentVersion?" -DefaultYes $true) {
        return $CurrentVersion
    }

    while ($true) {
        $version = (Read-Host "Enter the release version (major.minor.patch)").Trim()
        if ($version -match '^\d+\.\d+\.\d+$') {
            return $version
        }
        Write-Host "Use major.minor.patch, for example 0.1.4." -ForegroundColor Yellow
    }
}

function Get-ChangelogSection {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Version
    )

    $escapedVersion = [regex]::Escape($Version)
    $pattern =
        "(?ms)^##[ \t]+$escapedVersion(?:[ \t]+-[ \t]+[^\r\n]+)?[ \t]*\r?\n" +
        "(?<content>.*?)(?=^##[ \t]+|\z)"
    return [regex]::Match($Text, $pattern)
}

function Complete-ChangelogVersion {
    param([Parameter(Mandatory = $true)][string]$Version)

    $path = Join-Path $projectRoot "CHANGELOG.md"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "CHANGELOG.md was not found."
    }

    $text = [IO.File]::ReadAllText($path)
    $versionSection = Get-ChangelogSection -Text $text -Version $Version
    $unreleased = [regex]::Match(
        $text,
        '(?ms)^##[ \t]+Unreleased[ \t]*\r?\n(?<content>.*?)(?=^##[ \t]+|\z)'
    )
    if (-not $unreleased.Success) {
        throw "CHANGELOG.md must contain a '## Unreleased' section."
    }

    $unreleasedContent = $unreleased.Groups["content"].Value.Trim()
    if ($versionSection.Success) {
        if (-not $versionSection.Groups["content"].Value.Trim()) {
            throw "The CHANGELOG.md section for $Version is empty."
        }
        if ($unreleasedContent) {
            throw "CHANGELOG.md already has a $Version section, but Unreleased is not empty. Move or merge those entries manually before continuing."
        }
        Write-Host "CHANGELOG.md already has a non-empty $Version section."
        return
    }

    if (-not $unreleasedContent) {
        throw "CHANGELOG.md has no user-facing changes under Unreleased for $Version."
    }

    $newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $replacement =
        "## Unreleased$newline$newline" +
        "## $Version - $(Get-Date -Format 'yyyy-MM-dd')$newline$newline" +
        "$unreleasedContent$newline$newline"
    $updated =
        $text.Substring(0, $unreleased.Index) +
        $replacement +
        $text.Substring($unreleased.Index + $unreleased.Length)
    [IO.File]::WriteAllText($path, $updated, (New-Object Text.UTF8Encoding($false)))
    Write-Host "Moved Unreleased changes into the $Version section." -ForegroundColor Green
}

function Assert-CleanWorktree {
    $changes = @(Invoke-Git @("status", "--porcelain") -Capture)
    if ($changes.Count) {
        throw "The worktree is not clean. Commit or stash existing changes before starting a release."
    }
}

function Assert-MainReleaseMetadata {
    param([Parameter(Mandatory = $true)][string]$Version)

    $mainVersion = Get-ProjectVersion
    if ($mainVersion -ne $Version) {
        throw "main contains version $mainVersion, not release version $Version."
    }

    $changelog = [IO.File]::ReadAllText((Join-Path $projectRoot "CHANGELOG.md"))
    $section = Get-ChangelogSection -Text $changelog -Version $Version
    if (-not $section.Success -or -not $section.Groups["content"].Value.Trim()) {
        throw "main has no non-empty CHANGELOG.md section for $Version."
    }
}

function Get-RepositoryUrl {
    $remoteUrl = (Invoke-Git @("remote", "get-url", $remote) -Capture | Select-Object -First 1)
    $match = [regex]::Match($remoteUrl, 'github\.com[/:](?<repository>.+?)(?:\.git)?$')
    if (-not $match.Success) {
        return $null
    }
    return "https://github.com/$($match.Groups['repository'].Value)"
}

function Open-ReleasePage {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        Start-Process $Url
    } catch {
        Write-Host "Could not open the browser automatically: $Url" -ForegroundColor Yellow
    }
}

$previousLocation = Get-Location
try {
    Set-Location -LiteralPath $projectRoot
    $script:gitExe = Find-Git
    if (-not $script:gitExe) {
        throw "Git is required to run the release process."
    }
    & $script:gitExe rev-parse --show-toplevel *> $null
    if ($LASTEXITCODE) {
        throw "Run this script from the SelectSpeak Git repository."
    }

    Write-Step 1 "Prepare the release on $featureBranch"
    Assert-CleanWorktree
    $currentBranch = (Invoke-Git @("branch", "--show-current") -Capture | Select-Object -First 1)
    if ($currentBranch -ne $featureBranch) {
        if (-not (Confirm-Step "Switch from $currentBranch to $featureBranch now?")) {
            throw "Release preparation must be committed to $featureBranch."
        }
        Invoke-Git @("switch", $featureBranch)
    }
    Invoke-Git @("pull", "--ff-only", $remote, $featureBranch)

    $currentVersion = Get-ProjectVersion
    $version = Read-ReleaseVersion -CurrentVersion $currentVersion
    if ($version -ne $currentVersion) {
        & (Join-Path $PSScriptRoot "bump_version.ps1") -Version $version
        if ($LASTEXITCODE) {
            throw "Version bump failed."
        }
    } else {
        Write-Host "Keeping project version $version."
    }
    Complete-ChangelogVersion -Version $version

    Invoke-Git @("diff", "--check")
    $changedFiles = @(Invoke-Git @("diff", "--name-only") -Capture)
    $unexpectedFiles = @($changedFiles | Where-Object { $_ -notin $releaseFiles })
    if ($unexpectedFiles.Count) {
        throw "Release preparation changed unexpected files: $($unexpectedFiles -join ', ')"
    }

    if ($changedFiles.Count) {
        Invoke-Git (@("diff", "--") + $changedFiles)
        if (-not (Confirm-Step "Commit these release changes to $featureBranch?")) {
            throw "Release paused before committing."
        }
        Invoke-Git (@("add", "--") + $changedFiles)
        Invoke-Git @("commit", "-m", "chore: prepare SelectSpeak $version release")
    } else {
        Write-Host "Version and changelog are already prepared; no release commit is needed."
    }

    Write-Step 2 "Push $featureBranch and merge it to $mainBranch"
    if (-not (Confirm-Step "Push $featureBranch to $remote?" -DefaultYes $true)) {
        throw "Release paused before pushing $featureBranch."
    }
    Invoke-Git @("push", $remote, $featureBranch)

    $repositoryUrl = Get-RepositoryUrl
    if ($repositoryUrl) {
        $compareUrl = "$repositoryUrl/compare/$mainBranch...${featureBranch}?expand=1"
        Write-Host "Merge page: $compareUrl"
        if (Confirm-Step "Open the merge page?" -DefaultYes $true) {
            Open-ReleasePage -Url $compareUrl
        }
    }
    Write-Host "Merge $featureBranch into $mainBranch and wait for CI on the merged commit."
    if (-not (Confirm-Step "Has the release preparation been merged and has CI passed?")) {
        throw "Release paused before tagging. Rerun this script after the merge and CI complete."
    }

    Write-Step 3 "Update $mainBranch and create the release tag"
    Invoke-Git @("switch", $mainBranch)
    Invoke-Git @("pull", "--ff-only", $remote, $mainBranch)
    Assert-CleanWorktree
    Assert-MainReleaseMetadata -Version $version

    $tag = "v$version"
    if (Test-GitReference -Reference "refs/tags/$tag") {
        throw "Local tag $tag already exists; refusing to create another release tag."
    }
    & $script:gitExe ls-remote --exit-code --tags $remote "refs/tags/$tag" *> $null
    $remoteTagResult = $LASTEXITCODE
    if ($remoteTagResult -eq 0) {
        throw "Remote tag $tag already exists; refusing to replace it."
    }
    if ($remoteTagResult -ne 2) {
        throw "Could not check whether remote tag $tag already exists."
    }
    if (-not (Confirm-Step "Create and push the single annotated tag $tag from $mainBranch?")) {
        throw "Release paused before tagging."
    }
    Invoke-Git @("tag", "-a", $tag, "-m", "SelectSpeak $version")
    Invoke-Git @("push", $remote, "refs/tags/$tag")

    Write-Step 4 "Start the Distribution workflow"
    $workflowStarted = $false
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh -and (Confirm-Step "Start Distribution from $tag with GitHub CLI?" -DefaultYes $true)) {
        $ghPath = $gh.Source
        & $ghPath workflow run distribution.yml --ref $tag
        if ($LASTEXITCODE) {
            throw "Could not start the Distribution workflow with GitHub CLI."
        }
        $workflowStarted = $true
        Write-Host "Distribution started for $tag." -ForegroundColor Green
    }

    if ($repositoryUrl) {
        $actionsUrl = "$repositoryUrl/actions/workflows/distribution.yml"
        Write-Host "Distribution workflow: $actionsUrl"
        if (-not $workflowStarted) {
            Write-Host "Start Run workflow from tag $tag on this page."
        }
        if (Confirm-Step "Open the Distribution workflow page?" -DefaultYes $true) {
            Open-ReleasePage -Url $actionsUrl
        }
    } elseif (-not $workflowStarted) {
        Write-Host "Open GitHub Actions and start Distribution from tag $tag." -ForegroundColor Yellow
    }

    if (-not (Confirm-Step "Have both Distribution jobs passed and created the draft release?")) {
        throw "Release paused while Distribution is incomplete or failing."
    }

    Write-Step 5 "Review and publish the draft release"
    if ($repositoryUrl) {
        $releasesUrl = "$repositoryUrl/releases"
        Write-Host "Draft releases: $releasesUrl"
        if (Confirm-Step "Open the Releases page?" -DefaultYes $true) {
            Open-ReleasePage -Url $releasesUrl
        }
    }
    Write-Host "Review the generated changelog notes and unsigned-release boilerplate."
    Write-Host "Download the draft installer and test it on a clean supported Windows system."
    if (-not (Confirm-Step "Have the release notes and clean-system user flows been verified?")) {
        throw "Release paused before publication."
    }
    Write-Host "Publish the reviewed draft release on GitHub." -ForegroundColor Yellow
    if (-not (Confirm-Step "Has the draft release been published?")) {
        throw "Release remains a draft."
    }

    Write-Host ""
    Write-Host "SelectSpeak $version release process complete." -ForegroundColor Green
} finally {
    Set-Location -LiteralPath $previousLocation
}
