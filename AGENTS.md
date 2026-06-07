# AGENTS.md

Loop spec for coding agents (Claude Code, Codex, Cursor, Copilot) working on **work-plan-toolkit**.

**This file = how to verify your work and what "green" means.** `CLAUDE.md` is the deep reference and **overrides this file on any conflict**.

`work-plan-toolkit` *is* a Claude Code / Codex skill (`/work-plan`): a pure-Python-stdlib CLI for track-aware daily planning over GitHub issues, plus the `plan-status` doc-liveness command. An installer copies it into `~/.claude/skills/` (or `~/.agents/skills/` for Codex).

> **For Codex specifically:** in this repo, read-only review and analysis (e.g. `/spec-review`, code review, plan critique) are in scope and welcome — this repo's `AGENTS.md` governs here. Do **not** fall back to plan-only refusal / handoff for read-only work. Anything that writes files or runs mutating commands still follows the normal branch/PR rules below.

---

## The verify loop

Run these, read the output, fix, repeat. Do not claim success without running them.

| Step | Command | What "pass" means |
|------|---------|-------------------|
| Unit tests | `cd skills/work-plan && python3 -m unittest discover tests` | All green. Offline — every `gh`/`git` call is mocked; tests never hit the network. |
| Single test | `cd skills/work-plan && python3 -m unittest tests.<module>[.<Class>.<test>]` | The one you're iterating on passes. |
| CLI smoke | `python3 skills/work-plan/work_plan.py --help` | Runs without traceback. |
| Refresh live skill | `./install.sh` (`.\install.ps1` on Windows) | Re-copies source into `~/.claude/skills/work-plan/`. **Required after every source change** — editing source does NOT update the running skill. |

There is no build step, no lint config, no CI lint gate beyond a py3.9 union check + the unittest matrix (3.9–3.12 × ubuntu/macos/windows).

**Python / Node boundary.** Everything under `skills/work-plan/` (the CLI) is pure-stdlib Python with **no build step** — that property is load-bearing. The **`vscode/` subdir is a separate TS/Node project** (the viewer extension) with its own `package.json`, `npm` build, and CI job (`.github/workflows/vscode.yml`: typecheck · `node --test` · esbuild · `vsce package`). It does **not** touch the CLI's no-dependency property. The Python matrix (`test.yml`) only runs `unittest discover` inside `skills/work-plan/`, so it never exercises `vscode/`; the extension's gate is its own Node job. When editing `vscode/`, use Node conventions (the local gate is `npm run typecheck && npm test && npm run build`); everywhere else, stdlib Python.

---

## Traps that bite agents here

1. **Editing source ≠ updating the live skill.** Files under `skills/work-plan/` are source; the running `/work-plan` reads `~/.claude/skills/work-plan/`. Re-run `./install.sh` or your change has no effect on the slash command.
2. **`yq` means mikefarah/yq (Go), not kislyuk/yq (the Python jq wrapper).** Incompatible flags. Config + frontmatter parsing shell out to it.
3. **Pure stdlib only.** Python 3.9+ stdlib — no third-party packages (the "no `pip install`" property is load-bearing for redistribution). PEP 585 generics (`list[dict]`) are fine; **no 3.10+ features** (no `match` statements).
4. **New subcommand → register in BOTH places** in `work_plan.py`: the `SUBCOMMANDS` dict AND the `DESCRIPTIONS` list (help text is hand-written, not generated).

---

## Non-negotiables (guardrails on OUTPUT, not user input)

- **Pure Python 3.9+ stdlib.** No third-party deps, no `match`.
- **All GitHub state via `gh`** (reuses the user's `gh auth`; never read or store tokens). All git via `git` subprocess (list-form args).
- **GitHub is canonical for issue state.** The toolkit does NOT mirror or cache it — state is re-derived live from `gh`/`git`/the markdown body on every invocation. Don't add a cache.
- **Tests are offline.** Mock every `gh`/`git` subprocess call. Don't add tests that hit the network.
- **`install.sh` ↔ `install.ps1` and `uninstall.sh` ↔ `uninstall.ps1` stay in lockstep.** Change one, change the other (seed logic, auto-detection, config).

---

## Where things live

- Dispatcher: `skills/work-plan/work_plan.py` (maps subcommand → module; help is hand-written).
- Subcommands: `skills/work-plan/commands/<name>.py` (each exports `run(args) -> int`). Thin orchestration over `lib/`.
- Shared helpers: `skills/work-plan/lib/` (`config.py`, `frontmatter.py`, `tracks.py`, `github_state.py`, `git_state.py`, `status_table.py`, `prompts.py`).
- Tests: `skills/work-plan/tests/` (stdlib `unittest`, offline).
- Slash-command alias: `commands/work-plan.md`. Skill prompt: `skills/work-plan/SKILL.md`.
- Specs/plans: `docs/superpowers/specs/`, `docs/superpowers/plans/`.
- Source → runtime: `skills/work-plan/` → `~/.claude/skills/work-plan/` (via `install.sh`).

---

## Before you commit

- [ ] Conventional Commit title: `type(scope): description` (`feat|fix|chore|docs|test|refactor|perf|ci`).
- [ ] **Code** → feature branch `feat/<issue#>-name` + PR to `dev` (protected; squash-merge). Never commit code to `dev`/`main` directly.
- [ ] **Docs/specs** → may go straight to `dev`.
- [ ] Full test suite green: `cd skills/work-plan && python3 -m unittest discover tests`.
- [ ] Re-ran `./install.sh` if you changed skill source and want to exercise the live command.
- [ ] New subcommand registered in BOTH `SUBCOMMANDS` and `DESCRIPTIONS`.
- [ ] Still pure stdlib (no new imports of third-party packages; no `match`).
