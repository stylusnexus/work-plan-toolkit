# Org-Sharing Plugin Packaging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distribute `work-plan-toolkit` as two installable, auto-updating plugins (Claude Code + Codex) from one repo, served by a new public marketplace, while keeping `install.sh` working for everyone else.

**Architecture:** Strictly additive packaging over the existing CLI. Two manifests (`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`) wrap the unchanged `skills/` + `commands/` + `work_plan.py`. One slash command resolves the CLI path across all install modes via an env-var candidate probe. Config seeds lazily from the CLI (no install hook exists in either plugin system). A single semver, computed by a testable script and synced by CI into both manifests, drives update detection. A separate repo `stylusnexus/agent-plugins` carries both tools' marketplace index files.

**Tech Stack:** Python 3.9+ stdlib only (no third-party, no `match`); `gh` for GitHub; `git` subprocess; `yq` = mikefarah/yq; GitHub Actions; stdlib `unittest` (offline, mocked).

---

## Decisions made in this plan (flag for review)

1. **CalVer → semver (canonical).** `VERSION` becomes semver `MAJOR.MINOR.PATCH`, starting at **`1.0.0`**. `--version` reports semver. Both manifests carry the same semver. **Rationale:** Codex requires valid semver; a single scheme removes the drift risk; conventional-commit-driven bumping keeps every deploy a new version string so `/plugin update` works. This supersedes the spec's deferred "decide later" — **veto here if you'd rather keep CalVer as a separate build stamp.**
2. **Bump logic is extracted to `scripts/next_version.py`** (pure, offline-testable) and called by `version-bump.yml`, rather than inlined in YAML.
3. **Manifest metadata:** `license: "MIT"` (confirmed via `LICENSE`), `author.name: "Stylus Nexus"`, `repository`/`homepage`: `https://github.com/stylusnexus/work-plan-toolkit`.
4. **Default `notes_root` on seed:** `~/.claude/work-plan/notes` (a stable per-user path, NOT the ephemeral plugin cache). Matches the CLI's existing fixed config location `~/.claude/work-plan/config.yml`.
5. **Path probe uses plain `${CLAUDE_PLUGIN_ROOT}` (no `set -u`, no `:-`)** so it works whether the var is a real env var (Codex sets it for back-compat) or inline-substituted (Claude), falling through to `~/.claude` / `~/.agents` for installer users.

---

## File structure

| File | New/Mod | Responsibility |
|---|---|---|
| `.claude-plugin/plugin.json` | New | Claude Code plugin manifest (name/version/desc/meta) |
| `.codex-plugin/plugin.json` | New | Codex plugin manifest (same body, Codex schema) |
| `commands/work-plan.md` | Mod | Candidate-path probe resolving the CLI across install modes |
| `skills/work-plan/SKILL.md` | Mod | Document the same resolution order |
| `skills/work-plan/lib/config.py` | Mod | `ensure_config()` self-seeds `config.yml` on first run (single source of seed content) |
| `skills/work-plan/tests/test_config_seed.py` | New | Tests for `ensure_config()` |
| `skills/work-plan/tests/test_plugin_manifests.py` | New | Validates both manifests parse + carry required fields + equal version |
| `scripts/next_version.py` | New | Pure semver-bump from current version + commit subject |
| `scripts/test_next_version.py` | New | Offline tests for the bump function |
| `.github/workflows/version-bump.yml` | Mod | Compute semver via `next_version.py`; write VERSION + both manifests; semver CHANGELOG header |
| `VERSION` | Mod | CalVer string → `1.0.0` |
| `install.sh` | Mod | Delegate config seed to the CLI; keep lockstep |
| `install.ps1` | Mod | Same delegation (lockstep with `install.sh`) |
| `README.md` | Mod | Three install paths (Claude plugin · Codex plugin · install.sh) |
| **`stylusnexus/agent-plugins`** (separate repo) | New | `.claude-plugin/marketplace.json` + `.agents/plugins/marketplace.json` |

