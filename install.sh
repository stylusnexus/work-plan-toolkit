#!/usr/bin/env bash
# install.sh — install the work-plan toolkit  (macOS / Linux / WSL)
#
# Auto-detects target dir: ~/.claude/ (Claude Code) or ~/.agents/ (Codex).
# Override with --target=<dir> for custom locations.
# Copies files (not symlinks — for Windows compatibility via WSL paths).
# Re-run after `git pull` to refresh.

set -euo pipefail

TOOLKIT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Parse --target flag if given
TARGET_OVERRIDE=""
for arg in "$@"; do
    case "${arg}" in
        --target=*) TARGET_OVERRIDE="${arg#--target=}" ;;
        --help|-h)
            cat <<HLP
Usage: ./install.sh [--target=<dir>]

Auto-detects target if --target not given:
  1. ~/.claude/  (Claude Code)
  2. ~/.agents/  (Codex)

To install for both, run twice:
  ./install.sh --target=\$HOME/.claude
  ./install.sh --target=\$HOME/.agents
HLP
            exit 0
            ;;
    esac
done

# Resolve target
if [ -n "${TARGET_OVERRIDE}" ]; then
    BASE_DIR="${TARGET_OVERRIDE/#\~/$HOME}"
elif [ -d "${HOME}/.claude" ]; then
    BASE_DIR="${HOME}/.claude"
elif [ -d "${HOME}/.agents" ]; then
    BASE_DIR="${HOME}/.agents"
else
    printf "\033[31mERROR\033[0m no target dir found. Looked for ~/.claude (Claude Code) and ~/.agents (Codex).\n" >&2
    printf "Pass --target=<dir> to install elsewhere, or install Claude Code / Codex first.\n" >&2
    exit 1
fi

SKILLS_DIR="${BASE_DIR}/skills"
COMMANDS_DIR="${BASE_DIR}/commands"
CONFIG_DIR="${BASE_DIR}/work-plan"
CONFIG_FILE="${CONFIG_DIR}/config.yml"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
warn() { printf "\033[33m! %s\033[0m\n" "$1"; }
ok()   { printf "\033[32mok\033[0m %s\n" "$1"; }
err()  { printf "\033[31mERROR\033[0m %s\n" "$1" >&2; }

bold "work-plan toolkit installer"
echo "Toolkit:  ${TOOLKIT_DIR}"
echo "Target:   ${BASE_DIR}"
echo

# 1. Verify Claude Code dirs exist
if [ ! -d "${BASE_DIR}" ]; then
    err "${BASE_DIR} not found. Pass --target=<dir> or install Claude Code / Codex first."
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

# 3.5 Copy VERSION file alongside work_plan.py so --version can read it.
# VERSION lives at the repo root (auto-bumped on each main push by
# .github/workflows/version-bump.yml); the runtime expects it next to the script.
if [ -f "${TOOLKIT_DIR}/VERSION" ]; then
    cp "${TOOLKIT_DIR}/VERSION" "${SKILLS_DIR}/work-plan/VERSION"
    ok "copied VERSION ($(tr -d '[:space:]' < "${TOOLKIT_DIR}/VERSION"))"
else
    warn "no VERSION file at toolkit root — --version will report 'unknown'"
fi

# 3.6 Install the bin/work-plan launcher (resolves the CLI relative to itself).
# Plugin installs get bin/ on PATH automatically; for install.sh we drop the
# launcher next to the skills tree and (best-effort) into the target's bin/.
if [ -f "${TOOLKIT_DIR}/bin/work-plan" ]; then
    install -m 0755 "${TOOLKIT_DIR}/bin/work-plan" "${SKILLS_DIR}/work-plan/work-plan" 2>/dev/null || true
    mkdir -p "${BASE_DIR}/bin"
    install -m 0755 "${TOOLKIT_DIR}/bin/work-plan" "${BASE_DIR}/bin/work-plan" \
        && ok "installed bin/work-plan launcher (${BASE_DIR}/bin)" \
        || warn "could not install bin/work-plan launcher"
fi

# 4. Copy the standalone dispatcher command (bare /work-plan). NOTE: only the
# single dispatcher is copied — the per-verb suite under commands/ is plugin-only
# (namespaced /work-plan:brief …); copying it here would create bare /brief etc.
cmd_src="${TOOLKIT_DIR}/installer/work-plan.md"
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

# 5. Seed config via the CLI — single source of seed content (see lib/config.py).
# The CLI always reads/writes ONE config home (~/.claude/work-plan/config.yml),
# regardless of install target, so we delegate rather than write it here. A
# config-dependent command (`list`) triggers load_config → ensure_config.
CANON_CONFIG="${HOME}/.claude/work-plan/config.yml"
if [ -f "${CANON_CONFIG}" ]; then
    ok "config already exists, leaving alone (${CANON_CONFIG})"
else
    if python3 "${SKILLS_DIR}/work-plan/work_plan.py" list >/dev/null 2>&1; then
        ok "seeded ${CANON_CONFIG}"
    else
        warn "could not seed config via the CLI — check python3 (${CANON_CONFIG})"
    fi
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
