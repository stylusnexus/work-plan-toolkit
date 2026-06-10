# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository. Its Codex-facing sibling is [`AGENTS.md`](./AGENTS.md) — keep cross-cutting guidance consistent between the two when you change either.

## What this repo is

`work-plan-toolkit` is itself a Claude Code skill (`/work-plan`). The repo contains the skill source; an installer copies it into `~/.claude/skills/` so the slash command works. **Editing files here does not affect the running `/work-plan` slash command** — you must re-run `./install.sh` to refresh `~/.claude/skills/work-plan/` (the installer drops a `.installed-from` marker and overwrites prior copies of the same toolkit safely).

## Common commands

```bash
# Install / refresh into ~/.claude/skills/ (run after every code change)
./install.sh                        # macOS / Linux / WSL
./install.sh --target=$HOME/.agents # Codex variant
.\install.ps1                       # Windows

# Run tests (no pytest, no pip — stdlib unittest)
cd skills/work-plan && python3 -m unittest discover tests

# Run a single test module / case
cd skills/work-plan && python3 -m unittest tests.test_handoff_set_next
cd skills/work-plan && python3 -m unittest tests.test_handoff_set_next.TestSetNext.test_persists_to_frontmatter

# Run the CLI directly (bypasses the install + slash command)
python3 skills/work-plan/work_plan.py --help
python3 skills/work-plan/work_plan.py brief
```

There is no build step, lint config, or CI — edit, test, commit.

## Architecture

**The CLI is the substrate; SKILL.md is the prompt-engineering on top.** `work_plan.py` is dispatcher-only — it maps subcommand names to modules in `commands/` (each exports `run(args: list[str]) -> int`). Adding a subcommand means: write `commands/<name>.py`, register it in BOTH the `SUBCOMMANDS` dict AND the `DESCRIPTIONS` list in `work_plan.py` (the help text is hand-written, not auto-generated).

**Layered design:**