**Branching:** all code changes here go on one feature branch `feat/org-sharing-plugin-packaging` → PR to `dev` (squash-merge). The `stylusnexus/agent-plugins` repo is created and pushed separately (Task 12).

---

## Phase 1 — Claude plugin, end to end

### Task 1: Self-seeding config (`ensure_config`)

**Files:**
- Modify: `skills/work-plan/lib/config.py`
- Test: `skills/work-plan/tests/test_config_seed.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_config_seed.py
"""Tests for lazy config seeding (plugin installs run no install hook)."""
import sys
import unittest
from pathlib import Path
import tempfile

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.config import ensure_config, load_config


class EnsureConfigTest(unittest.TestCase):
    def test_seeds_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "work-plan" / "config.yml"
            created = ensure_config(cfg_path)
            self.assertTrue(created)
            self.assertTrue(cfg_path.is_file())
            cfg = load_config(cfg_path)
            self.assertIn("notes_root", cfg)
            self.assertEqual(cfg["repos"], {})

    def test_idempotent_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "work-plan" / "config.yml"
            ensure_config(cfg_path)
            before = cfg_path.read_bytes()
            created = ensure_config(cfg_path)
            self.assertFalse(created)
            self.assertEqual(cfg_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_config_seed -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_config'`.

- [ ] **Step 3: Implement `ensure_config` in `lib/config.py`**

Add after the imports/`DEFAULT_CONFIG_PATH` and before `load_config`:

```python
DEFAULT_NOTES_ROOT = Path.home() / ".claude" / "work-plan" / "notes"

_SEED_TEMPLATE = (
    "# work-plan config — auto-seeded on first run. Edit to customize.\n"
    "# Run /work-plan init-repo <key> --github=<org/repo> to populate repos:.\n"
    "notes_root: {notes_root}\n"
    "repos: {{}}\n"
)


def ensure_config(path: Path = DEFAULT_CONFIG_PATH,
                  notes_root: Path = DEFAULT_NOTES_ROOT) -> bool:
    """Create a default config.yml (and notes_root dir) if absent.

    Single source of the seed content — install.sh delegates here so plugin
    installs (which run no install hook) and script installs behave identically.
    Returns True if it created the file, False if it already existed.
    """
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(notes_root).mkdir(parents=True, exist_ok=True)
    path.write_text(_SEED_TEMPLATE.format(notes_root=notes_root), encoding="utf-8")
    return True
```

- [ ] **Step 4: Have `load_config` self-seed instead of hard-erroring**

In `load_config`, replace the `if not path.exists(): raise ConfigError(...)` block with:

```python
    path = Path(path)
    if not path.exists():
        ensure_config(path)
```

