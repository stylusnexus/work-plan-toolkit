# install.ps1 — install the work-plan toolkit into $env:USERPROFILE/.claude/  (Windows)
#
# Copies skills + command into ~/.claude/. Re-run after `git pull` to refresh.

$ErrorActionPreference = "Stop"

$ToolkitDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir   = Join-Path $env:USERPROFILE ".claude"
$SkillsDir   = Join-Path $ClaudeDir "skills"
$CommandsDir = Join-Path $ClaudeDir "commands"
$ConfigDir   = Join-Path $ClaudeDir "work-plan"
$ConfigFile  = Join-Path $ConfigDir "config.yml"

function Bold($msg) { Write-Host $msg -ForegroundColor White }
function Ok($msg)   { Write-Host "ok $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "! $msg" -ForegroundColor Yellow }
function Err($msg)  { Write-Host "ERROR $msg" -ForegroundColor Red }

Bold "work-plan toolkit installer (Windows)"
Write-Host "Toolkit:  $ToolkitDir"
Write-Host "Target:   $ClaudeDir"
Write-Host ""

# 1. Verify Claude Code dirs exist
if (-not (Test-Path $ClaudeDir)) {
    Err "$ClaudeDir not found. Is Claude Code installed?"
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