- `commands/<name>.py` — one file per subcommand. Thin orchestration over `lib/`.
- `lib/` — shared helpers. Notable modules:
  - `config.py` — loads `~/.claude/work-plan/config.yml` by shelling out to `yq` (so YAML parsing stays stdlib-only).
  - `frontmatter.py` — `parse_file` / `write_file` for YAML-frontmattered markdown. Same `yq` shell-out trick.
  - `tracks.py` — `discover_tracks(cfg)` walks `notes_root/` and builds `Track` dataclasses. `find_track_by_name` is the canonical resolver.
  - `github_state.py` / `git_state.py` — wrappers over `gh` / `git` subprocess calls.
  - `status_table.py` — parses + edits the canonical issue table inside a track's markdown body.
  - `prompts.py` — `prompt_input`, `prompt_lines`, `prompt_yes_no`, `parse_flags` (use these; don't reinvent).

**Data model:** GitHub is canonical for issue state. Track markdown files are lightweight references — they list issue numbers in YAML frontmatter, and the CLI re-derives state live from `gh`/`git`/the markdown body on every invocation. The toolkit deliberately does NOT mirror or cache GitHub state.

**Two unusual patterns to know:**

1. **Verbatim relay** (`brief`, `handoff`, `orient`, `hygiene`): the Python output IS the deliverable. SKILL.md instructs the model to reproduce the full Python output verbatim in chat — users copy-paste from chat into other terminals.
2. **Two-step AI subcommands** (`group`, `suggest-priorities`, `auto-triage`): CLI fetches issues + prints a prompt → the LLM produces JSON and writes it via the Write tool to a per-user cache file under `~/.claude/work-plan/cache/` (mode `0700`; e.g. `auto_triage.answers.json`) → user re-runs with `--apply`. The CLI never calls an LLM directly.

## Hard constraints

- **Pure Python 3.9+ stdlib.** Do not add third-party packages. The "no `pip install` step" property is load-bearing for redistribution. PEP 585 generics (`list[dict]`) are fine; no 3.10+ features (no `match` statements).
- **`yq` means mikefarah/yq (Go), not kislyuk/yq (the Python jq wrapper).** They take incompatible flags. The installer verifies this.
- **`install.sh` ↔ `install.ps1` and `uninstall.sh` ↔ `uninstall.ps1` must stay in lockstep.** When you change one, change the other. Same for auto-detection logic and config seeding.
- **All external state goes through `gh` (not direct GitHub API).** Reuses the user's `gh auth`; we never read or store tokens.
- **Tests mock all `gh` / `git` subprocess calls** — they run offline. Don't add tests that hit the network.

## Files vs runtime locations

- `skills/work-plan/` (source) → `~/.claude/skills/work-plan/` (installed copy used by `/work-plan`)
- `skills/repo-activity-summary/` → `~/.claude/skills/repo-activity-summary/`
- `commands/work-plan.md` → `~/.claude/commands/work-plan.md` (the slash-command alias)
- `notes/` (default `notes_root` in seeded config) — empty until `init-repo` populates it

The active config the skill reads is `~/.claude/work-plan/config.yml`. There is no template file in the repo for it; `install.sh` writes the right two lines directly.

## Commit / PR conventions

Conventional Commits. PR titles become squash-merge commit messages. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`. Scope is encouraged when localized (`feat(orient): ...`, `fix(install.sh): ...`). See `CONTRIBUTING.md` and `.github/pull_request_template.md`.

## Keep docs in lockstep with changes

When a change warrants it, update the docs **in the same PR** as the code — don't defer:

- **README.md** (root) — when you add/rename/remove a subcommand or flag, or change user-visible behavior. The command tables (the `## Commands` reference and the quick-start table near the top) are hand-maintained; update both rows if the change touches a command listed in each.
- **vscode/README.md** — when the VS Code extension's surface changes (a new lens/sort/command, a new tree affordance, a confirm flow).
- **agent-plugins** ([stylusnexus/agent-plugins](https://github.com/stylusnexus/agent-plugins), cross-repo) — that README is a **catalog entry pinned to a release tag**, written at the "VS Code viewer + skills" altitude. Update it only when the *plugin's advertised surface* changes (a new/renamed `/work-plan:*` skill command, install/upgrade instructions, the one-line capability summary) — **not** for flag-level details, which live in this repo's README. Day-to-day `feat`/`fix` work does not touch it; a new top-level skill command or a release that changes the pitch does.
- **CHANGELOG.md** — **don't hand-edit** below the `<!-- new entries inserted below -->` marker. It's written by `.github/workflows/version-bump.yml` on the deploy PR merge to `main`, from that PR's title/body (see "Deploy & release" below). dev merges don't touch it; the production deploy does.

Rule of thumb: a `feat` that adds/changes a flag or command → README here (both tables). A new top-level skill command or a release that changes the plugin's pitch → also agent-plugins. Pure internal `refactor`/`test`/`chore` → usually no doc change.

## Deploy & release

**Do NOT use any globally-installed `/deploy` skill here — one may be present that targets a different project** (assuming a different git remote, a database-migration step, and release-please PR squashing — none of which exist in this repo). This repo's deploy is simpler and is documented below.

**The deploy is a `dev → main` merge.** Merging a deploy PR into `main` fires `.github/workflows/version-bump.yml`, which (on `pull_request: closed` + merged):
1. writes `VERSION` = `<UTC-date>+<short-sha>` (CalVer, e.g. `2026.06.10+a6052bf`),
2. syncs that CalVer into `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`,
3. **prepends a CHANGELOG.md entry from the deploy PR's title + body**, and
4. commits `chore(version): bump to <ver> [skip ci]` to `main`.

So **the deploy PR title/body IS the changelog entry** — write it as one (conventional-commit title like `feat: …`, body with the shipped changes). The title must be a real conventional type or version-bump still runs but the entry reads poorly.

### Deploy steps (run manually — no repo-local deploy skill)
1. Confirm `dev` CI is green and `git diff origin/main..dev` is non-empty.
2. `gh pr create --base main --head dev --title "<conventional summary>" --body "<changelog-worthy body>"`.
3. Wait for PR checks (Tests matrix 3.9–3.12 × ubuntu/macos/windows, lint, vscode build): `gh pr checks <n> --watch`.
4. `gh pr merge <n> --merge --admin` (merge commit, matching the `Merge dev → main` history — keeps `main`/`dev` aligned, no squash phantom-diff). version-bump fires automatically.
5. **Back-merge `main → dev`** to pick up the bot's `[skip ci]` VERSION/CHANGELOG/manifest commit: `git checkout dev && git merge origin/main && git push origin dev`. Skipping this makes the *next* deploy drift on CHANGELOG.md. After it, `git diff origin/main..dev` is empty. (Direct push to `dev` works — the branch-protection "must be a PR" line is advisory here.)
6. Re-run `./install.sh` if you want the local `~/.claude/skills/work-plan/` copy current.

### Publishing the npm CLI and the VS Code extension
Two **independent**, version-source-distinct publishes, both gated on the deploy landing on `main` first:

- **npm** (`@stylusnexus/work-plan`) — version is **derived from `VERSION`** (CalVer→semver, e.g. `2026.06.10` → `2026.6.10`) and stamped at publish time; the committed `package.json` version is irrelevant. Trigger manually: `gh workflow run npm-publish.yml --ref main -f dry_run=false` (default `dry_run=true` just packs+validates). Same-day republish of an already-taken version needs the `version_suffix` input (e.g. `-1`).
- **VS Code** (`stylusnexus.work-plan-viewer`) — version comes from **`vscode/package.json` and must be hand-bumped** (semver; the convention has been a patch bump per deploy — `0.3.1`/`0.3.2`/`0.3.3`/`0.3.4`). Marketplace `--skip-duplicate` means republishing the same version silently no-ops, so bump it in the deploy. Publish by **creating a GitHub Release** (`gh release create v<VERSION-with-dash> --target main …`, tag form `v2026.06.10-a6052bf`) which triggers `vscode-publish.yml` → Marketplace + Open VSX as two independent jobs (either can be re-run alone). Or `gh workflow run vscode-publish.yml -f dry_run=false`.

Both publish workflows need repo/org Actions secrets: `NPM_TOKEN`; `VSCE_PAT` + `OVSX_TOKEN`. The Marketplace publisher (`stylusnexus`) must already exist.

### Same-day re-deploys (version collisions)

Two deploys on the **same UTC day** collide on version, because each registry derives its version differently — handle both before re-publishing:

- **npm** drops the sha: `VERSION` `2026.06.10+<sha>` → semver `2026.6.10`. The sha differs per deploy, but the published npm version does **not**, so a second same-day publish of `2026.6.10` is rejected ("cannot publish over existing version"). Use the workflow's `version_suffix` input: `gh workflow run npm-publish.yml --ref main -f dry_run=false -f version_suffix=-1` (then `-2`, …) for the 2nd+ same-day publish.
- **VS Code** version is independent and hand-set in `vscode/package.json`; it is **not** date-derived, so it never auto-collides — but you must bump it for **every** publish, including a second same-day one (e.g. `0.3.4` → `0.3.5`). Marketplace publishes with `--skip-duplicate`, so forgetting the bump means the workflow silently no-ops and the new build never ships. The GitHub Release tag embeds the sha (`v2026.06.10-<sha2>`), so the tag itself won't collide — only the extension version inside the VSIX matters.

In short: same-day npm needs `version_suffix`; same-day VS Code needs another `package.json` patch bump. Neither is automatic.
