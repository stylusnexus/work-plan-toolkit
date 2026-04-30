# install.ps1 — install the work-plan toolkit  (Windows native PowerShell)
#
# Auto-detects target dir: $env:USERPROFILE\.claude\ (Claude Code) or
# $env:USERPROFILE\.agents\ (Codex). Override with -Target <dir>.
# Copies files. Re-run after `git pull` to refresh.

param(
    [string]$Target = "",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    @"
Usage: .\install.ps1 [-Target <dir>]

Auto-detects target if -Target not given:
  1. $env:USERPROFILE\.claude\  (Claude Code)
  2. $env:USERPROFILE\.agents\  (Codex)

To install for both, run twice:
  .\install.ps1 -Target "$env:USERPROFILE\.claude"
  .\install.ps1 -Target "$env:USERPROFILE\.agents"
"@
    exit 0
}

$ToolkitDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Resolve target
if ($Target) {
    $BaseDir = $Target
} elseif (Test-Path (Join-Path $env:USERPROFILE ".claude")) {
    $BaseDir = Join-Path $env:USERPROFILE ".claude"
} elseif (Test-Path (Join-Path $env:USERPROFILE ".agents")) {
    $BaseDir = Join-Path $env:USERPROFILE ".agents"
} else {
    Write-Host "ERROR no target dir found. Looked for ~\.claude (Claude Code) and ~\.agents (Codex)." -ForegroundColor Red
    Write-Host "Pass -Target <dir> to install elsewhere, or install Claude Code / Codex first." -ForegroundColor Red
    exit 1
}

$SkillsDir   = Join-Path $BaseDir "skills"
$CommandsDir = Join-Path $BaseDir "commands"
$ConfigDir   = Join-Path $BaseDir "work-plan"
$ConfigFile  = Join-Path $ConfigDir "config.yml"

function Bold($msg) { Write-Host $msg -ForegroundColor White }
function Ok($msg)   { Write-Host "ok $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "! $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "ERROR $msg" -ForegroundColor Red }

Bold "work-plan toolkit installer (Windows)"
Write-Host "Toolkit:  $ToolkitDir"
Write-Host "Target:   $BaseDir"
Write-Host ""

# 1. Verify target dir exists
if (-not (Test-Path $BaseDir)) {
    Err "$BaseDir not found. Pass -Target <dir> or install Claude Code / Codex first."
    exit 1
}
New-Item -ItemType Directory -Force -Path $SkillsDir, $CommandsDir, $ConfigDir | Out-Null

# 2. Verify external dependencies
$missing = @()
foreach ($cmd in @("gh", "git", "yq", "python")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        $missing += $cmd
    }
}
if ($missing.Count -gt 0) {
    Err "Missing required tools: $($missing -join ', ')"
    Write-Host ""
    Write-Host "  gh:     https://cli.github.com/  (winget install GitHub.cli)"
    Write-Host "  git:    https://git-scm.com/     (winget install Git.Git)"
    Write-Host "  yq:     https://github.com/mikefarah/yq  (winget install MikeFarah.yq)"
    Write-Host "  python: https://www.python.org/  (winget install Python.Python.3)"
    exit 1
}
Ok "all dependencies present"

# 3. Copy skills (with marker file for safe uninstall)
function Copy-Skill {
    param([string]$Name)
    $src = Join-Path $ToolkitDir "skills\$Name"
    $dst = Join-Path $SkillsDir $Name
    $marker = Join-Path $dst ".installed-from"

    if (Test-Path $dst) {
        if ((Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $ToolkitDir)) {
            Remove-Item $dst -Recurse -Force
        } else {
            Warn "$dst exists and was not installed by this toolkit."
            $ans = Read-Host "    Overwrite? [y/N]"
            if ($ans -ne "y" -and $ans -ne "Y") {
                Warn "skipped $Name"
                return
            }
            Remove-Item $dst -Recurse -Force
        }
    }
    Copy-Item $src $dst -Recurse
    Set-Content -Path $marker -Value $ToolkitDir -NoNewline
    Ok "copied $Name"
}

Copy-Skill "work-plan"
Copy-Skill "repo-activity-summary"

# 3.5 Copy VERSION file alongside work_plan.py so --version can read it.
# VERSION lives at the repo root (auto-bumped on each main push by
# .github/workflows/version-bump.yml); the runtime expects it next to the script.
$versionSrc = Join-Path $ToolkitDir "VERSION"
$versionDst = Join-Path $SkillsDir "work-plan\VERSION"
if (Test-Path $versionSrc) {
    Copy-Item $versionSrc $versionDst -Force
    $v = (Get-Content $versionSrc -Raw).Trim()
    Ok "copied VERSION ($v)"
} else {
    Warn "no VERSION file at toolkit root — --version will report 'unknown'"
}

# 4. Copy slash command
$cmdSrc = Join-Path $ToolkitDir "commands\work-plan.md"
$cmdDst = Join-Path $CommandsDir "work-plan.md"
if (Test-Path $cmdDst) {
    $srcHash = (Get-FileHash $cmdSrc).Hash
    $dstHash = (Get-FileHash $cmdDst).Hash
    if ($srcHash -eq $dstHash) {
        Ok "command already up to date"
    } else {
        Warn "$cmdDst differs from toolkit."
        $ans = Read-Host "    Overwrite? [y/N]"
        if ($ans -eq "y" -or $ans -eq "Y") {
            Copy-Item $cmdSrc $cmdDst -Force
            Ok "copied command"
        } else {
            Warn "skipped command"
        }
    }
} else {
    Copy-Item $cmdSrc $cmdDst
    Ok "copied command"
}

# 5. Seed config — only if it doesn't already exist
if (Test-Path $ConfigFile) {
    Ok "config already exists, leaving alone ($ConfigFile)"
} else {
    $absNotes = Join-Path $ToolkitDir "notes"
    @"
# work-plan config — created by install.ps1. Edit this file to customize.
# Run /work-plan init-repo <key> --github=<org/repo> to populate repos:.
notes_root: $absNotes
repos: {}
"@ | Set-Content -Path $ConfigFile -Encoding UTF8
    Ok "seeded $ConfigFile (notes_root: $absNotes)"
}

# 6. Smoke test
Write-Host ""
Bold "Smoke test"
$workPlanPy = Join-Path $SkillsDir "work-plan\work_plan.py"
$smokeOk = $false
try {
    python $workPlanPy --help | Out-Null
    $smokeOk = $true
} catch {}
if ($smokeOk) { Ok "work_plan.py --help runs" } else { Warn "work_plan.py --help failed — investigate manually" }

Write-Host ""
Bold "Done."
Write-Host "Try:  python $workPlanPy --help"
Write-Host "Or in Claude Code: /work-plan --help"
Write-Host ""
Write-Host "Bootstrap your first repo:  /work-plan init-repo <key>"
Write-Host "Re-run after 'git pull' to refresh."
