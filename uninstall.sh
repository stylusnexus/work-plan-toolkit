#!/usr/bin/env bash
# uninstall.sh — remove work-plan toolkit copies from ~/.claude/  (macOS / Linux / WSL)
#
# Removes ONLY copies that were installed by this toolkit (verified via the
# .installed-from marker file). Leaves your config + notes alone.

set -euo pipefail

TOOLKIT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CLAUDE_DIR="${HOME}/.claude"
SKILLS_DIR="${CLAUDE_DIR}/skills"
COMMANDS_DIR="${CLAUDE_DIR}/commands"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
warn() { printf "\033[33m! %s\033[0m\n" "$1"; }
ok()   { printf "\033[32mok\033[0m %s\n" "$1"; }

bold "work-plan toolkit uninstaller"

remove_skill() {
    local name="$1"
    local dst="${SKILLS_DIR}/${name}"
    local marker="${dst}/.installed-from"

    if [ ! -e "${dst}" ]; then
        ok "${name} already absent"
        return
    fi
    if [ ! -f "${marker}" ]; then
        warn "${dst} has no .installed-from marker — leaving alone (not ours)"
        return
    fi
    if ! grep -qx "${TOOLKIT_DIR}" "${marker}"; then
        warn "${dst} was installed from a different toolkit — leaving alone"
        return
    fi
    rm -rf "${dst}"
    ok "removed ${name}"
}

remove_skill "work-plan"
remove_skill "repo-activity-summary"

cmd_src="${TOOLKIT_DIR}/commands/work-plan.md"
cmd_dst="${COMMANDS_DIR}/work-plan.md"
if [ -f "${cmd_dst}" ] && cmp -s "${cmd_src}" "${cmd_dst}"; then
    rm -f "${cmd_dst}"
    ok "removed work-plan command"
elif [ -f "${cmd_dst}" ]; then
    warn "${cmd_dst} differs from this toolkit's copy — leaving alone"
else
    ok "command already absent"
fi

echo
bold "Done."
echo "Your config (~/.claude/work-plan/config.yml) and notes were not touched."
echo "Remove them manually if you want a clean slate."
