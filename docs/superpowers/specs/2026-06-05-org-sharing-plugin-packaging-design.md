# Org Sharing — Plugin Packaging & Marketplace Distribution

> **For agentic workers:** This is a design spec (the *why* and *what*), not an implementation
> plan. The bite-sized *how* gets written next via the writing-plans skill into
> `docs/superpowers/plans/`. This is the **first of two** org-sharing specs. This one covers
> *tool-sharing* (everyone runs the same skill version). The sibling spec covers *data-sharing*
> (everyone sees the same plans/tracks via a shared/committed `notes_root` convention) and is a
> declared non-goal here.

**Date:** 2026-06-05
**Status:** Drafted — awaiting review
**Owner:** Eve McGivern (Stylus Nexus)
**Feature home:** `work-plan-toolkit` (repo root) + a new marketplace repo `stylusnexus/agent-plugins`

---

## Plain-English summary (read this even if you never read code)

Today, to use `/work-plan` a developer clones this repo and runs `./install.sh`, which copies
the skill files into their `~/.claude/` (or `~/.agents/` for Codex). It works once. The problem
is what happens *after*: when the repo changes, their copy doesn't. There's no "update" button —
they have to remember to `git pull` and re-run the installer. Across an org, everyone drifts to a
slightly different version, and nobody knows it.

The fix is to publish the toolkit the way modern agent tools expect: as a **plugin** listed in a
**marketplace**. A developer adds the marketplace once, runs one install command, and from then
on a single update command pulls the latest version. No clone, no script, no drift.

There's a wrinkle worth stating plainly, because an earlier assumption was too rosy. Both
Anthropic's **Claude Code** and OpenAI's **Codex** now have plugin systems — but they are
**separate**. A Claude marketplace listing is not readable by Codex's installer, and vice versa.
What they *do* share is the actual skill content: the `SKILL.md` file and our Python CLI are an
open, portable standard both tools understand. So the plan is: **two thin packaging wrappers
around one shared body of code.** We add a small manifest file for each tool, list the toolkit in
one marketplace repo that carries both tools' index files, and keep `install.sh` alive only for
the tools that have no plugin system (Cursor, plain terminal use).

The bulk of the work is not "packaging" — it's making *one* set of files work in *both* plugin
worlds *and* the old installer world at the same time: the file path the slash command uses to
find the CLI, where the config file gets created, and keeping one version number in sync across
three places.

---

## Problem statement

`install.sh` is a **point-in-time copy** with no update channel. The README tells users to
"re-run after `git pull` to refresh" — an instruction nobody follows reliably. The consequence
for an org is silent version skew: two developers on `/work-plan` may be running materially
different behavior, and there is no surfaced signal that they have drifted.

### What the prior spec assumed (and where it was optimistic)

The `plan-status` spec (2026-05-30, "Packaging as a plugin (deferred, no-rework)") claimed
packaging would require *"no file moves and no rework — just adding a `.claude-plugin/plugin.json`
wrapper."* The first half holds: **no files move.** The second half does not. The slash command
and `SKILL.md` **hardcode** `~/.claude/skills/work-plan/work_plan.py`. A plugin installs to a
**versioned cache** (`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`), not to
`~/.claude/skills/`, so that hardcoded path resolves to nothing under a plugin install. Fixing
path resolution, config seeding (no install hook exists), and versioning *is* the rework — modest,
but real.

### Distribution facts established during design (cited)

