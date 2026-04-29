# uninstall.ps1 — remove work-plan toolkit copies from $env:USERPROFILE/.claude/  (Windows)
#
# Removes ONLY copies installed by this toolkit (verified via .installed-from marker).
# Leaves your config + notes alone.

$ErrorActionPreference = "Stop"

$ToolkitDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ClaudeDir   = Join-Path $env:USERPROFILE ".claude"
$SkillsDir   = Join-Path $ClaudeDir "skills"
$CommandsDir = Join-Path $ClaudeDir "commands"

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
