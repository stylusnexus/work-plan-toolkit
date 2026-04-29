#!/usr/bin/env bash
# uninstall.sh — remove work-plan toolkit symlinks from ~/.claude/
#
# Removes ONLY the symlinks created by install.sh (verified by readlink target).
# Leaves your config (~/.claude/work-plan/config.yml) and your notes alone.

set -euo pipefail

TOOLKIT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CLAUDE_DIR="${HOME}/.claude"
SKILLS_DIR="${CLAUDE_DIR}/skills"
COMMANDS_DIR="${CLAUDE_DIR}/commands"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
warn() { printf "\033[33m! %s\033[0m\n" "$1"; }
ok()   { printf "\033[32mok\033[0m %s\n" "$1"; }

bold "work-plan toolkit uninstaller"

unlink_if_ours() {
    local label="$1"
    local src="$2"
    local dst="$3"

    if [ -L "${dst}" ] && [ "$(readlink "${dst}")" = "${src}" ]; then
        rm "${dst}"
        ok "removed ${label}"
    elif [ -e "${dst}" ]; then
        warn "${dst} exists but doesn't point into this toolkit — leaving alone"
    else
        ok "${label} already absent"
    fi
}

unlink_if_ours "work-plan skill"           "${TOOLKIT_DIR}/skills/work-plan"             "${SKILLS_DIR}/work-plan"
unlink_if_ours "repo-activity-summary skill" "${TOOLKIT_DIR}/skills/repo-activity-summary" "${SKILLS_DIR}/repo-activity-summary"
unlink_if_ours "work-plan command"         "${TOOLKIT_DIR}/commands/work-plan.md"        "${COMMANDS_DIR}/work-plan.md"

echo
bold "Done."
echo "Your config (~/.claude/work-plan/config.yml) and notes were not touched."
echo "Remove them manually if you want a clean slate."