- **Claude Code plugins** work across every Claude Code surface — terminal, **VS Code and
  JetBrains IDE extensions** (plugin config is shared with the CLI), desktop, web.
  ([ide-integrations](https://code.claude.com/docs/en/ide-integrations.md), [plugins-reference](https://code.claude.com/docs/en/plugins-reference.md))
- **Codex** has its **own** plugin system + marketplace browser (`/plugins`, `codex plugin
  marketplace add owner/repo`) and consumes `SKILL.md` skills, installing to `~/.agents/skills`.
  ([codex/plugins](https://developers.openai.com/codex/plugins), [codex/skills](https://developers.openai.com/codex/skills), [codex/plugins/build](https://developers.openai.com/codex/plugins/build))
- **`SKILL.md` is an open standard** ("Agent Skills", agentskills.io) consumed by both tools —
  the portable layer. ([skills](https://code.claude.com/docs/en/skills.md))
- **The two plugin registries are NOT cross-compatible.** Codex's docs make no mention of
  `.claude-plugin` support; Anthropic's make no mention of Codex. Manifests live at distinct
  paths (`.claude-plugin/plugin.json` vs `.codex-plugin/plugin.json`).
- **The "ChatGPT in VS Code" extension (`openai.chatgpt`) is Codex.** ChatGPT-the-consumer-app
  (GPTs/connectors) is a separate ecosystem that does not install coding-agent skills.

---

## Goals

1. A Claude Code user installs and updates the toolkit with `/plugin install` + `/plugin update`
   — no clone, no `install.sh`.
2. A Codex user does the same via Codex's plugin mechanism.
3. **One** set of skill files and **one** `work_plan.py` serve both plugins and the legacy
   installer — no forks, no duplicated logic.
4. The slash command resolves the CLI path correctly in all install modes (Claude plugin, Codex
   plugin, `install.sh`→`~/.claude`, `install.sh`→`~/.agents`).
5. Config is seeded automatically on first run (no install hook exists in either plugin system).
6. One version number, synced by CI into every manifest that needs it.
7. A single marketplace repo (`stylusnexus/agent-plugins`) that scales to future Stylus Nexus
   plugins and carries both tools' index files.

## Non-goals

- **Data-sharing / shared `notes_root`** — the second org-sharing spec. `plan-status` already
  derives verdicts live from each repo's git and `--stamp`/`--archive` commit into the repo so
  they travel via `git pull`; the gap is the per-user `work-plan` track config. Out of scope here.
- **Publishing to the official Codex Plugin Directory** — self-serve publishing is "coming soon"
  per OpenAI docs. This spec uses the repo/team marketplace path that works today; the official
  directory is a later, no-rework follow-on.
- **Deprecating `install.sh`** — it stays for Cursor / plain-CLI / direct users.
- **Changing any `work-plan` subcommand behavior.** Packaging only.

---

## Design

### Repo shape: two manifests, one body

Add two files at the repo root; move nothing:

```
work-plan-toolkit/
├── .claude-plugin/plugin.json     ← NEW (Claude Code manifest)
├── .codex-plugin/plugin.json      ← NEW (Codex manifest)
├── commands/work-plan.md          ← edited (path resolution, §path)
├── skills/work-plan/SKILL.md      ← edited (path resolution docs)
├── skills/work-plan/work_plan.py  ← unchanged CLI substrate
├── VERSION                        ← role clarified (§version)
├── install.sh / install.ps1       ← retained, seed step delegates to CLI
└── …
```

Both manifests point at the same `commands/` and `skills/` (identical `skills/<name>/SKILL.md`
layout is what both tools expect). Distinct manifest directories (`.claude-plugin/` vs
`.codex-plugin/`) coexist without conflict. Each manifest carries `name`, `version` (semver,
see §version), `description`, `author`, `repository`, `license`. Codex requires all three of
name/version/description; Claude requires only `name`. We populate the full set in both.

### Path resolution — the core dual-track problem

The slash command must find `work_plan.py` regardless of how it was installed. A **candidate-path
probe** in the command's bash block, first existing wins:

```bash
for c in \
  "${CLAUDE_PLUGIN_ROOT:-}/skills/work-plan/work_plan.py" \
  "${PLUGIN_ROOT:-}/skills/work-plan/work_plan.py" \
  "$HOME/.claude/skills/work-plan/work_plan.py" \
  "$HOME/.agents/skills/work-plan/work_plan.py"; do
  if [ -n "$c" ] && [ -f "$c" ]; then WORK_PLAN="$c"; break; fi
done
python3 "$WORK_PLAN" $ARGUMENTS
```

This works because:
- **Claude plugin** sets `CLAUDE_PLUGIN_ROOT` (substituted inline in command content).
- **Codex plugin** sets `PLUGIN_ROOT` **and** `CLAUDE_PLUGIN_ROOT`/`CLAUDE_PLUGIN_DATA` for
  backward compatibility — so the first candidate already resolves under Codex too; `PLUGIN_ROOT`
  is a belt-and-suspenders fallback.
- **`install.sh`** copies into `~/.claude/skills/` or `~/.agents/skills/`; the unset env vars
  expand to a non-existent leading-slash path that fails `-f` and falls through.

`SKILL.md` documents the same resolution order in its "how to run the CLI" section (today it lists
three hardcoded paths; it gains the env-var-first forms).

### Config seeding — lazy, single-sourced

Neither plugin system runs an install script, and neither can write to the user's home dir at
install time. Config must be seeded **lazily by the CLI on first run.** Today `install.sh` writes
the two-line `~/.claude/work-plan/config.yml`. We move that seed content into `lib/config.py` as
the single source of truth:

- `load_config()` (or a new `ensure_config()` it calls) writes the default `config.yml` if the
  file is absent, then proceeds. The path stays `~/.claude/work-plan/config.yml` (its current
  `DEFAULT_CONFIG_PATH`).
- `install.sh` / `install.ps1` drop their inline heredoc seed and instead invoke the CLI's seed
  path (so first-run feels instant for installer users, with zero duplicated content).
- Config lives **outside** the plugin cache, so it survives `/plugin update` in both ecosystems.

One config location for every install mode; one place the seed text lives.

### Versioning — semver canonical

Codex **requires** semver (`"1.0.0"`); Claude **accepts** any string. The common denominator is
**semver**, derived from Conventional Commit types (`feat`→minor, `fix`→patch). `version-bump.yml`
writes the same semver into `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` on each
qualifying merge. Update detection in both tools is by version-string change, so a bump is what
tells installed copies an update exists.

**Open item (deferred to the implementation plan / spec #2):** the existing CalVer `VERSION`
(`2026.06.04+5d7962f`) that `--version` reports today. Options recorded, not decided here: replace
CalVer with semver everywhere; or keep CalVer for `--version`/build provenance alongside semver in
the manifests. The spec locks only the *requirement*: **manifests carry a valid semver synced by
CI.** `_load_version()`'s upward walk already finds `VERSION` inside the plugin cache, so
`--version` keeps working regardless of which option wins.

### Marketplaces — one repo, two index files

New **public** repo `stylusnexus/agent-plugins`, tool-neutral because it carries both indexes and
will hold future plugins:

```
agent-plugins/
├── .claude-plugin/marketplace.json   ← Claude index
└── .agents/plugins/marketplace.json  ← Codex index
```

Each lists the toolkit as an **external** plugin (the code stays in `work-plan-toolkit`):

```json
// .claude-plugin/marketplace.json
{
  "name": "stylus-nexus",
  "owner": { "name": "Stylus Nexus" },
  "plugins": [
    { "name": "work-plan",
      "source": { "source": "github", "repo": "stylusnexus/work-plan-toolkit", "ref": "main" },
      "description": "Track-aware daily planning over GitHub issues, plus plan-status doc liveness." }
  ]
}
```

The Codex index mirrors this in Codex's marketplace schema. `ref: main` tracks latest; the
per-manifest semver gates whether an installed copy sees an update.

### User-facing install flows (documented in README)

- **Claude Code:** `/plugin marketplace add stylusnexus/agent-plugins` → `/plugin install
  work-plan@stylus-nexus` → `/plugin update work-plan@stylus-nexus`. Works in CLI and IDE
  extensions identically.
- **Codex:** `codex plugin marketplace add stylusnexus/agent-plugins` → install via `/plugins`
  browser / CLI → update via Codex's update command. (Note the official-directory caveat.)
- **Cursor / direct / other:** clone + `./install.sh` (unchanged), or drop `SKILL.md` per the
  open Agent Skills standard.

### Architecture fit

No change to the CLI's dispatcher/`commands/`/`lib/` design. The plugin layer is *strictly*
additive: two manifests, one edited slash command, one edited `SKILL.md`, a relocated config seed,
and a CI step. The "CLI is the substrate, SKILL.md is the prompt layer" invariant is preserved;
plugins are just a fourth way to deliver the same substrate.

---

## Phasing

**Phase 1 — Claude plugin, end to end.** `.claude-plugin/plugin.json`; candidate-path probe in
`commands/work-plan.md` + `SKILL.md`; CLI self-seed config; stand up `stylusnexus/agent-plugins`
with the Claude index; verify install + update on a clean machine/profile. Exit: a Claude Code
user installs and updates with no clone.

**Phase 2 — Codex plugin.** `.codex-plugin/plugin.json`; Codex index file in the marketplace
repo; verify the same `work_plan.py` resolves under a Codex plugin install (via the shared
`CLAUDE_PLUGIN_ROOT` back-compat). Exit: a Codex user installs and updates with no clone.

**Phase 3 — Versioning + docs + lockstep.** Semver in both manifests; `version-bump.yml` syncs it;
README three-path install section; `install.ps1`/`uninstall.*` follow the config-seed move. Exit:
one merge bumps semver in both manifests; installer parity on Windows/macOS/Linux.

Each phase is a commit/PR boundary (code → feature branch → PR to `dev`, per repo convention).
The marketplace repo is its own repo with its own trivial history.

---

## Test / verification cases (plain English)

**Path resolution**
- Claude plugin install: `/work-plan --help` runs; the probe selects the `CLAUDE_PLUGIN_ROOT`
  candidate.
- Codex plugin install: `/work-plan --help` runs; resolves via the shared back-compat env var.
- `install.sh`→`~/.claude`: resolves the `~/.claude` candidate (env vars unset).
- `install.sh`→`~/.agents`: resolves the `~/.agents` candidate.
- No candidate exists → a clear error naming the four locations searched (not a silent failure).

**Config seeding**
- First run with no `~/.claude/work-plan/config.yml` creates a valid two-key file, then the
  command proceeds.
- Second run leaves the existing config byte-identical (no clobber).
- The seed text exists in exactly one place in the codebase (CLI), not duplicated in `install.sh`.

**Versioning**
- `--version` reports a value under a plugin install (upward walk finds `VERSION` in the cache).
- A `feat:`-typed merge bumps the minor; a `fix:` bumps the patch; both manifests carry the same
  semver after the bump workflow runs.

**Marketplace / install**
- `marketplace add` then `install` then `update` succeeds on Claude Code (CLI and IDE extension).
- The Codex index installs the same plugin via Codex's mechanism.
- A version bump on `main` makes `/plugin update` report and apply an update.

**Non-regression**
- Existing `install.sh` users see identical behavior (skills + command + config present; smoke
  test passes).
- No `work-plan` subcommand changes behavior; the full offline `unittest` suite stays green.

---

## Risks & open questions

- **CalVer ↔ semver reconciliation** — deferred (see §version). Risk: a half-migrated state where
  `--version` and the manifests disagree. Mitigation: implementation plan decides the CalVer fate
  before the CI sync ships.
- **Dual-manifest coexistence** — structurally fine (distinct paths) but not explicitly documented
  by either vendor. Mitigation: Phase-1/2 verification on real installs; low blast radius.
- **`${CLAUDE_PLUGIN_ROOT}` substitution in *command* markdown** — confirmed for skill/agent
  content and hooks; commands are markdown too, but if a surface ever fails to substitute, the
  probe's `~/.claude` fallback still catches plugin installs under the default profile. Verify on
  a real Claude plugin install in Phase 1.
- **Codex official-directory timing** — self-serve publishing "coming soon." We ship via repo
  marketplace now; the official listing is additive later.
- **Cache ephemerality** — plugin cache dirs are version-scoped and GC'd ~7 days after update.
  We never write state there (config lives in `~/.claude/work-plan/`), so this is informational.
- **Marketplace repo bootstrap** — `stylusnexus/agent-plugins` is a new public repo; creating it
  and its two index files is part of Phase 1, outside this code repo's history.

---

## Decisions locked (this session)

1. **Marketplace:** dedicated **public** repo, named **`stylusnexus/agent-plugins`**, carrying
   both Claude and Codex index files.
2. **`install.sh`:** kept (dual-track), narrowed to Cursor/direct now that both plugins are
   first-class.
3. **Codex packaging:** **dual plugins in this spec** — Claude *and* Codex, sharing one
   `SKILL.md` + CLI.
4. **Versioning:** **semver** in the manifests (Codex requirement); CalVer reconciliation is an
   explicit open item for the implementation plan / spec #2.
