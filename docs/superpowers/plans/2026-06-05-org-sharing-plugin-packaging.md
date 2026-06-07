# Org-Sharing Plugin Packaging — Implementation Plan (rev. 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distribute `work-plan-toolkit` as installable, updatable plugins (Claude Code + Codex) from one repo via a public marketplace, with a namespaced command suite, while keeping `install.sh` working for everyone else.

**Architecture:** Additive packaging over the unchanged CLI. A self-locating `bin/work-plan` wrapper resolves the CLI in every install mode. Thin command wrappers (namespaced under the plugin) call that wrapper. Config self-seeds from the CLI at one fixed home. CalVer (unchanged) is written into the manifests by CI. One shared `.claude-plugin/marketplace.json`, pinned to a release tag, serves both hosts.

**Tech Stack:** Python 3.9+ stdlib only (no third-party, no `match`); `gh`; `git` subprocess; `yq` = mikefarah/yq; GitHub Actions; stdlib `unittest` (offline, mocked).

**Source of truth:** `docs/superpowers/specs/2026-06-05-org-sharing-plugin-packaging-design.md` (revised after Codex spec-review). This plan was rewritten to match that revision.

---

## Decisions carried from the spec (no re-litigation needed)

1. **Versioning: keep CalVer.** No semver, no `next_version.py`. CI writes the existing `VERSION`
   string into the manifest(s).
2. **CLI resolution: `bin/work-plan` self-locating wrapper** (not an env-var markdown probe).
3. **Command surface: namespaced suite** (`brief/handoff/orient/hygiene/status` + `run` catch-all)
   for the plugin; `install.sh` copies only the single `/work-plan` dispatcher.
4. **One config home** `~/.claude/work-plan/config.yml` for all hosts; CLI self-seeds; installers delegate.
5. **One marketplace index** `.claude-plugin/marketplace.json`, **tag-pinned**; Codex reads it
   legacy-compatible.
6. **Manifest metadata:** `license: "MIT"`, `author.name: "Stylus Nexus"`,
   `repository`/`homepage`: `https://github.com/stylusnexus/work-plan-toolkit`.

---

## Corrections from the verification spike (2026-06-05) — these OVERRIDE conflicting task text below

A hands-on spike against the real `claude`/`codex` CLIs proved the mechanics and corrected the plan.
Apply these everywhere they touch:

1. **`bin/work-plan` resolves from the wrapper's PARENT** (`root="$(cd "$(dirname "$0")/.." && pwd)"`,
   then `$root/skills/...`) — `$here/skills` was a real bug. Add a `${PLUGIN_ROOT:-}` candidate (Codex).
   *(Applied in Task 2.)*
2. **`$ARGUMENTS` stays UNQUOTED in every wrapper.** Quoting breaks `reconcile --all`. *(Applied in Task 4.)*
3. **Never ship `commands/work-plan.md` in the plugin** — it collides with the `work-plan` skill
   (`claude plugin details` showed `work-plan` twice). In `.claude-plugin/plugin.json` set a
   `"commands"` allowlist of the suite + `run` only (omit `work-plan.md`); if the allowlist can't
   exclude a file, instead keep the dispatcher OUTSIDE `commands/` and have `install.sh` copy it from
   there. Verify with `claude plugin details work-plan` → `work-plan` appears **once**.
4. **CalVer is fine** (passes `claude plugin validate --strict`; Codex installs it). Add
   **`claude plugin validate --strict <plugin>`** as a CI/test gate (Task 3 + a CI step in Task 12).
5. **One marketplace index suffices for BOTH hosts** (Claude + Codex both installed from it). No second
   index. The marketplace.json needs a top-level `"description"` (else a validate warning). A LOCAL
   test marketplace uses a relative `source` (`"./work-plan"`); the published one uses the `github` source.
