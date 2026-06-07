# Org Sharing — Plugin Packaging & Marketplace Distribution

> **For agentic workers:** This is a design spec (the *why* and *what*), not an implementation
> plan. The bite-sized *how* gets written next via the writing-plans skill into
> `docs/superpowers/plans/`. This is the **first of two** org-sharing specs. This one covers
> *tool-sharing* (everyone runs the same skill version). The sibling spec covers *data-sharing*
> (everyone sees the same plans/tracks via a per-repo committed `.work-plan/` convention) and is a
> declared non-goal here.

**Date:** 2026-06-05
**Status:** Revised after Codex spec-review (2026-06-05) — awaiting re-review
**Owner:** Eve McGivern (Stylus Nexus)
**Feature home:** `work-plan-toolkit` (repo root) + a new public marketplace repo `stylusnexus/agent-plugins`

---

## Revision note (what changed after the second-model review + verification spike)

A Codex spec-review (two rounds) returned DO NOT SHIP and was largely right. Primary-doc
verification corrected several claims, and a **hands-on verification spike** (2026-06-05, against the
real `claude`/`codex` CLIs) then settled the externals. **Spike results, all confirmed in our favor:**
CalVer **passes `claude plugin validate --strict`**; the **`bin/` wrapper resolves** with the `../`
fix; a **single `.claude-plugin/marketplace.json` installs end-to-end on BOTH Claude and Codex**;
the **command suite namespaces** (`/work-plan:brief`); and the dispatcher/skill **name collision is
real** (fix: exclude `commands/work-plan.md` from the plugin). This revision bakes all of it in:

- **`bin/` wrapper replaces the env-var path probe.** Claude plugins auto-add a plugin's `bin/`
  to PATH; a `bin/work-plan` wrapper resolves the CLI relative to *itself*, which is robust where
  `${CLAUDE_PLUGIN_ROOT}`-in-command-markdown was unverified.