(Keep the rest of `load_config` unchanged. The old multi-line `ConfigError` guidance string is removed — first run now seeds rather than fails.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd skills/work-plan && python3 -m unittest tests.test_config_seed -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `cd skills/work-plan && python3 -m unittest discover tests`
Expected: OK. If any test asserted the old "config.yml not found" `ConfigError`, update it to assert seeding instead.

- [ ] **Step 7: Commit**

```bash
git add skills/work-plan/lib/config.py skills/work-plan/tests/test_config_seed.py
git commit -m "feat(config): self-seed config.yml on first run (plugin installs have no install hook)"
```

---

### Task 2: Claude plugin manifest + validity test

**Files:**
- Create: `.claude-plugin/plugin.json`
- Modify: `VERSION`
- Test: `skills/work-plan/tests/test_plugin_manifests.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plugin_manifests.py
"""Validates plugin manifests parse and carry required fields with one version."""
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _load(rel):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


class ClaudeManifestTest(unittest.TestCase):
    def test_parses_and_has_required_fields(self):
        m = _load(".claude-plugin/plugin.json")
        self.assertEqual(m["name"], "work-plan")
        self.assertTrue(SEMVER.match(m["version"]), m["version"])
        self.assertTrue(m["description"])

    def test_version_matches_VERSION_file(self):
        m = _load(".claude-plugin/plugin.json")
        ver = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(m["version"], ver)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plugin_manifests -v`
Expected: FAIL — file `.claude-plugin/plugin.json` does not exist.

- [ ] **Step 3: Set `VERSION` to semver**

Overwrite `VERSION` with exactly:

```
1.0.0
```

- [ ] **Step 4: Create `.claude-plugin/plugin.json`**

```json
{
  "name": "work-plan",
  "version": "1.0.0",
  "description": "Track-aware daily planning over GitHub issues, plus plan-status doc/plan liveness. Pure-stdlib CLI-backed skill.",
  "author": { "name": "Stylus Nexus", "email": "evemcgivern@gmail.com" },
  "homepage": "https://github.com/stylusnexus/work-plan-toolkit",
  "repository": "https://github.com/stylusnexus/work-plan-toolkit",
  "license": "MIT",
  "keywords": ["planning", "github-issues", "work-plan", "productivity", "agent-skill"]
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plugin_manifests -v`
Expected: PASS (Codex test class added in Task 6 will live in the same file later).

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json VERSION skills/work-plan/tests/test_plugin_manifests.py
git commit -m "feat(plugin): add Claude Code plugin manifest; VERSION -> semver 1.0.0"
```

---

### Task 3: Candidate-path probe in the slash command

**Files:**
- Modify: `commands/work-plan.md`

- [ ] **Step 1: Replace the body of `commands/work-plan.md`**

Keep the YAML frontmatter; replace the run instructions with:

````markdown
---
description: Track-aware daily work planning (5 essentials + --help for full list)
argument-hint: "[brief|handoff|orient|reconcile|hygiene|--help]"
---

Resolve the work-plan CLI across install modes (Claude plugin / Codex plugin /
install.sh / Codex `~/.agents`), then run it with the user's arguments. Do NOT
add `set -u` — the probe relies on unset vars expanding empty.

```bash
for c in \
  "${CLAUDE_PLUGIN_ROOT}/skills/work-plan/work_plan.py" \
  "${PLUGIN_ROOT}/skills/work-plan/work_plan.py" \
  "$HOME/.claude/skills/work-plan/work_plan.py" \
  "$HOME/.agents/skills/work-plan/work_plan.py"; do
  if [ -n "$c" ] && [ -f "$c" ]; then WORK_PLAN="$c"; break; fi
done
if [ -z "${WORK_PLAN:-}" ]; then
  echo "work-plan CLI not found (looked under CLAUDE_PLUGIN_ROOT, PLUGIN_ROOT, ~/.claude, ~/.agents)." >&2
  exit 1
fi
python3 "$WORK_PLAN" $ARGUMENTS
```

Then relay the output verbatim. If $ARGUMENTS is empty, run `--help`.

For the essentials: `brief` (multi-track snapshot) · `handoff <track>` (wrap up a
work block) · `orient <track>` (re-orient) · `hygiene` (weekly cleanup). For
everything else, run `--help` to discover.
````

- [ ] **Step 2: Sanity-check the probe locally (installer layout exists today)**

Run:
```bash
bash -c 'for c in "${CLAUDE_PLUGIN_ROOT}/skills/work-plan/work_plan.py" "${PLUGIN_ROOT}/skills/work-plan/work_plan.py" "$HOME/.claude/skills/work-plan/work_plan.py" "$HOME/.agents/skills/work-plan/work_plan.py"; do if [ -n "$c" ] && [ -f "$c" ]; then echo "RESOLVED: $c"; break; fi; done'
```
Expected: prints `RESOLVED: …/.claude/skills/work-plan/work_plan.py` (from a prior `./install.sh`). Confirms the fallback path works when plugin env vars are unset.

- [ ] **Step 3: Commit**

```bash
git add commands/work-plan.md
git commit -m "feat(command): resolve CLI path across plugin/install modes via candidate probe"
```

---

### Task 4: Document the resolution order in SKILL.md

**Files:**
- Modify: `skills/work-plan/SKILL.md` (the "how to run the CLI" lines, ~35–37)

- [ ] **Step 1: Replace the three hardcoded run lines**

Find:
```
- Claude Code: `python3 ~/.claude/skills/work-plan/work_plan.py <subcommand>`
- Codex: `python3 ~/.agents/skills/work-plan/work_plan.py <subcommand>`
- Cursor / Copilot / direct: `python3 <toolkit>/skills/work-plan/work_plan.py <subcommand>`
```

Replace with:
```
Resolve the CLI path in this order (first that exists wins), then run
`python3 <path> <subcommand>`:
1. `${CLAUDE_PLUGIN_ROOT}/skills/work-plan/work_plan.py`  (Claude plugin; also set by Codex for back-compat)
2. `${PLUGIN_ROOT}/skills/work-plan/work_plan.py`         (Codex plugin)
3. `~/.claude/skills/work-plan/work_plan.py`              (install.sh → Claude Code)
4. `~/.agents/skills/work-plan/work_plan.py`              (install.sh → Codex)
The `/work-plan` slash command performs this probe automatically.
```

- [ ] **Step 2: Commit**

```bash
git add skills/work-plan/SKILL.md
git commit -m "docs(skill): document multi-mode CLI path resolution"
```

---

### Task 5: Stand up the Claude marketplace index (in `stylusnexus/agent-plugins`)

> This task creates the **separate** marketplace repo and its Claude index. The Codex index is added in Task 11. Done outside the toolkit repo; no toolkit commit.

- [ ] **Step 1: Create the repo and the Claude index**

```bash
mkdir -p /tmp/agent-plugins/.claude-plugin
cat > /tmp/agent-plugins/.claude-plugin/marketplace.json <<'JSON'
{
  "name": "stylus-nexus",
  "owner": { "name": "Stylus Nexus" },
  "plugins": [
    {
      "name": "work-plan",
      "source": { "source": "github", "repo": "stylusnexus/work-plan-toolkit", "ref": "main" },
      "description": "Track-aware daily planning over GitHub issues, plus plan-status doc/plan liveness."
    }
  ]
}
JSON
cat > /tmp/agent-plugins/README.md <<'MD'
# Stylus Nexus — Agent Plugins Marketplace

Plugins for AI coding agents (Claude Code + Codex), sharing one body of skills.

## Claude Code
```
/plugin marketplace add stylusnexus/agent-plugins
/plugin install work-plan@stylus-nexus
```

## Codex
```
codex plugin marketplace add stylusnexus/agent-plugins
```
then install **work-plan** from the `/plugins` browser.
MD
```

- [ ] **Step 2: Validate the JSON parses**

Run: `python3 -c "import json,sys; json.load(open('/tmp/agent-plugins/.claude-plugin/marketplace.json')); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Create the GitHub repo and push**

```bash
cd /tmp/agent-plugins
git init -q && git add -A && git commit -q -m "feat: marketplace with work-plan (Claude index)"
gh repo create stylusnexus/agent-plugins --public --source=. --remote=origin --push
```

- [ ] **Step 4: Verify the marketplace resolves**

Run: `gh repo view stylusnexus/agent-plugins --json visibility,name`
Expected: `{"name":"agent-plugins","visibility":"PUBLIC"}`.

---

### Task 6: Phase-1 end-to-end verification (Claude plugin)

> Manual verification on a real Claude Code install. No code; record results in the PR.

- [ ] **Step 1: Add the marketplace and install**

In a Claude Code session:
```
/plugin marketplace add stylusnexus/agent-plugins
/plugin install work-plan@stylus-nexus
```

- [ ] **Step 2: Verify the command resolves and runs**

Run `/work-plan --help`.
Expected: the help text renders (CLI resolved via `${CLAUDE_PLUGIN_ROOT}`). If it fails, inspect which probe candidate matched (temporarily echo `$WORK_PLAN`).

- [ ] **Step 3: Verify version + first-run seed**

Run `/work-plan --version` → expected `work-plan 1.0.0`.
Confirm `~/.claude/work-plan/config.yml` now exists (seeded on first run) with `notes_root: ~/.claude/work-plan/notes`.

- [ ] **Step 4: Record evidence in the PR description.** Exit criterion: a Claude Code user installs and runs `/work-plan` with no clone and no `install.sh`.

---

## Phase 2 — Codex plugin

### Task 7: Codex plugin manifest + validity test

**Files:**
- Create: `.codex-plugin/plugin.json`
- Modify: `skills/work-plan/tests/test_plugin_manifests.py`

- [ ] **Step 1: Extend the manifest test (failing)**

Append to `skills/work-plan/tests/test_plugin_manifests.py`:

```python
class CodexManifestTest(unittest.TestCase):
    def test_parses_and_has_required_fields(self):
        m = _load(".codex-plugin/plugin.json")
        self.assertEqual(m["name"], "work-plan")
        self.assertTrue(SEMVER.match(m["version"]), m["version"])
        self.assertTrue(m["description"])

    def test_codex_and_claude_versions_match(self):
        c = _load(".claude-plugin/plugin.json")["version"]
        x = _load(".codex-plugin/plugin.json")["version"]
        self.assertEqual(c, x)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plugin_manifests -v`
Expected: FAIL — `.codex-plugin/plugin.json` missing.

- [ ] **Step 3: Create `.codex-plugin/plugin.json`**

```json
{
  "name": "work-plan",
  "version": "1.0.0",
  "description": "Track-aware daily planning over GitHub issues, plus plan-status doc/plan liveness. Pure-stdlib CLI-backed skill.",
  "author": { "name": "Stylus Nexus", "email": "evemcgivern@gmail.com" },
  "homepage": "https://github.com/stylusnexus/work-plan-toolkit",
  "repository": "https://github.com/stylusnexus/work-plan-toolkit",
  "license": "MIT",
  "keywords": ["planning", "github-issues", "work-plan", "productivity", "agent-skill"],
  "interface": {
    "displayName": "Work Plan",
    "shortDescription": "Track-aware daily planning over GitHub issues.",
    "category": "productivity"
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plugin_manifests -v`
Expected: PASS (Claude + Codex classes).

- [ ] **Step 5: Commit**

```bash
git add .codex-plugin/plugin.json skills/work-plan/tests/test_plugin_manifests.py
git commit -m "feat(plugin): add Codex plugin manifest (.codex-plugin/plugin.json)"
```

---

### Task 8: Add the Codex marketplace index (in `stylusnexus/agent-plugins`)

> Separate repo again. Codex marketplace schema mirrors the Claude one; place at `.agents/plugins/marketplace.json`.

- [ ] **Step 1: Add the Codex index**

```bash
mkdir -p /tmp/agent-plugins/.agents/plugins
cat > /tmp/agent-plugins/.agents/plugins/marketplace.json <<'JSON'
{
  "name": "stylus-nexus",
  "owner": { "name": "Stylus Nexus" },
  "plugins": [
    {
      "name": "work-plan",
      "source": { "source": "github", "repo": "stylusnexus/work-plan-toolkit", "ref": "main" },
      "description": "Track-aware daily planning over GitHub issues, plus plan-status doc/plan liveness."
    }
  ]
}
JSON
python3 -c "import json; json.load(open('/tmp/agent-plugins/.agents/plugins/marketplace.json')); print('ok')"
```
Expected: `ok`.

- [ ] **Step 2: Commit and push to the marketplace repo**

```bash
cd /tmp/agent-plugins
git add -A && git commit -m "feat: add Codex marketplace index"
git push origin main
```

---

### Task 9: Phase-2 end-to-end verification (Codex plugin)

> Manual verification in Codex. No code; record results in the PR.

- [ ] **Step 1: Add the marketplace + install in Codex**

```
codex plugin marketplace add stylusnexus/agent-plugins
```
Install **work-plan** via the `/plugins` browser.

- [ ] **Step 2: Verify resolution + version**

Run `/work-plan --help` and `/work-plan --version` in Codex.
Expected: help renders (CLI resolved via `CLAUDE_PLUGIN_ROOT` back-compat or `PLUGIN_ROOT`); version is `1.0.0`.

- [ ] **Step 3: Record evidence in the PR.** Exit criterion: a Codex user installs and runs `/work-plan` with no clone.

---

## Phase 3 — Versioning, docs, and lockstep

### Task 10: Testable semver bump script

**Files:**
- Create: `scripts/next_version.py`
- Create: `scripts/test_next_version.py`

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_next_version.py
"""Offline tests for next_version.bump (run: python3 scripts/test_next_version.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from next_version import bump


class BumpTest(unittest.TestCase):
    def test_feat_bumps_minor(self):
        self.assertEqual(bump("1.2.3", "feat(plugin): add manifest"), "1.3.0")

    def test_fix_bumps_patch(self):
        self.assertEqual(bump("1.2.3", "fix(config): seed path"), "1.2.4")

    def test_chore_and_docs_bump_patch(self):
        self.assertEqual(bump("1.2.3", "chore: tidy"), "1.2.4")
        self.assertEqual(bump("1.2.3", "docs: readme"), "1.2.4")

    def test_breaking_bang_bumps_major(self):
        self.assertEqual(bump("1.2.3", "feat(api)!: rename flag"), "2.0.0")

    def test_breaking_footer_bumps_major(self):
        self.assertEqual(bump("1.2.3", "feat: x\n\nBREAKING CHANGE: y"), "2.0.0")

    def test_non_semver_current_raises(self):
        with self.assertRaises(ValueError):
            bump("2026.06.06+abc", "fix: x")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 scripts/test_next_version.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'next_version'`.

- [ ] **Step 3: Implement `scripts/next_version.py`**

```python
#!/usr/bin/env python3
"""Compute the next semver from current VERSION + a conventional-commit subject.

Pure stdlib, no `match`. Used by .github/workflows/version-bump.yml and unit-
tested offline. Usage: next_version.py <current-semver> <commit-subject>
"""
import re
import sys

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TYPE = re.compile(r"^([a-z]+)")


def bump(current: str, subject: str) -> str:
    m = _SEMVER.match(current.strip())
    if not m:
        raise ValueError(f"VERSION is not semver: {current!r}")
    major, minor, patch = (int(g) for g in m.groups())
    s = subject.strip()
    head = s.split(":", 1)[0] if ":" in s else ""
    is_breaking = head.endswith("!") or "BREAKING CHANGE" in s
    tmatch = _TYPE.match(head)
    type_ = tmatch.group(1) if tmatch else ""
    if is_breaking:
        return f"{major + 1}.0.0"
    if type_ == "feat":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main(argv: list) -> int:
    if len(argv) != 3:
        print("usage: next_version.py <current-semver> <commit-subject>", file=sys.stderr)
        return 2
    print(bump(argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 scripts/test_next_version.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/next_version.py scripts/test_next_version.py
git commit -m "feat(ci): add testable semver bump script"
```

---

### Task 11: Rework `version-bump.yml` to semver + sync manifests

**Files:**
- Modify: `.github/workflows/version-bump.yml`

- [ ] **Step 1: Replace the "Compute and write VERSION" step**

Replace the `Compute and write VERSION` step (the `DATE=…/SHA=…/NEW=…` block) with:

```yaml
      - name: Compute and write semver
        id: compute
        env:
          PR_TITLE: ${{ github.event.pull_request.title }}
        run: |
          CURRENT="$(cat VERSION)"
          SUBJECT="${PR_TITLE:-fix: manual bump}"
          NEW="$(python3 scripts/next_version.py "$CURRENT" "$SUBJECT")"
          echo "$NEW" > VERSION
          python3 - "$NEW" <<'PY'
          import json, sys
          new = sys.argv[1]
          for path in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
              with open(path) as f:
                  data = json.load(f)
              data["version"] = new
              with open(path, "w") as f:
                  json.dump(data, f, indent=2)
                  f.write("\n")
          PY
          echo "new_version=$NEW" >> "$GITHUB_OUTPUT"
```

- [ ] **Step 2: Fix the CHANGELOG step's version/date derivation**

In the `Prepend CHANGELOG entry` step's Python heredoc, replace:
```python
          date = ver.split("+")[0].replace(".", "-")  # 2026.06.04 -> 2026-06-04
```
with:
```python
          import datetime
          date = datetime.date.today().isoformat()  # semver has no date; stamp today (UTC runner)
```

- [ ] **Step 3: Update the commit step to stage the manifests**

In the `Commit and push if anything changed` step, change the diff-guard and `git add` to include the manifests:
```bash
          if git diff --quiet VERSION CHANGELOG.md .claude-plugin/plugin.json .codex-plugin/plugin.json; then
            echo "Nothing to commit."
            exit 0
          fi
```
and
```bash
          git add VERSION CHANGELOG.md .claude-plugin/plugin.json .codex-plugin/plugin.json
```

- [ ] **Step 4: Update the job name comment**

Change `name: Bump VERSION to <date>+<sha>` to `name: Bump semver`.

- [ ] **Step 5: Dry-run the compute logic locally**

Run:
```bash
python3 scripts/next_version.py "$(cat VERSION)" "feat(plugin): packaging"
```
Expected: `1.1.0` (from `1.0.0` + a `feat`). Confirms the workflow's core call.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/version-bump.yml
git commit -m "feat(ci): bump semver from commit type and sync into both plugin manifests"
```

---

### Task 12: Delegate config seeding from the installers (lockstep)

**Files:**
- Modify: `install.sh`
- Modify: `install.ps1`

- [ ] **Step 1: Replace the config-seed block in `install.sh`**

Replace the heredoc seed (the `if [ -f "${CONFIG_FILE}" ] … else … cat > … EOF … fi` block, ~149–161) with delegation to the CLI:

```bash
# 5. Seed config via the CLI (single source of seed content; see lib/config.py)
if [ -f "${CONFIG_FILE}" ]; then
    ok "config already exists, leaving alone (${CONFIG_FILE})"
else
    if python3 "${SKILLS_DIR}/work-plan/work_plan.py" --version >/dev/null 2>&1; then
        ok "config will self-seed on first run (${CONFIG_FILE})"
    else
        warn "could not run CLI to seed config — check python3"
    fi
fi
```

(Rationale: the CLI seeds lazily via `ensure_config` on first real invocation; the installer no longer owns seed content. `--version` does not trigger seeding, so this only reports intent — seeding happens on the first command that calls `load_config`. If you prefer eager seeding, replace the `--version` probe with `… work_plan.py list >/dev/null 2>&1` which calls `load_config`.)

- [ ] **Step 2: Mirror the change in `install.ps1`**

Replace the PowerShell config-seed block with the equivalent delegation:

```powershell
# 5. Seed config via the CLI (single source of seed content; see lib/config.py)
if (Test-Path $ConfigFile) {
    Ok "config already exists, leaving alone ($ConfigFile)"
} else {
    & python3 "$SkillsDir/work-plan/work_plan.py" list *> $null
    if ($LASTEXITCODE -eq 0) { Ok "config seeded on first run ($ConfigFile)" }
    else { Warn "could not run CLI to seed config — check python3" }
}
```

- [ ] **Step 3: Verify install.sh still completes**

Run: `./install.sh --target="$(mktemp -d)/.claude"`
Expected: copies skills + command, prints the config-seed line, smoke test passes.

- [ ] **Step 4: Commit**

```bash
git add install.sh install.ps1
git commit -m "refactor(install): delegate config seeding to the CLI (lockstep sh/ps1)"
```

---

### Task 13: README — three install paths

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add an "Install" section near the top of `README.md`**

Insert after the project intro / before the existing install instructions:

````markdown
## Install

Pick the path for your tool. All three install the same skill + CLI.

### Claude Code (recommended) — plugin, auto-updates
```
/plugin marketplace add stylusnexus/agent-plugins
/plugin install work-plan@stylus-nexus
```
Update later with `/plugin update work-plan@stylus-nexus`. Works in the CLI and the VS Code / JetBrains extensions.

### Codex — plugin, auto-updates
```
codex plugin marketplace add stylusnexus/agent-plugins
```
Then install **work-plan** from the `/plugins` browser.

### Cursor / direct / other — script
```
git clone https://github.com/stylusnexus/work-plan-toolkit
cd work-plan-toolkit && ./install.sh            # or ./install.sh --target=$HOME/.agents
```
Re-run `./install.sh` after `git pull` to refresh (the plugin paths above update themselves).
````

- [ ] **Step 2: Make the existing install.sh docs reference the new section** (avoid duplication — point the old "Installation" prose at the script path above; keep requirements/`yq`/`gh` notes).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): three install paths (Claude plugin, Codex plugin, install.sh)"
```

---

### Task 14: Refresh the live skill, full suite, open PR

- [ ] **Step 1: Reinstall to refresh the live skill**

Run: `./install.sh`
Expected: `ok copied work-plan`, smoke test passes.

- [ ] **Step 2: Run the full offline suite**

Run: `cd skills/work-plan && python3 -m unittest discover tests`
Expected: OK (includes the new `test_config_seed`, `test_plugin_manifests`).

- [ ] **Step 3: Run the CI script test**

Run: `python3 scripts/test_next_version.py`
Expected: OK.

- [ ] **Step 4: Push the branch and open the PR**

```bash
git push -u origin feat/org-sharing-plugin-packaging
gh pr create --base dev \
  --title "feat: package as Claude + Codex plugins with marketplace distribution" \
  --body "Implements docs/superpowers/specs/2026-06-05-org-sharing-plugin-packaging-design.md. Dual plugins from one repo; candidate-path CLI resolution; self-seeding config; semver (replaces CalVer) synced into both manifests by CI; README three install paths. Marketplace repo: stylusnexus/agent-plugins (separate). Phase 1/2 end-to-end install evidence in comments."
```

- [ ] **Step 5: Record Phase-1/2 manual install evidence** (Tasks 6 & 9) in the PR description before requesting merge.

---

## Self-Review

**Spec coverage** (each spec section → task):
- §1 Two manifests, one body → Tasks 2, 7.
- §2 Path resolution (probe) → Task 3 (+ SKILL.md Task 4).
- §3 Config seeding (lazy, single source) → Task 1; installers delegate → Task 12.
- §4 Versioning (semver canonical, CI sync) → Tasks 10, 11; VERSION→semver in Task 2.
- §5 Marketplace (one repo, two indexes, neutral name) → Tasks 5, 8.
- §6 Docs + lockstep → Tasks 4, 12, 13.
- Phasing (P1 Claude e2e / P2 Codex / P3 versioning+docs) → Tasks 1–6 / 7–9 / 10–14.
- Verification cases → covered by Task 1 (seed idempotency), Task 2/7 (manifests), Task 3 (probe), Tasks 6/9 (e2e), Task 10 (version), Task 14 (non-regression suite).

**Placeholder scan:** No "TBD/TODO"; every code/JSON/YAML step shows full content. The CalVer↔semver open item is **resolved** (Decisions §1), not deferred.

**Type/name consistency:** `ensure_config(path, notes_root)` defined in Task 1 and called by installers (Task 12) and tests (Task 1). `bump(current, subject)` defined in Task 10, used by its test (Task 10) and the workflow (Task 11). Manifest `version` field asserted equal to `VERSION` (Task 2) and across manifests (Task 7), and written by the workflow (Task 11) — all consistent. Marketplace `name` is `stylus-nexus` everywhere (Tasks 5, 8, 13).

**Open risk to watch during execution:** the `${CLAUDE_PLUGIN_ROOT}` substitution-vs-env behavior in *command* markdown is verified live in Task 6 Step 2; the `~/.claude` fallback covers the failure case.
