# uninstall.ps1 — remove work-plan toolkit copies  (Windows native PowerShell)
#
# Auto-detects target dir: ~\.claude\ (Claude Code) or ~\.agents\ (Codex).
# Override with -Target <dir>. Removes ONLY copies installed by this toolkit
# (verified via .installed-from marker). Leaves config + notes alone.

param(
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"

$ToolkitDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Target) {
    $BaseDir = $Target
} elseif (Test-Path (Join-Path $env:USERPROFILE ".claude")) {
    $BaseDir = Join-Path $env:USERPROFILE ".claude"
} elseif (Test-Path (Join-Path $env:USERPROFILE ".agents")) {
    $BaseDir = Join-Path $env:USERPROFILE ".agents"
} else {
    Write-Host "ERROR no target dir found." -ForegroundColor Red
    exit 1
}

$SkillsDir   = Join-Path $BaseDir "skills"
$CommandsDir = Join-Path $BaseDir "commands"

function Bold($msg) { Write-Host $msg -ForegroundColor White }
function Ok($msg)   { Write-Host "ok $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "! $msg" -ForegroundColor Yellow }

Bold "work-plan toolkit uninstaller (Windows)"

function Remove-Skill {
    param([string]$Name)
    $dst = Join-Path $SkillsDir $Name
    $marker = Join-Path $dst ".installed-from"

    if (-not (Test-Path $dst)) {
        Ok "$Name already absent"
        return
    }
    if (-not (Test-Path $marker)) {
        Warn "$dst has no .installed-from marker — leaving alone (not ours)"
        return
    }
    if ((Get-Content $marker -Raw).Trim() -ne $ToolkitDir) {
        Warn "$dst was installed from a different toolkit — leaving alone"
        return
    }
    Remove-Item $dst -Recurse -Force
    Ok "removed $Name"
}

Remove-Skill "work-plan"
Remove-Skill "repo-activity-summary"

$cmdSrc = Join-Path $ToolkitDir "commands\work-plan.md"
$cmdDst = Join-Path $CommandsDir "work-plan.md"
if (Test-Path $cmdDst) {
    $srcHash = (Get-FileHash $cmdSrc).Hash
    $dstHash = (Get-FileHash $cmdDst).Hash
    if ($srcHash -eq $dstHash) {
        Remove-Item $cmdDst -Force
        Ok "removed work-plan command"
    } else {
        Warn "$cmdDst differs from this toolkit's copy — leaving alone"
    }
} else {
    Ok "command already absent"
}

Write-Host ""
Bold "Done."
Write-Host "Your config (~/.claude/work-plan/config.yml) and notes were not touched."
Write-Host "Remove them manually if you want a clean slate."