- **Command names are namespaced.** Claude plugin skills/commands are *always* `/plugin:name`
  ([docs](https://code.claude.com/docs/en/plugins)). We turn that into a feature: a namespaced
  **command suite** (`/work-plan:brief`, `:handoff`, …) for the plugin; `install.sh` keeps the
  single bare `/work-plan`.
- **Versioning stays CalVer.** "Codex requires semver" was *unproven*; Claude treats `version` as
  a free string (omit it and the commit SHA is used, so every commit is a new version). The
  semver migration is dropped.
- **One marketplace index, not two** (spike-verified). Codex installed from the same
  `.claude-plugin/marketplace.json` Claude uses; the "fallback second index" is dropped.
- **`bin/` `../` fix + unquoted `$ARGUMENTS` + collision exclusion** (round-2 review + spike): resolve
  from the wrapper's parent; leave `$ARGUMENTS` unquoted (quoting breaks `reconcile --all`); never
  ship `commands/work-plan.md` in the plugin.
- **"travels via git pull" was overstated.** `plan-status` writes files / `git mv`; it does **not**
  commit or push (verified: no commit/push in `plan_status.py` or `lib/git_state.py`). The user
  commits. Corrected throughout (and in spec #2).
- **Surface + drift claims narrowed.** Plugins target terminal + IDE extensions (not web /
  desktop-remote, which lack user plugins and `gh`); updates are explicit/version-gated
  (`/plugin update`), not silent — so this is "easy updates," not "no drift."

---

## Plain-English summary (read this even if you never read code)

Spec-in-one-line: make `/work-plan` installable and updatable like a real plugin, instead of a
clone-and-run script that silently goes stale.

Today a developer clones this repo and runs `./install.sh`, which copies the files into their
`~/.claude/`. It works once; there's no update button, so across people (or across your own
machines) versions drift with no signal. The fix is to publish the toolkit as a **plugin** listed
in a small **public marketplace**: add the marketplace once, install once, and `/plugin update`
pulls the latest after that. `install.sh` stays for tools without a plugin system (Cursor, plain
terminal use).

Both Claude Code and Codex have plugin systems. They're *separate* (different manifests), but they
share the same underlying skill files and Python CLI, and — usefully — Codex can read Claude's
marketplace index, so one index file serves both. The real work isn't "packaging"; it's making
*one* set of files behave correctly across the plugin world *and* the old installer world: how the
command finds the CLI, where config is created, and the command names users actually type.

---

## Problem statement

`install.sh` is a **point-in-time copy** with no update channel ("re-run after `git pull`" —
which nobody does reliably). For an org, that means silent version skew with no surfaced signal.

### What the prior `plan-status` spec assumed (and where it was optimistic)

The `plan-status` spec (2026-05-30) claimed packaging would be *"no file moves and no rework — just
add `.claude-plugin/plugin.json`."* **No files move** holds. **No rework** does not: the slash
command and `SKILL.md` hardcode `~/.claude/skills/work-plan/work_plan.py`, but a plugin installs to
a **versioned cache** (`~/.claude/plugins/cache/…`), so that path resolves to nothing. Path
resolution, config seeding, command namespacing, and a marketplace are the (modest, real) work.

### Distribution facts established + verified (cited)

- **Claude plugins** work across terminal and the **VS Code / JetBrains extensions** (plugin config
  shared with the CLI). Skills/commands are **always namespaced** `/<plugin>:<name>`; `version` is
  optional (omitted → commit SHA, every commit a new version). `bin/` is auto-added to PATH while a
  plugin is enabled. ([create plugins](https://code.claude.com/docs/en/plugins),
  [reference](https://code.claude.com/docs/en/plugins-reference))
- **Codex** has its own plugin system (`.codex-plugin/plugin.json`), consumes `SKILL.md`, and reads
  marketplace indexes from **both** `.agents/plugins/marketplace.json` and a **legacy-compatible
  `.claude-plugin/marketplace.json`**. ([codex/plugins/build](https://developers.openai.com/codex/plugins/build))
- **`SKILL.md`** is an open standard both hosts consume — the portable layer.
- **`plan-status` does not commit/push** (verified in code) — files travel only after the user commits.
- **Unverified / must-confirm in implementation:** whether `${CLAUDE_PLUGIN_ROOT}`/`PLUGIN_ROOT`
  are available to *command/skill* runtime under Codex (documented for hook processes), and whether
  Codex honors a Claude-style plugin `bin/`. The `bin/` wrapper's *self-relative* resolution is
  designed to not depend on either.

---

## Goals

1. A Claude Code user installs + updates via `/plugin install` / `/plugin update` — no clone.
2. A Codex user installs + updates via Codex's plugin mechanism — no clone.
3. **One** set of skill files + **one** `work_plan.py` serve both plugins and `install.sh`.
4. The command finds the CLI in every mode (Claude plugin cache, Codex plugin, `install.sh`→`~/.claude`,
   `install.sh`→`~/.agents`) — via a self-locating `bin/work-plan` wrapper, not a hardcoded path.
5. Config seeds automatically on first run (no install hook exists in either plugin system), at a
   single, documented, install-mode-independent location.
6. One version string (CalVer, the existing scheme), written into the manifest(s) by CI.
7. A single public marketplace repo (`stylusnexus/agent-plugins`) that serves both hosts and scales
   to future Stylus Nexus plugins.
8. Under the plugin, a discoverable **namespaced command suite**; under `install.sh`, the existing
   single `/work-plan`.

## Non-goals

- **Data-sharing / per-repo `.work-plan/`** — spec #2.
- **Publishing to the official Codex Plugin Directory** — self-serve is "coming soon"; we use the
  repo marketplace path that works today.
- **Deprecating `install.sh`** — kept for Cursor / plain-CLI / direct users.
- **Changing any `work-plan` subcommand's behavior.** Packaging + command surface only.
- **Web / desktop-remote support.** Out of scope (no user plugins / no `gh` there).

---

## Design

### Repo shape

Add, at the repo root (move nothing existing):

```
work-plan-toolkit/
├── .claude-plugin/plugin.json     ← NEW Claude manifest (name, version=CalVer, desc, meta)
├── .codex-plugin/plugin.json      ← NEW Codex manifest (same body + interface block)
├── bin/work-plan                  ← NEW self-locating wrapper → python3 <resolved>/work_plan.py
├── commands/                      ← suite of thin wrappers (plugin) + the single dispatcher
│   ├── work-plan.md               ← existing dispatcher (the ONLY file install.sh copies)
│   ├── brief.md  handoff.md  orient.md  hygiene.md  status.md   ← NEW (plugin suite)
│   └── run.md                     ← NEW catch-all → work-plan <subcommand ...>
├── skills/work-plan/…             ← unchanged CLI + SKILL.md (path-doc edit only)
├── install.sh / install.ps1       ← copy ONLY commands/work-plan.md; delegate config seed
└── VERSION                        ← unchanged CalVer
```

### CLI resolution — a self-locating `bin/` wrapper

Ship `bin/work-plan` (bash). It resolves `work_plan.py` **relative to its own location** first,
then falls back to known install paths, and never depends on an env var being present:

```sh
#!/usr/bin/env bash
# Resolve work_plan.py relative to this wrapper's PARENT (the plugin root, since
# the wrapper lives at <root>/bin/work-plan), then fall back to install paths.
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

> **`../` is load-bearing** (spike-verified). The wrapper is at `<root>/bin/work-plan`, so it must
> resolve from `dirname/..`, not `dirname` — `$here/skills/...` would be `<root>/bin/skills/...` and
> never exist. Verified working in both the Claude *and* Codex versioned caches (same layout).

- **Claude plugin / Codex plugin:** both unpack to `<cache>/<version>/{skills,bin}`; the wrapper's
  `../` resolves the bundled CLI. (Verified: `codex plugin add` installs `skills/` + `bin/` into its
  cache; the Claude install resolves via `bin/` on PATH.)
- **`install.sh`:** the wrapper is copied to a known location; self-relative or the
  `~/.claude`/`~/.agents` fallbacks resolve.
- **Windows:** the bash wrapper does not run natively. `install.ps1` ships a `.cmd`/`.ps1` shim (or
  the command files call `python3 <resolved>` directly) — see the plan's Windows task.

Command/skill files invoke `work-plan <args>` (on PATH) rather than a hardcoded python path.

### Command surface — namespaced suite (plugin) + single dispatcher (install.sh)

Plugin skills/commands are always namespaced `/<plugin>:<name>`. We use that for a discoverable
**plan-management suite**, each a thin wrapper calling `work-plan <subcommand> $ARGUMENTS`:

- `/work-plan:brief` · `/work-plan:handoff` · `/work-plan:orient` · `/work-plan:hygiene` ·
  `/work-plan:status` (→ `plan-status`)
- `/work-plan:run <subcommand …>` — catch-all for the long tail (`slot`, `close`, `reconcile`,
  `group`, `suggest-priorities`, `init-repo`, `refresh-md`, `duplicates`, `canonicalize`, `list`).
- The model-invoked `SKILL.md` provides the `work-plan` skill for natural-language entry.

**Collision fix (spike-verified).** The plugin must **NOT** ship `commands/work-plan.md`: a
`work-plan` command *and* the `work-plan` skill both register as the name `work-plan`, and the spike
confirmed it — `claude plugin details` listed `work-plan` **twice** in the inventory. So
`commands/work-plan.md` is excluded from the plugin (via the manifest's `commands` allowlist, or by
not placing it where the plugin discovers it) and exists **only** for `install.sh` standalone, where
there is no namespace and it provides the bare `/work-plan` dispatcher. Standalone install therefore
copies **only** `commands/work-plan.md` — never the per-verb suite, which would pollute the global
namespace with bare `/brief`, `/handoff`.

Argument handling (corrected after the second review round): **leave `$ARGUMENTS` UNQUOTED** —
bash re-parses the substituted text and honors the user's own inline quotes, so `reconcile --all`
splits into argv correctly while a user-quoted `--milestone='v1 — Launch'` stays intact. (Quoting the
whole placeholder collapses `reconcile --all` into one argv element → "unknown subcommand" — verified.)
The dispatcher special-cases **empty args → `--help`** (the CLI exits 2 on no args).

### Config seeding — lazy, single-sourced, install-mode-independent

No plugin system runs an install hook, and neither can write to `$HOME` at install time. The CLI
self-seeds on first run:

- `lib/config.py` gains `ensure_config()` — the **single source** of the seed content — called by
  `load_config()` when the file is absent. It writes an **absolute** `notes_root`
  (`Path.home()/".claude"/"work-plan"/"notes"`, expanded — **not** a literal `~`, which
  `tracks.py` does not `expanduser`) outside any plugin cache, and creates that dir. (`tracks.py`
  also gains a defensive `expanduser()` so a hand-edited `~` config still works.)
- **Config location is fixed at `~/.claude/work-plan/config.yml`** for all hosts (the CLI already
  reads only that path). The review flagged that `install.sh --target=~/.agents` currently seeds a
  *different* `~/.agents/work-plan/config.yml` the CLI never reads — a pre-existing latent bug. This
  spec resolves it explicitly: **there is one config home, `~/.claude/work-plan/`, regardless of
  skill install location**; `install.sh` stops seeding `~/.agents/work-plan/` and lets the CLI seed
  the canonical path. (Acceptance: a `--target=~/.agents` install reads/writes the same config a
  default install does.)
- `install.sh` / `install.ps1` drop their inline seed heredocs and run the **same** CLI seed step
  (identical behavior, lockstep) — fixing the review's "sh uses `--version` (no seed) / ps1 uses
  `list` (seeds)" divergence: both call a command that triggers `load_config()`.

### Versioning — CalVer, written into the manifest by CI (spike-verified)

Keep the existing CalVer `VERSION` (`<date>+<sha>`, auto-bumped on each deploy by
`version-bump.yml`). **Spike-verified:** the current CalVer `2026.06.06+7909ca5` **passes
`claude plugin validate --strict` (exit 0)** and **Codex installs it as-is** (shown as the installed
version), so the earlier "Codex requires semver / leading zeros fail strict" concern is refuted.
`version-bump.yml` gains one step: after writing `VERSION`, copy the same string into
`.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` and stage them **in the bump commit**.
`--version` keeps working via the upward-walk (`_load_version` finds root `VERSION` inside the cache —
verified live). **CI gate:** `claude plugin validate --strict <plugin>` runs on every PR.

### Marketplace — one shared index (spike-verified for BOTH hosts)

New **public** repo `stylusnexus/agent-plugins` with **two index files** — one per host:

```
agent-plugins/
├── .claude-plugin/marketplace.json    ← Claude  (source: github, repo)
└── .agents/plugins/marketplace.json   ← Codex   (source: url + policy + category)
```

```json
// .claude-plugin/marketplace.json (Claude)
{ "name": "stylus-nexus", "owner": { "name": "Stylus Nexus" },
  "description": "Stylus Nexus plugins for Claude Code + Codex.",
  "plugins": [ { "name": "work-plan",
    "source": { "source": "github", "repo": "stylusnexus/work-plan-toolkit", "ref": "<tag>" },
    "description": "…" } ] }

// .agents/plugins/marketplace.json (Codex)
{ "name": "stylus-nexus", "owner": { "name": "Stylus Nexus" },
  "description": "Stylus Nexus plugins for Claude Code + Codex.",
  "plugins": [ { "name": "work-plan",
    "source": { "source": "url", "url": "https://github.com/stylusnexus/work-plan-toolkit.git", "ref": "<tag>" },
    "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
    "category": "Productivity", "description": "…" } ] }
```

**CORRECTION (verified at publish, 2026-06-07):** the earlier "one index serves both hosts" claim is
**FALSE for a published (git) source.** Codex reads the `.claude-plugin/marketplace.json` *location*
legacy-compatibly, but **cannot parse Claude's `{source: github, repo}` plugin-source** — `codex
plugin list` showed nothing and `codex plugin add` returned "plugin not found." Codex needs its **own**
`.agents/plugins/marketplace.json` with its native schema (`source: url`/`git-subdir` + `policy` +
`category`). The spike's "Codex installed from one index" used a *relative-path local* source, which
Codex *does* parse — masking the github-source gap. With both index files present and pinned to the
same tag, **both hosts install end-to-end** (verified: Claude `/plugin update` → `2026.06.07+46f9db9`;
`codex plugin add work-plan@stylus-nexus` → `2026.06.07+46f9db9`). The `description` field is required
on the Claude index to avoid a validate warning.

**Rollback / mutable-`main` safety:** the marketplace pins a **release tag** (`ref: <tag>`), not bare
`main`, so a bad commit on `main` does not auto-ship. **Release ordering (review fix):** merge to
`main` → wait for `version-bump.yml`'s bump commit (which now also syncs the manifests) → **tag that
bump commit** → point the marketplace `ref` at the tag. Rollback = point `ref` at the prior tag.
`claude plugin tag` validates that `plugin.json` and the marketplace entry agree.

### Install flows (documented in README — corrected names)

- **Claude Code (recommended):** `/plugin marketplace add stylusnexus/agent-plugins` →
  `/plugin install work-plan@stylus-nexus` → commands appear as `/work-plan:brief`, `/work-plan:run`,
  etc.; update with `/plugin update work-plan@stylus-nexus`. Works in CLI + IDE extensions.
- **Codex:** `codex plugin marketplace add stylusnexus/agent-plugins`, then install **work-plan**
  via `/plugins`; skills are invoked per Codex's convention (`@`/`/skills`) — exact invocation
  confirmed in Phase 2.
- **Cursor / direct / other:** `git clone … && ./install.sh` → bare `/work-plan`. Re-run after pull.

---

## Phasing

**Phase 1 — Claude plugin, end to end (verified after publish).**
`.claude-plugin/plugin.json`; `bin/work-plan` wrapper; the namespaced command suite + `run` catch-all;
`install.sh` copies only the dispatcher; CLI self-seed (`ensure_config`); single config home;
`stylusnexus/agent-plugins` with the shared index pinned to a release tag. **Verification ordering
fix:** merge the manifests to `main` and cut the tag *first*, then install from the tagged ref and
confirm `/work-plan:brief` runs and config self-seeds (test a **config-dependent** command from a
clean `$HOME`, not `--version`). Exit: clean install + a second-tag update both verified.

**Phase 2 — Codex plugin.** `.codex-plugin/plugin.json` with `"skills": "./skills/"` (declare the
component path; don't rely on auto-discovery). Codex install from the shared index is **already
spike-verified**; this phase confirms the in-session **skill-invocation syntax** and whether `bin/`
is on Codex's PATH (the wrapper's `../` self-resolution works from the cache regardless; if `bin/`
isn't on PATH, command/skill content calls it via `${PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_ROOT}`). Exit:
Codex skill runs and a re-tag update is picked up.

**Phase 3 — Versioning + docs + lockstep.** `version-bump.yml` writes CalVer into the manifest(s);
README updated (three install paths, namespaced command names, **CalVer** — not semver); `install.ps1`
/`uninstall.*` follow the seed/copy changes in lockstep.

Each phase is a commit/PR boundary (code → feature branch → PR to `dev`; squash-merge). The deploy
PR `dev`→`main` is what triggers `version-bump.yml`. The marketplace repo has its own history.

---

## Test / verification cases (plain English)

**CLI resolution**
- `bin/work-plan` resolves the CLI from inside a plugin cache (self-relative), from `~/.claude`, and
  from `~/.agents`; with no candidate it prints a four-location error and exits 1.

**Command surface**
- Under the plugin, `/work-plan:brief` runs `work-plan brief`; `/work-plan:run reconcile --all`
  reaches the catch-all.
- `install.sh` installs only `/work-plan` (no bare `/brief` etc. appear).
- A multiword arg (`run group --milestone='v1 — Launch'`) is passed intact (UNQUOTED `$ARGUMENTS`,
  bash honors the user's inline quotes); a multi-flag arg (`run reconcile --all`) splits correctly;
  empty args → `--help`.
- The plugin inventory lists `work-plan` exactly **once** (no command/skill duplicate).

**Config seeding**
- First run with no `~/.claude/work-plan/config.yml` (clean `$HOME`) creates a valid file via a
  config-dependent command, then proceeds; second run is byte-identical.
- A `--target=~/.agents` install reads/writes the **same** `~/.claude/work-plan/config.yml`.
- The seed text exists in exactly one place (CLI), not duplicated in `install.sh`/`install.ps1`.

**Versioning**
- `--version` reports the CalVer string under a plugin install.
- A deploy bump writes the same CalVer into `VERSION` and the manifest(s).

**Marketplace / install / update**
- `marketplace add` → `install work-plan@stylus-nexus` → `/work-plan:brief` works (Claude, CLI + IDE).
- Cutting a new tag + bumping the marketplace `ref` makes `/plugin update` apply it.
- Rollback: pointing `ref` back at the prior tag is reflected on next update.
- Codex install via the same marketplace repo succeeds (Phase 2).

**Non-regression**
- `install.sh` users keep identical behavior + bare `/work-plan`; full offline `unittest` suite green.

---

## Risks & open questions

**Resolved by the 2026-06-05 spike** (was open): CalVer-strict validity ✅, `bin/` `../` resolution
✅, single-index install on Claude **and** Codex ✅, command-suite namespacing ✅, name-collision
reality ✅ (fix applied). These are no longer risks.

Remaining:
- **Codex in-session skill-invocation syntax** — install/layout/version all verified; the exact
  `@`/`/skills` invocation and whether `bin/` is on Codex's PATH are confirmed in Phase 2. Cosmetic:
  the wrapper resolves via `../` from the cache regardless, and `${PLUGIN_ROOT}` is a fallback.
- **Windows launcher** — the bash `bin/work-plan` doesn't run natively; `install.ps1` must ship a
  `.cmd`/`.ps1` shim (or command files call `python3` directly). Verify on the Windows CI matrix.
- **Tag-pinned marketplace cadence** — pinning to tags adds a "tag the bump commit + point ref" step;
  accepted for rollback safety. Document so releases don't stall.
- **`repo-activity-summary` rides along** — the plugin bundles the whole `skills/` dir, so the second
  skill installs too (seen in the spike inventory). Intended (it's a real toolkit skill); note it.
- **Namespaced names in muscle memory** — `/work-plan:brief` ≠ today's `/work-plan brief`. Documented;
  `install.sh` users keep the old form.

---

## Decisions locked (this session)

1. **Marketplace:** one public repo **`stylusnexus/agent-plugins`** with a **single**
   `.claude-plugin/marketplace.json` (Codex reads it legacy-compatible), pinned to a **release tag**.
2. **`install.sh`:** kept (dual-track), copies only the single dispatcher command.
3. **Codex packaging:** dual plugins (Claude + Codex manifests), one shared body + marketplace.
4. **Versioning:** **keep CalVer** (semver requirement was unproven); CI writes it into the manifest(s).
5. **CLI resolution:** self-locating **`bin/work-plan`** wrapper (not an env-var markdown probe).
6. **Command surface:** namespaced **suite** (`brief/handoff/orient/hygiene/status` + `run` catch-all)
   for the plugin; bare `/work-plan` for `install.sh`.
7. **Config:** one home `~/.claude/work-plan/config.yml` for all hosts; CLI self-seeds; installers delegate.