6. **`.codex-plugin/plugin.json` must declare `"skills": "./skills/"`** (don't rely on auto-discovery).
   *(Add to Task 10.)*
7. **Release ordering:** merge → let `version-bump.yml` run (it now also syncs the manifests) → **tag
   the bump commit** → point the marketplace `ref` at that tag. Do NOT tag the merge commit (it
   predates the manifest sync). *(Fixes Task 7.)*
8. **Windows:** the bash `bin/work-plan` doesn't run natively — `install.ps1` ships a `.cmd`/`.ps1`
   shim (or the command files call `python3 <resolved>` directly); verify on the Windows CI matrix.
   *(Add to Task 13.)*
9. **Config-seed tests run under a temporary `$HOME`** and assert the created file + parsed contents;
   no `|| true` masking of failures in tests. `ensure_config` writes an **absolute** `notes_root`
   (`Path.home()/...`), and `tracks.py` gains a defensive `expanduser()`.

---

## File structure

| File | New/Mod | Responsibility |
|---|---|---|
| `bin/work-plan` | New | Self-locating wrapper → `python3 <resolved>/work_plan.py "$@"` |
| `.claude-plugin/plugin.json` | New | Claude manifest (name/version=CalVer/desc/meta) |
| `.codex-plugin/plugin.json` | New | Codex manifest (same body + `interface`) |
| `commands/work-plan.md` | Mod | The single dispatcher (only file `install.sh` copies); empty args → `--help` |
| `commands/brief.md` `handoff.md` `orient.md` `hygiene.md` `status.md` `run.md` | New | Namespaced suite (plugin only); each calls `work-plan <sub> "$ARGUMENTS"` |
| `skills/work-plan/lib/config.py` | Mod | `ensure_config()`; `load_config()` self-seeds when absent |
| `skills/work-plan/tests/test_config_seed.py` | New | Seeding via `load_config()` from a clean path |
| `skills/work-plan/tests/test_plugin_manifests.py` | New | Manifests parse, required fields, version == `VERSION` |
| `tests/test_bin_wrapper.py` (repo-root) | New | `bin/work-plan` resolution logic (offline, fake layouts) |
| `.github/workflows/version-bump.yml` | Mod | Also write CalVer into both manifests; stage them |
| `install.sh` / `install.ps1` | Mod | Copy only the dispatcher; delegate config seed; lockstep |
| `README.md` | Mod | Three install paths; namespaced names; CalVer |
| **`stylusnexus/agent-plugins`** (separate repo) | New | One `.claude-plugin/marketplace.json`, tag-pinned |

**Branching:** code on `feat/org-sharing-plugin-packaging` → PR to `dev`. The marketplace repo is created/pushed separately and **pinned to a tag cut after the toolkit PR merges** (avoids the circular-verification bug).

---

## Phase 1 — Claude plugin, end to end

### Task 1: Self-seeding config via `load_config()`

**Files:** Modify `skills/work-plan/lib/config.py`; Create `skills/work-plan/tests/test_config_seed.py`

- [ ] **Step 1: Write the failing test** (proves seeding through `load_config`, per the review)

```python
# skills/work-plan/tests/test_config_seed.py
"""Lazy config seeding (plugin installs run no install hook)."""
import sys, tempfile, unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))
from lib.config import load_config, ensure_config


class EnsureConfigTest(unittest.TestCase):
    def test_load_config_seeds_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "work-plan" / "config.yml"
            cfg = load_config(cfg_path)          # must NOT raise; must seed
            self.assertTrue(cfg_path.is_file())
            self.assertIn("notes_root", cfg)
            self.assertEqual(cfg["repos"], {})

    def test_ensure_config_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "work-plan" / "config.yml"
            self.assertTrue(ensure_config(cfg_path, notes_root=Path(d) / "notes"))
            before = cfg_path.read_bytes()
            self.assertFalse(ensure_config(cfg_path, notes_root=Path(d) / "notes"))
            self.assertEqual(cfg_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_config_seed -v`
Expected: FAIL (`ImportError: ensure_config`, and `load_config` raises on missing).

- [ ] **Step 3: Implement in `lib/config.py`**

Add near the top (after `DEFAULT_CONFIG_PATH`):

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
    """Create a default config.yml (+ notes_root dir) if absent. Single source
    of seed content — installers delegate here. Returns True if it created it."""
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(notes_root).mkdir(parents=True, exist_ok=True)
    path.write_text(_SEED_TEMPLATE.format(notes_root=notes_root), encoding="utf-8")
    return True
```

Then in `load_config`, replace the missing-file `raise ConfigError(...)` block with:

```python
    path = Path(path)
    if not path.exists():
        ensure_config(path)
```

- [ ] **Step 4: Run tests — verify pass**

Run: `cd skills/work-plan && python3 -m unittest tests.test_config_seed -v`  → PASS (2).

- [ ] **Step 5: Full suite (fix any test that asserted the old "not found" ConfigError)**

Run: `cd skills/work-plan && python3 -m unittest discover tests`  → OK.

- [ ] **Step 6: Commit**

```bash
git add skills/work-plan/lib/config.py skills/work-plan/tests/test_config_seed.py
git commit -m "feat(config): self-seed config.yml via load_config on first run"
```

---

### Task 2: `bin/work-plan` self-locating wrapper

**Files:** Create `bin/work-plan`; Create `tests/test_bin_wrapper.py` (repo root)

- [ ] **Step 1: Write the failing test** (offline; builds fake layouts in tmp)

```python
# tests/test_bin_wrapper.py
"""bin/work-plan resolves the CLI relative to itself and via fallbacks."""
import os, stat, subprocess, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "bin" / "work-plan"


class BinWrapperTest(unittest.TestCase):
    def _fake_cli(self, root: Path):
        cli = root / "skills" / "work-plan" / "work_plan.py"
        cli.parent.mkdir(parents=True, exist_ok=True)
        cli.write_text("import sys; print('CLI', *sys.argv[1:])\n")
        return cli

    def test_resolves_self_relative(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._fake_cli(root)
            bindir = root / "bin"; bindir.mkdir()
            wp = bindir / "work-plan"
            wp.write_text(WRAPPER.read_text())
            wp.chmod(wp.stat().st_mode | stat.S_IEXEC)
            out = subprocess.run([str(wp), "brief", "x"], capture_output=True, text=True,
                                 env={**os.environ, "HOME": d})
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("CLI brief x", out.stdout)

    def test_errors_when_no_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            wp = Path(d) / "bin" / "work-plan"; wp.parent.mkdir()
            wp.write_text(WRAPPER.read_text()); wp.chmod(0o755)
            out = subprocess.run([str(wp), "brief"], capture_output=True, text=True,
                                 env={**os.environ, "HOME": str(Path(d) / "empty")})
            self.assertEqual(out.returncode, 1)
            self.assertIn("CLI not found", out.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it — verify it fails**

Run: `python3 tests/test_bin_wrapper.py -v`
Expected: FAIL — `bin/work-plan` does not exist.

- [ ] **Step 3: Create `bin/work-plan`**

```sh
#!/usr/bin/env bash
# Resolve work_plan.py relative to the wrapper's PARENT (plugin root: the wrapper
# is <root>/bin/work-plan), then known install paths. The `../` is load-bearing —
# `$here/skills` would be `<root>/bin/skills` and never exist (spike-verified).
root="$(cd "$(dirname "$0")/.." && pwd)"
for c in \
  "$root/skills/work-plan/work_plan.py" \
  "${CLAUDE_PLUGIN_ROOT:-}/skills/work-plan/work_plan.py" \
  "${PLUGIN_ROOT:-}/skills/work-plan/work_plan.py" \
  "$HOME/.claude/skills/work-plan/work_plan.py" \
  "$HOME/.agents/skills/work-plan/work_plan.py"; do
  [ -n "$c" ] && [ -f "$c" ] && exec python3 "$c" "$@"
done
echo "work-plan: CLI not found (looked next to bin/.., CLAUDE_PLUGIN_ROOT, PLUGIN_ROOT, ~/.claude, ~/.agents)." >&2
exit 1
```

Then: `chmod +x bin/work-plan`
(The Step-1 test builds `<root>/bin/work-plan` + `<root>/skills/...` as siblings, so `../` resolution
is exactly what makes it pass — spike-confirmed against both the Claude and Codex caches.)

- [ ] **Step 4: Run tests — verify pass**

Run: `python3 tests/test_bin_wrapper.py -v`  → PASS (2).

- [ ] **Step 5: Commit**

```bash
git add bin/work-plan tests/test_bin_wrapper.py
git commit -m "feat(bin): self-locating work-plan wrapper resolving the CLI across install modes"
```

---

### Task 3: Claude plugin manifest + validity test

**Files:** Create `.claude-plugin/plugin.json`; Create `skills/work-plan/tests/test_plugin_manifests.py`

- [ ] **Step 1: Write the failing test**

```python
# skills/work-plan/tests/test_plugin_manifests.py
"""Manifests parse, carry required fields, and match VERSION (CalVer string)."""
import json, unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load(rel):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


class ClaudeManifestTest(unittest.TestCase):
    def test_required_fields(self):
        m = _load(".claude-plugin/plugin.json")
        self.assertEqual(m["name"], "work-plan")
        self.assertTrue(m["description"])

    def test_version_matches_VERSION(self):
        m = _load(".claude-plugin/plugin.json")
        ver = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(m["version"], ver)   # CalVer string, not semver


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plugin_manifests -v`  → FAIL (missing file).

- [ ] **Step 3: Create `.claude-plugin/plugin.json`** (set `version` to the CURRENT `VERSION` string)

```json
{
  "name": "work-plan",
  "version": "PASTE_CURRENT_VERSION_STRING",
  "description": "Track-aware daily planning over GitHub issues, plus plan-status doc/plan liveness. Pure-stdlib CLI-backed skill.",
  "author": { "name": "Stylus Nexus", "email": "evemcgivern@gmail.com" },
  "homepage": "https://github.com/stylusnexus/work-plan-toolkit",
  "repository": "https://github.com/stylusnexus/work-plan-toolkit",
  "license": "MIT",
  "keywords": ["planning", "github-issues", "work-plan", "productivity", "agent-skill"]
}
```

Set `version` by running `cat VERSION` and pasting the exact string (e.g. `2026.06.06+7909ca5`).

- [ ] **Step 4: Run tests — verify pass**

Run: `cd skills/work-plan && python3 -m unittest tests.test_plugin_manifests -v`  → PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/plugin.json skills/work-plan/tests/test_plugin_manifests.py
git commit -m "feat(plugin): add Claude Code plugin manifest (version = current CalVer)"
```

---

### Task 4: Namespaced command suite + dispatcher

**Files:** Create `commands/{brief,handoff,orient,hygiene,status,run}.md`; Modify `commands/work-plan.md`

> **Collision (spike-confirmed):** `commands/work-plan.md` and the `work-plan` skill both register as
> `work-plan` — `claude plugin details` listed it **twice**. So `commands/work-plan.md` must be
> **excluded from the plugin** and exist **only** for `install.sh` standalone. Exclude it via the
> manifest `commands` allowlist (Step 5) — list only the suite + `run`, omit `work-plan.md`.

- [ ] **Step 1: Rewrite the dispatcher `commands/work-plan.md`** (empty args → `--help`; UNQUOTED args)

````markdown
---
description: Track-aware daily work planning (dispatcher; --help for full list)
argument-hint: "[brief|handoff|orient|hygiene|status|--help]"
---

Run the work-plan CLI via the PATH wrapper and relay output verbatim:

```bash
if [ -z "$ARGUMENTS" ]; then work-plan --help; else work-plan $ARGUMENTS; fi
```

(`work-plan` is the plugin's `bin/` wrapper, also installed by `install.sh`.)
````

- [ ] **Step 2: Create the five verb wrappers** — each identical in shape. Example `commands/brief.md`:

````markdown
---
description: Multi-track daily snapshot across your GitHub issues.
argument-hint: "[--repo=<key>]"
---

```bash
work-plan brief $ARGUMENTS
```

Relay the output verbatim.
````

Create `handoff.md` (`work-plan handoff $ARGUMENTS`), `orient.md` (`work-plan orient $ARGUMENTS`),
`hygiene.md` (`work-plan hygiene $ARGUMENTS`), `status.md` (`work-plan plan-status $ARGUMENTS`). Same
frontmatter+relay shape; only the subcommand and `description`/`argument-hint` differ. **Leave
`$ARGUMENTS` UNQUOTED everywhere** — bash re-parses the substituted text and honors the user's own
inline quotes, so `reconcile --all` splits into argv while a user-quoted `--milestone='v1 — Launch'`
stays intact. (Quoting `"$ARGUMENTS"` collapses `reconcile --all` into one argv → "unknown
subcommand" — spike-verified.)

- [ ] **Step 3: Create the catch-all `commands/run.md`**

````markdown
---
description: Run any work-plan subcommand (slot, close, reconcile, group, init-repo, refresh-md, …).
argument-hint: "<subcommand> [args]"
---

```bash
work-plan $ARGUMENTS
```

Relay the output verbatim.
````

- [ ] **Step 4: Manual sanity check** (the wrapper is on PATH after install; here, call it directly)

Run: `./bin/work-plan --help | head -3`
Expected: the CLI help prints (resolves self-relative).

- [ ] **Step 5: Commit**

```bash
git add commands/
git commit -m "feat(commands): namespaced suite (brief/handoff/orient/hygiene/status + run) over bin wrapper"
```

---

### Task 5: `install.sh` copies only the dispatcher + delegates seeding

**Files:** Modify `install.sh`

- [ ] **Step 1: Restrict the command copy to the dispatcher**

In `install.sh`, the command-copy step (around the `cmd_src`/`cmd_dst` block) must copy **only**
`commands/work-plan.md` (it already does — confirm it does NOT glob `commands/*.md`). Add a comment:

```bash
# Standalone install copies ONLY the dispatcher command. The per-verb suite
# (brief.md, handoff.md, …) is plugin-only — copying them here would create bare
# /brief, /handoff that pollute the global command namespace.
```

- [ ] **Step 2: Install the `bin/work-plan` wrapper onto PATH-or-known-location**

After copying the skill, copy the wrapper next to the skill so its self-relative resolution works,
and (best-effort) link it onto the user's PATH:

```bash
cp "${TOOLKIT_DIR}/bin/work-plan" "${SKILLS_DIR}/work-plan/.." 2>/dev/null || true
install -m 0755 "${TOOLKIT_DIR}/bin/work-plan" "${BASE_DIR}/bin/work-plan" 2>/dev/null \
  || { mkdir -p "${BASE_DIR}/bin"; install -m 0755 "${TOOLKIT_DIR}/bin/work-plan" "${BASE_DIR}/bin/work-plan"; }
ok "installed bin/work-plan wrapper"
```

(The wrapper resolves the CLI via `~/.claude`/`~/.agents` fallbacks regardless, so PATH linking is a
convenience, not a requirement.)

- [ ] **Step 3: Replace the inline config seed with CLI delegation**

Replace the heredoc seed block with a call that triggers `load_config()` (which now seeds):

```bash
# Seed config via the CLI (single source of seed content; see lib/config.py).
if [ -f "${HOME}/.claude/work-plan/config.yml" ]; then
    ok "config already exists (${HOME}/.claude/work-plan/config.yml)"
else
    python3 "${SKILLS_DIR}/work-plan/work_plan.py" list >/dev/null 2>&1 || true
    ok "config seeded at ${HOME}/.claude/work-plan/config.yml"
fi
```

Note: config home is **always `~/.claude/work-plan/`**, even for `--target=~/.agents` (the CLI reads
only that path). Remove any `--target`-derived `CONFIG_DIR` seeding.

- [ ] **Step 4: Verify install.sh into a throwaway target**

Run: `./install.sh --target="$(mktemp -d)/.claude"`
Expected: copies skill + only `work-plan.md` command + the wrapper; prints the seed line; smoke test passes.

- [ ] **Step 5: Commit**

```bash
git add install.sh
git commit -m "refactor(install.sh): dispatcher-only command, install bin wrapper, one config home, delegate seed"
```

---

### Task 6: SKILL.md path-doc edit

**Files:** Modify `skills/work-plan/SKILL.md` (~lines 35–37)

- [ ] **Step 1: Replace the three hardcoded run lines with the wrapper convention**

```
Run the CLI via the `work-plan` wrapper (plugin `bin/`, also installed by install.sh):
`work-plan <subcommand>`. It resolves `work_plan.py` relative to itself, then falls back to
`${CLAUDE_PLUGIN_ROOT}`, `~/.claude`, `~/.agents`. Direct/dev use:
`python3 <toolkit>/skills/work-plan/work_plan.py <subcommand>`.
```

- [ ] **Step 2: Commit**

```bash
git add skills/work-plan/SKILL.md
git commit -m "docs(skill): document the work-plan wrapper as the CLI entry point"
```

---

### Task 7: Open the toolkit PR, merge, tag a release

- [ ] **Step 1: Push + PR**

```bash
git push -u origin feat/org-sharing-plugin-packaging
gh pr create --base dev --title "feat: package as Claude + Codex plugins (bin wrapper, command suite, marketplace)" \
  --body "Implements docs/superpowers/specs/2026-06-05-org-sharing-plugin-packaging-design.md (rev). Marketplace repo + tag follow in Task 8/9."
```

- [ ] **Step 2: After review + squash-merge to `dev`, deploy `dev`→`main`** (per the repo's deploy flow), so the manifests + `bin/` are on `main`.

- [ ] **Step 3: Tag a release on `main`**

```bash
git checkout main && git pull
TAG="v$(cat VERSION | tr '+' '-')"   # e.g. v2026.06.06-7909ca5
git tag "$TAG" && git push origin "$TAG"
echo "$TAG"
```

Record `$TAG` for the marketplace `ref` in Task 8.

---

### Task 8: Stand up the marketplace (separate repo, tag-pinned)

> Runs **after** Task 7 so `main`/the tag already contains the manifests — fixes the review's
> circular-verification finding.

- [ ] **Step 1: Create the single shared index**

```bash
mkdir -p /tmp/agent-plugins/.claude-plugin
TAG="<paste tag from Task 7>"
cat > /tmp/agent-plugins/.claude-plugin/marketplace.json <<JSON
{
  "name": "stylus-nexus",
  "owner": { "name": "Stylus Nexus" },
  "plugins": [
    { "name": "work-plan",
      "source": { "source": "github", "repo": "stylusnexus/work-plan-toolkit", "ref": "${TAG}" },
      "description": "Track-aware daily planning over GitHub issues, plus plan-status doc/plan liveness." }
  ]
}
JSON
python3 -c "import json;json.load(open('/tmp/agent-plugins/.claude-plugin/marketplace.json'));print('ok')"
```

- [ ] **Step 2: README + create + push**

```bash
cat > /tmp/agent-plugins/README.md <<'MD'
# Stylus Nexus — Agent Plugins Marketplace
Plugins for Claude Code + Codex.
## Claude Code
/plugin marketplace add stylusnexus/agent-plugins
/plugin install work-plan@stylus-nexus
## Codex
codex plugin marketplace add stylusnexus/agent-plugins   # then install work-plan from /plugins
MD
cd /tmp/agent-plugins && git init -q && git add -A && git commit -q -m "feat: work-plan marketplace (tag-pinned)"
gh repo create stylusnexus/agent-plugins --public --source=. --remote=origin --push
```

---

### Task 9: Phase-1 verification (Claude) — after publish

- [ ] **Step 1:** `/plugin marketplace add stylusnexus/agent-plugins` then `/plugin install work-plan@stylus-nexus`.
- [ ] **Step 2:** Run `/work-plan:brief` (or `/work-plan:run --help`) → CLI resolves via `bin/`, output renders.
- [ ] **Step 3 (config seed, done right):** from a clean `$HOME` (or after moving `~/.claude/work-plan/config.yml` aside), run a **config-dependent** command (`/work-plan:run list`); confirm `~/.claude/work-plan/config.yml` is created. (Do NOT rely on `--version`/`--help` — they return before `load_config`.)
- [ ] **Step 4 (update):** cut a second tag, bump the marketplace `ref`, run `/plugin update work-plan@stylus-nexus`, confirm `/work-plan:run --version` reports the new CalVer. Record evidence in the PR.

---

## Phase 2 — Codex plugin

### Task 10: Codex manifest + validity test

**Files:** Create `.codex-plugin/plugin.json`; Modify `skills/work-plan/tests/test_plugin_manifests.py`

- [ ] **Step 1: Extend the test (failing)**

```python
class CodexManifestTest(unittest.TestCase):
    def test_required_fields(self):
        m = _load(".codex-plugin/plugin.json")
        self.assertEqual(m["name"], "work-plan")
        self.assertTrue(m["description"])

    def test_versions_match(self):
        self.assertEqual(_load(".claude-plugin/plugin.json")["version"],
                         _load(".codex-plugin/plugin.json")["version"])
```

- [ ] **Step 2: Run — verify fail.** `cd skills/work-plan && python3 -m unittest tests.test_plugin_manifests -v`

- [ ] **Step 3: Create `.codex-plugin/plugin.json`** (same CalVer string as the Claude manifest)

```json
{
  "name": "work-plan",
  "version": "PASTE_SAME_VERSION_STRING",
  "description": "Track-aware daily planning over GitHub issues, plus plan-status doc/plan liveness. Pure-stdlib CLI-backed skill.",
  "author": { "name": "Stylus Nexus", "email": "evemcgivern@gmail.com" },
  "homepage": "https://github.com/stylusnexus/work-plan-toolkit",
  "repository": "https://github.com/stylusnexus/work-plan-toolkit",
  "license": "MIT",
  "keywords": ["planning", "github-issues", "work-plan", "productivity", "agent-skill"],
  "interface": { "displayName": "Work Plan", "shortDescription": "Track-aware daily planning over GitHub issues.", "category": "productivity" }
}
```

- [ ] **Step 4: Run — verify pass.** Then commit:

```bash
git add .codex-plugin/plugin.json skills/work-plan/tests/test_plugin_manifests.py
git commit -m "feat(plugin): add Codex plugin manifest"
```

---

### Task 11: Codex verification (the genuinely-unverified runtime path)

> No code by default; this task **confirms or falls back**. Record findings in the PR.

- [ ] **Step 1:** `codex plugin marketplace add stylusnexus/agent-plugins`; confirm Codex reads the
  legacy `.claude-plugin/marketplace.json` (else add a native `.agents/plugins/marketplace.json`
  with the Codex schema: `source: url`/`git-subdir` + `policy.installation`/`policy.authentication`
  + `category`).
- [ ] **Step 2:** Install **work-plan** via `/plugins`; determine the actual invocation (`@work-plan`,
  `/skills`, etc.) and whether `bin/work-plan` is on PATH. If `bin/` is honored, the wrapper resolves
  the CLI; if not, document the working `python3 <path>` form and adjust the skill/command wrappers.
- [ ] **Step 3:** Verify a config-dependent command seeds `~/.claude/work-plan/config.yml`, and that
  install + a second-tag update both work. Exit: Codex install + update verified, invocation documented.

---

## Phase 3 — Versioning, docs, lockstep

### Task 12: `version-bump.yml` writes CalVer into the manifests

**Files:** Modify `.github/workflows/version-bump.yml`

- [ ] **Step 1: After the existing "Compute and write VERSION" step, sync the manifests**

Add a step (keep the CalVer compute exactly as-is):

```yaml
      - name: Sync CalVer into plugin manifests
        env: { NEW_VERSION: ${{ steps.compute.outputs.new_version }} }
        run: |
          python3 - "$NEW_VERSION" <<'PY'
          import json, sys
          new = sys.argv[1]
          for path in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
              with open(path) as f: data = json.load(f)
              data["version"] = new
              with open(path, "w") as f: json.dump(data, f, indent=2); f.write("\n")
          PY
```

- [ ] **Step 2: Stage the manifests in the commit step**

In the `Commit and push` step, add the manifests to the diff-guard and `git add`:

```bash
          if git diff --quiet VERSION CHANGELOG.md .claude-plugin/plugin.json .codex-plugin/plugin.json; then
            echo "Nothing to commit."; exit 0; fi
          ...
          git add VERSION CHANGELOG.md .claude-plugin/plugin.json .codex-plugin/plugin.json
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/version-bump.yml
git commit -m "ci(version-bump): write CalVer into both plugin manifests on deploy"
```

---

### Task 13: `install.ps1` lockstep + uninstall lockstep

**Files:** Modify `install.ps1` (and `uninstall.sh`/`uninstall.ps1` if they reference the seed/command)

- [ ] **Step 1: Mirror Task 5 in PowerShell exactly** — copy only `commands/work-plan.md`; install the
  `bin/work-plan` wrapper; seed via the **same** CLI call shape (a config-dependent command), one
  config home `~/.claude/work-plan/`. The shell and PowerShell seed behavior must be **identical**
  (both trigger `load_config`), per `AGENTS.md` lockstep.

```powershell
& python3 "$SkillsDir/work-plan/work_plan.py" list *> $null
Ok "config seeded at $HOME/.claude/work-plan/config.yml"
```

- [ ] **Step 2: Commit**

```bash
git add install.ps1 uninstall.sh uninstall.ps1
git commit -m "refactor(install.ps1): lockstep with install.sh (dispatcher-only, bin wrapper, one config home)"
```

---

### Task 14: README — three paths, namespaced names, CalVer

**Files:** Modify `README.md`

- [ ] **Step 1: Add/replace the Install section**

````markdown
## Install

### Claude Code (recommended) — plugin, easy updates
```
/plugin marketplace add stylusnexus/agent-plugins
/plugin install work-plan@stylus-nexus
```
Commands appear namespaced: `/work-plan:brief`, `/work-plan:handoff`, `/work-plan:orient`,
`/work-plan:hygiene`, `/work-plan:status`, and `/work-plan:run <subcommand>` for the rest.
Update with `/plugin update work-plan@stylus-nexus`. Works in the CLI and the VS Code / JetBrains extensions.

### Codex — plugin
```
codex plugin marketplace add stylusnexus/agent-plugins
```
Then install **work-plan** from `/plugins`.

### Cursor / direct / other — script
```
git clone https://github.com/stylusnexus/work-plan-toolkit
cd work-plan-toolkit && ./install.sh
```
Gives the single `/work-plan <subcommand>`. Re-run `./install.sh` after `git pull` to refresh.
````

- [ ] **Step 2: Fix the version section** — ensure README still describes **CalVer** (no semver edits).
  Confirm: `grep -n -i "semver\|semantic version" README.md` returns nothing new.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): three install paths, namespaced command names, CalVer"
```

---

### Task 15: Refresh live skill, full suite

- [ ] **Step 1:** `./install.sh` → smoke test passes.
- [ ] **Step 2:** `cd skills/work-plan && python3 -m unittest discover tests` → OK.
- [ ] **Step 3:** `python3 tests/test_bin_wrapper.py` → OK.
- [ ] **Step 4:** Record Phase-1/2 install+update evidence (Tasks 9, 11) in the PR before final merge.

---

## Self-Review

**Spec coverage:** bin wrapper → T2; manifests → T3/T10; config one-home + self-seed → T1/T5/T13;
command suite + dispatcher-only install → T4/T5; marketplace one-index tag-pinned → T8; CalVer sync
→ T12; docs/lockstep → T6/T13/T14; non-circular verification → T7→T8→T9; Codex unverified-path →
T11. The spec's "plan-status doesn't commit" correction is a spec/spec-#2 concern, not a code task here.

**Review-finding closure:** circular verification → T7/T8 ordering; first-run seed proven via
config-dependent command → T1/T9 Step 3; installer lockstep → T5/T13 identical seed; config
`~/.claude` vs `~/.agents` → T5 one-home; `$ARGUMENTS` quoting + empty→`--help` → T4; semver/CalVer
→ kept CalVer (T3/T12); README CalVer consistency → T14 Step 2; namespaced names → T4/T14.

**Placeholder scan:** the two `PASTE_..._VERSION_STRING` tokens are explicit instructions (run
`cat VERSION`), not vague placeholders. No "TBD/TODO".

**Type/name consistency:** `ensure_config(path, notes_root)` defined T1, used T5/T13. `work-plan`
wrapper name consistent across T2/T4/T5/T6/T13. Manifest `version` == `VERSION` asserted T3, synced T12.

**Residual risk:** Codex runtime path/invocation (T11) is the one unverified area; isolated to the
`bin/` wrapper + an explicit confirm-or-fallback task, not assumed.
