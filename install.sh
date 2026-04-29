#!/usr/bin/env bash
# install.sh — install the work-plan toolkit into ~/.claude/  (macOS / Linux / WSL)
#
# Copies (not symlinks — for Windows compatibility via WSL paths) skills + command
# into ~/.claude/. Re-run after `git pull` to refresh.

set -euo pipefail

TOOLKIT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CLAUDE_DIR="${HOME}/.claude"
SKILLS_DIR="${CLAUDE_DIR}/skills"
COMMANDS_DIR="${CLAUDE_DIR}/commands"
CONFIG_DIR="${CLAUDE_DIR}/work-plan"
CONFIG_FILE="${CONFIG_DIR}/config.yml"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
warn() { printf "\033[33m! %s\033[0m\n" "$1"; }
ok()   { printf "\033[32mok\033[0m %s\n" "$1"; }
err()  { printf "\033[31mERROR\033[0m %s\n" "$1" >&2; }

bold "work-plan toolkit installer"
echo "Toolkit:  ${TOOLKIT_DIR}"
echo "Target:   ${CLAUDE_DIR}"
echo

# 1. Verify Claude Code dirs exist
if [ ! -d "${CLAUDE_DIR}" ]; then
    err "${CLAUDE_DIR} not found. Is Claude Code installed?"
    exit 1
fi
mkdir -p "${SKILLS_DIR}" "${COMMANDS_DIR}" "${CONFIG_DIR}"

# 2. Verify external dependencies
missing=()
for cmd in gh git yq python3; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        missing+=("${cmd}")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    err "Missing required tools: ${missing[*]}"
    echo
    echo "  gh:      https://cli.github.com/  (brew install gh)"
    echo "  git:     https://git-scm.com/     (brew install git)"
    echo "  yq:      https://github.com/mikefarah/yq  (brew install yq)"
    echo "  python3: https://www.python.org/  (brew install python)"
    exit 1
fi
ok "all dependencies present"

# 3. Copy skills (with marker file for safe uninstall)
copy_skill() {
    local name="$1"
    local src="${TOOLKIT_DIR}/skills/${name}"
    local dst="${SKILLS_DIR}/${name}"

    if [ -e "${dst}" ]; then
        # Re-install: only proceed if marker matches our toolkit
        if [ -f "${dst}/.installed-from" ] && grep -qx "${TOOLKIT_DIR}" "${dst}/.installed-from"; then
            rm -rf "${dst}"
        else
            warn "${dst} exists and was not installed by this toolkit."
            printf "    Overwrite? [y/N] "
            read -r ans
            if [ "${ans}" != "y" ] && [ "${ans}" != "Y" ]; then
                warn "skipped ${name}"
                return
            fi
            rm -rf "${dst}"
        fi
    fi
    cp -R "${src}" "${dst}"
    # Drop a marker so uninstall knows this copy is ours
    printf "%s\n" "${TOOLKIT_DIR}" > "${dst}/.installed-from"
    ok "copied ${name}"
}

copy_skill "work-plan"
copy_skill "repo-activity-summary"

# 4. Copy slash command (no marker file — single file)
cmd_src="${TOOLKIT_DIR}/commands/work-plan.md"
cmd_dst="${COMMANDS_DIR}/work-plan.md"
if [ -e "${cmd_dst}" ]; then
    if cmp -s "${cmd_src}" "${cmd_dst}"; then
        ok "command already up to date"
    else
        warn "${cmd_dst} differs from toolkit. Overwrite? [y/N] "
        read -r ans
        if [ "${ans}" = "y" ] || [ "${ans}" = "Y" ]; then
            cp "${cmd_src}" "${cmd_dst}"
            ok "copied command"
        else
            warn "skipped command"
        fi
    fi
else
    cp "${cmd_src}" "${cmd_dst}"
    ok "copied command"
fi

# 5. Seed config — only if it doesn't already exist
if [ -f "${CONFIG_FILE}" ]; then
    ok "config already exists, leaving alone (${CONFIG_FILE})"
else
    cp "${TOOLKIT_DIR}/config/config.example.yml" "${CONFIG_FILE}"
    abs_notes="${TOOLKIT_DIR}/notes"
    tmp="$(mktemp)"
    awk -v abs="${abs_notes}" '/^notes_root:/ { print "notes_root: " abs; next } { print }' \
        "${CONFIG_FILE}" > "${tmp}" && mv "${tmp}" "${CONFIG_FILE}"
    ok "seeded ${CONFIG_FILE} (notes_root: ${abs_notes})"
fi

# 6. Smoke test
echo
bold "Smoke test"
if python3 "${SKILLS_DIR}/work-plan/work_plan.py" --help >/dev/null 2>&1; then
    ok "work_plan.py --help runs"
else
    warn "work_plan.py --help failed — investigate manually"
fi

echo
bold "Done."
echo "Try:  python3 ${SKILLS_DIR}/work-plan/work_plan.py --help"
echo "Or in Claude Code: /work-plan --help"
echo
echo "Bootstrap your first repo:  /work-plan init-repo <key>"
echo "Re-run after 'git pull' to refresh."
