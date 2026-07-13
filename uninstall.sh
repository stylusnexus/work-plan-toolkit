#!/usr/bin/env bash
# uninstall.sh — remove work-plan toolkit copies  (macOS / Linux / WSL)
#
# Auto-detects target dir: ~/.claude/ (Claude Code) or ~/.agents/ (Codex).
# Override with --target=<dir>. Removes ONLY copies that were installed by this
# toolkit (verified via the .installed-from marker file). Leaves config + notes alone.

set -euo pipefail

TOOLKIT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

TARGET_OVERRIDE=""
for arg in "$@"; do
    case "${arg}" in
        --target=*) TARGET_OVERRIDE="${arg#--target=}" ;;
    esac
done

if [ -n "${TARGET_OVERRIDE}" ]; then
    BASE_DIR="${TARGET_OVERRIDE/#\~/$HOME}"
elif [ -d "${HOME}/.claude" ]; then
    BASE_DIR="${HOME}/.claude"
elif [ -d "${HOME}/.agents" ]; then
    BASE_DIR="${HOME}/.agents"
else
    printf "ERROR no target dir found.\n" >&2
    exit 1
fi

SKILLS_DIR="${BASE_DIR}/skills"
COMMANDS_DIR="${BASE_DIR}/commands"
LAUNCHER_MARKER_ID="stylusnexus/work-plan-toolkit launcher v1"

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

cmd_src="${TOOLKIT_DIR}/installer/work-plan.md"
cmd_dst="${COMMANDS_DIR}/work-plan.md"
if [ -f "${cmd_dst}" ] && cmp -s "${cmd_src}" "${cmd_dst}"; then
    rm -f "${cmd_dst}"
    ok "removed work-plan command"
elif [ -f "${cmd_dst}" ]; then
    warn "${cmd_dst} differs from this toolkit's copy — leaving alone"
else
    ok "command already absent"
fi

sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
    elif command -v python3 >/dev/null 2>&1; then python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
    else return 1
    fi
}

launcher_is_managed() {
    local dst="$1" marker="${1}.installed-from" recorded current extra
    [ -f "${dst}" ] && [ ! -L "${dst}" ] && [ -f "${marker}" ] && [ ! -L "${marker}" ] || return 1
    [ "$(sed -n '1p' "${marker}")" = "${LAUNCHER_MARKER_ID}" ] || return 1
    recorded="$(sed -n '2s/^sha256=//p' "${marker}")"
    extra="$(sed -n '3p' "${marker}")"
    [[ "${recorded}" =~ ^[0-9a-f]{64}$ ]] && [ -z "${extra}" ] || return 1
    current="$(sha256_file "${dst}")" || return 1
    [ "${current}" = "${recorded}" ]
}

# Remove only launchers whose marker and current content prove ownership.
for f in "${BASE_DIR}/bin/work-plan" "${BASE_DIR}/bin/work-plan.cmd"; do
    marker="${f}.installed-from"
    if launcher_is_managed "${f}"; then
        rm -f "${f}" "${marker}"
        ok "removed $(basename "${f}") launcher"
    elif [ -e "${f}" ] || [ -L "${f}" ] || [ -e "${marker}" ] || [ -L "${marker}" ]; then
        warn "${f} is unmanaged or modified — leaving launcher and marker alone"
    fi
done

echo
bold "Done."
echo "Your config (~/.claude/work-plan/config.yml) and notes were not touched."
echo "Remove them manually if you want a clean slate."
