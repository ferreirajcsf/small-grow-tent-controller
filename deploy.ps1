# ==============================================================================
# Small Grow Tent Controller - Deploy Script
# ==============================================================================
# SETUP: Edit the $HaConfigPath variable below to point to your HA config folder
# USAGE:
#   .\deploy.ps1                 - copy files to HA + git commit/tag/push
#   .\deploy.ps1 -NoGit          - copy files to HA only
#   .\deploy.ps1 -NoFileCopy     - git only (docs/changelog changes)
#   .\deploy.ps1 -NoRelease      - git push but skip GitHub release zip upload
# ==============================================================================

param(
    [switch]$NoGit,
    [switch]$NoFileCopy,
    [switch]$NoRelease
)

# ==============================================================================
# CONFIGURE THIS - change to your HA config path
# ==============================================================================
$HaConfigPath = "\\192.168.1.107\config"
# ==============================================================================

$ErrorActionPreference = "Stop"

$RepoRoot       = $PSScriptRoot
$IntegrationSrc = Join-Path $RepoRoot "custom_components\small_grow_tent_controller"
$IntegrationDst = Join-Path $HaConfigPath "custom_components\small_grow_tent_controller"

# Read version from const.py
$ConstFile = Join-Path $IntegrationSrc "const.py"
$VersionMatch = Select-String -Path $ConstFile -Pattern '^VERSION\s*=\s*"([^"]+)"'
$Version = $VersionMatch.Matches[0].Groups[1].Value
$Tag = "v$Version"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Small Grow Tent Controller - Deploy"   -ForegroundColor Cyan
Write-Host "  Version : $Version"                    -ForegroundColor Cyan
Write-Host "  Tag     : $Tag"                        -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Copy integration files to HA
# ------------------------------------------------------------------------------
if (-not $NoFileCopy) {
    Write-Host ">>> Copying integration files to HA..." -ForegroundColor Yellow

    if (-not (Test-Path $HaConfigPath)) {
        Write-Host "ERROR: HA config path not found: $HaConfigPath" -ForegroundColor Red
        Write-Host "Edit the HaConfigPath variable at the top of deploy.ps1" -ForegroundColor Red
        exit 1
    }

    if (-not (Test-Path $IntegrationDst)) {
        New-Item -ItemType Directory -Path $IntegrationDst | Out-Null
        Write-Host "    Created: $IntegrationDst"
    }

    Copy-Item -Path "$IntegrationSrc\*" -Destination $IntegrationDst -Recurse -Force
    Write-Host "    Copied to: $IntegrationDst" -ForegroundColor Green
    Write-Host "    Restart Home Assistant to pick up the changes." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host ">>> Skipping file copy (-NoFileCopy)" -ForegroundColor DarkGray
    Write-Host ""
}

# ------------------------------------------------------------------------------
# 2. Git - stage, commit, tag, push
# ------------------------------------------------------------------------------
if (-not $NoGit) {
    Write-Host ">>> Git status..." -ForegroundColor Yellow
    $Status = git status --porcelain
    if (-not $Status) {
        Write-Host "    Nothing to commit - working tree clean." -ForegroundColor DarkGray
    } else {
        Write-Host "    Modified files:"
        $Status | ForEach-Object { Write-Host "      $_" }
        Write-Host ""

        git add -A
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: git add failed" -ForegroundColor Red; exit 1 }

        Write-Host "    Enter commit message (leave blank to use 'release: $Version'):" -ForegroundColor Yellow
        $CommitMsg = Read-Host "    >"
        if ([string]::IsNullOrWhiteSpace($CommitMsg)) {
            $CommitMsg = "release: $Version"
        }

        git commit -m $CommitMsg
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: git commit failed" -ForegroundColor Red; exit 1 }
        Write-Host "    Committed: $CommitMsg" -ForegroundColor Green
    }

    # Tag
    $ExistingTag = git tag -l $Tag
    if ($ExistingTag) {
        Write-Host ""
        Write-Host "    Tag $Tag already exists." -ForegroundColor DarkGray
        $Overwrite = Read-Host "    Delete and recreate it? (y/N)"
        if ($Overwrite -eq "y" -or $Overwrite -eq "Y") {
            git tag -d $Tag | Out-Null
            $null = git push origin ":refs/tags/$Tag" 2>&1
            git tag -a $Tag -m $Tag
            Write-Host "    Tag recreated: $Tag" -ForegroundColor Green
        } else {
            Write-Host "    Keeping existing tag." -ForegroundColor DarkGray
        }
    } else {
        git tag -a $Tag -m $Tag
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: git tag failed" -ForegroundColor Red; exit 1 }
        Write-Host "    Tagged: $Tag" -ForegroundColor Green
    }

    # Push
    Write-Host ""
    Write-Host ">>> Pushing to GitHub..." -ForegroundColor Yellow
    git push origin main
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: git push (main) failed" -ForegroundColor Red; exit 1 }
    git push origin $Tag
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: git push (tag) failed" -ForegroundColor Red; exit 1 }
    Write-Host "    Pushed: main + $Tag" -ForegroundColor Green
    Write-Host ""

    # ------------------------------------------------------------------------------
    # 3. GitHub release asset upload
    # ------------------------------------------------------------------------------
    if (-not $NoRelease) {
        $GhAvailable = Get-Command gh -ErrorAction SilentlyContinue
        if (-not $GhAvailable) {
            Write-Host ">>> gh CLI not found - skipping release asset upload." -ForegroundColor DarkYellow
            Write-Host "    Install from: https://cli.github.com" -ForegroundColor DarkYellow
        } else {
            $ZipName = "small-grow-tent-controller-$Version.zip"
            $ZipPath = Join-Path $RepoRoot $ZipName

            Write-Host ">>> Building release zip: $ZipName..." -ForegroundColor Yellow
            if (Test-Path $ZipPath) { Remove-Item $ZipPath }
            Compress-Archive -Path $RepoRoot -DestinationPath $ZipPath

            $ReleaseExists = $false
            try {
                $null = gh release view $Tag 2>&1
                if ($LASTEXITCODE -eq 0) { $ReleaseExists = $true }
            } catch {
                $ReleaseExists = $false
            }

            if (-not $ReleaseExists) {
                Write-Host "    Creating GitHub release $Tag..." -ForegroundColor Yellow
                gh release create $Tag $ZipPath --title "$Tag" --notes "See CHANGELOG.md for details."
            } else {
                Write-Host "    Uploading asset to existing release $Tag..." -ForegroundColor Yellow
                gh release upload $Tag $ZipPath --clobber
            }

            if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gh release upload failed" -ForegroundColor Red; exit 1 }
            Write-Host "    Release asset uploaded: $ZipName" -ForegroundColor Green
            Remove-Item $ZipPath
        }
    } else {
        Write-Host ">>> Skipping release asset upload (-NoRelease)" -ForegroundColor DarkGray
    }
} else {
    Write-Host ">>> Skipping git (-NoGit)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Done!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
