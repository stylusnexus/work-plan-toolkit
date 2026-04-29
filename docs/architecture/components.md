# Component Reference

> Companion to: [overview.md](overview.md) · [data-flow.md](data-flow.md)

Per-module breakdown of `skills/work-plan/`. The full canonical user-facing description of each subcommand lives in `work_plan.py` (`DESCRIPTIONS` list) and `SKILL.md` — this doc covers internal structure only.

## Top-level layout

```
skills/work-plan/
├── work_plan.py            # Dispatcher. SUBCOMMANDS dict + DESCRIPTIONS help text.
├── SKILL.md                # LLM-facing usage rules (verbatim relay, next_up flow, ...).
├── commands/               # 16 subcommand modules. Each exports `run(args) -> int`.
└── lib/                    # 13 shared helpers. Pure stdlib, importable from any command.
```

## `work_plan.py` (dispatcher)

The entry point. Three responsibilities:

1. Map subcommand name → module path (`SUBCOMMANDS` dict). Supports both `brief` and `--brief` forms; flag-style aliases exist for the four essentials (`--brief`, `--handoff`, `--orient`, `--hygiene`).
2. Print rich help (`--help` / `-h` / no args) using the hand-maintained `DESCRIPTIONS` list — this is the user-facing reference, not auto-generated.
3. Dynamic-import the chosen module and call `module.run(argv[2:])`.

**Adding a subcommand**: write `commands/<name>.py` with `def run(args: list[str]) -> int`, register in BOTH `SUBCOMMANDS` and `DESCRIPTIONS`. Forgetting `DESCRIPTIONS` makes the subcommand work but leaves it undocumented in `--help`.

## `commands/` — subcommand modules

Each module is thin orchestration over `lib/`. Sizes are an honest signal of complexity:

| Module | LOC | Role |
|---|---:|---|
| `handoff.py` | 595 | The most complex command. Derives recent commits attributable to a track (two attribution paths: explicit branches, or scan-and-filter by `#NNNN` mentions), uncommitted files (only if current branch belongs to this track), GitHub-closed-since-last-handoff, and a "fresh-session prompt" copy block. Also has an `--interactive` legacy mode and `--set-next` for Claude-driven `next_up` persistence. |
| `where_was_i.py` | 302 | `orient`. Track-mode: ~15-line paste block (priority, last session, next pick, git state). No-arg cwd-mode: branch + recent commits + modified files for non-track work. `--pick` forces an interactive picker. |
| `group.py` | 223 | Two-step AI clustering: step 1 fetches GitHub issues + writes a clustering prompt; step 2 (`--apply`) reads `/tmp/work_plan_groups.answers.json` written by the surrounding LLM and creates `<repo>/<slug>.md` track files. |
| `brief.py` | 199 | Multi-track snapshot. Walks tracks, fetches GitHub state per track, applies time-aware framing (`lib/render.py`), prints sorted by priority. Output is the deliverable — verbatim relay required. |
| `suggest_priorities.py` | 124 | Two-step AI label backfill: step 1 fetches unlabeled issues + prompts for `priority/PN` labels; step 2 (`--apply`) calls `gh issue edit --add-label`. Mirrors the structure of `group.py`. |
| `canonicalize.py` | 123 | Inserts a `<!-- canonical-issue-table -->` marker + table at the top of a track's body, so subsequent `refresh-md` calls target only that table and leave narrative tables alone. |
| `duplicates.py` | 111 | stdlib `difflib` similarity scan over open issue titles. Prints `gh issue close` consolidation commands. |
| `refresh_md.py` | 110 | Sync canonical body status table with current GitHub state. `--all` sweeps every active track. |
| `reconcile.py` | 98 | Sync track frontmatter with `track/<slug>` GitHub labels (label-as-source-of-truth direction). |
| `init_repo.py` | 90 | Bootstrap: create `<notes_root>/<key>/archive/{shipped,abandoned}/` + add a repo block to `~/.claude/work-plan/config.yml` via `yq -i`. JSON-encodes inputs to prevent YAML injection. |
| `slot.py` | 81 | Add an issue number to a track's `github.issues` list. Dedupes. |
| `init.py` | 66 | Add YAML frontmatter to a brand-new track `.md` file. |
| `close.py` | 56 | Mark a track shipped/parked/abandoned. Moves to `archive/<state>/` for shipped/abandoned. |
| `hygiene.py` | 51 | Wrapper: invokes `refresh_md.py --all` + `reconcile.py --all` + `duplicates.py` in sequence. |
| `list_cmd.py` | 39 | List active tracks. `--all` includes parked/archived. |

## `lib/` — shared helpers

| Module | LOC | Purpose | Used by |
|---|---:|---|---|
| `tracks.py` | 98 | `discover_tracks(cfg)` walks `notes_root/` and builds `Track` dataclasses. `find_track_by_name` is the canonical resolver — every command that takes a track arg uses it. | every command that operates on tracks |
| `frontmatter.py` | 48 | `parse_file` / `write_file` for YAML-frontmattered markdown. Preserves body exactly. Shells out to `yq` for YAML I/O (keeps stdlib-only invariant). | every command that edits tracks |
| `config.py` | 59 | Loads `~/.claude/work-plan/config.yml`. Normalizes legacy string-shape repo entries to dict shape. Exposes `resolve_github_for_folder`, `resolve_local_path_for_folder`. | all commands |
| `github_state.py` | 63 | `fetch_issues(repo, nums)` — wraps `gh issue view --json`. Defines `PRIORITY_LABELS` and `state_to_status_label`. | brief, handoff, orient, refresh-md, reconcile, suggest-priorities, group |
| `git_state.py` | 130 | `current_branch`, `has_uncommitted`, `commits_ahead`, `last_commit_date`, `branch_exists`, plus time helpers (`gap_seconds_to_label`, `parse_iso_timestamp`). Always runs git with `-C <path>` — never depends on cwd. | handoff, orient, brief, close |
| `status_table.py` | 122 | Find + edit the canonical markdown status table in a track body. Distinguishes "first table with issue refs" from "first table that happens to have a Status column". `find_canonical_status_tables` honors the `<!-- canonical-issue-table -->` marker placed by `canonicalize`. | handoff, refresh-md, drift |
| `session_log.py` | 39 | `append_session_log` writes `### Session — <ts>` blocks under the `## Session log` header. | handoff |
| `closure.py` | 72 | `is_closure_ready(signals)` — 5-signal gate (all issues closed, all branches done, `next_up` empty, cold 14d, no recent related issues). | close, brief |
| `drift.py` | 32 | `detect_drift(body, github_issues)` — compare body status icons (✅/🔲) with GitHub state. | brief, refresh-md |
| `new_issues.py` | 45 | Match recent GitHub issues to existing tracks by `track/<slug>` label or title-word fuzzy match. | brief, handoff |
| `render.py` | 74 | Output composers: `time_aware_framing`, `render_track_row`. Keeps presentation logic out of command modules. | brief |
| `prompts.py` | 68 | `prompt_input`, `prompt_lines`, `prompt_yes_no`, `parse_flags`. **Use these — don't reinvent.** | every interactive command |

## Command → lib dependency cheat-sheet

```mermaid
flowchart LR
    classDef cmd fill:#e8f3ff,stroke:#3b82f6
    classDef lib fill:#fff4e0,stroke:#f59e0b

    brief(brief):::cmd
    handoff(handoff):::cmd
    orient(orient):::cmd
    rmd(refresh-md):::cmd
    rec(reconcile):::cmd
    grp(group):::cmd
    sp(suggest-priorities):::cmd
    close(close):::cmd

    config[config]:::lib
    tracks[tracks]:::lib
    fm[frontmatter]:::lib
    ghs[github_state]:::lib
    gs[git_state]:::lib
    st[status_table]:::lib
    sl[session_log]:::lib
    drift[drift]:::lib
    closure[closure]:::lib
    render[render]:::lib

    brief --> tracks --> fm
    brief --> ghs
    brief --> render
    brief --> drift --> st
    brief --> closure
    handoff --> tracks
    handoff --> ghs
    handoff --> gs
    handoff --> st
    handoff --> sl
    orient --> tracks
    orient --> ghs
    orient --> gs
    rmd --> tracks
    rmd --> ghs
    rmd --> st
    rmd --> drift
    rec --> tracks
    rec --> ghs
    grp --> ghs
    sp --> ghs
    close --> tracks
    close --> closure
    tracks --> config
```

(Most commands also use `prompts.py` for `parse_flags`; omitted from the diagram for clarity.)

## Tests

Mirror of `commands/` and `lib/` under `skills/work-plan/tests/`. All `gh` / `git` subprocess calls are mocked via `unittest.mock`. The suite is offline, finishes in well under a second, and uses pure stdlib `unittest` (no `pytest`).

Notable test files:

- `test_handoff_set_next.py` — covers the `--set-next` flag round-trip (the LLM's persistence path for `next_up`).
- `test_status_table.py` — table parsing edge cases including narrative-vs-canonical distinction.
- `test_drift.py` — drift detection across emoji / text status formats.
- `test_smoke.py` — module imports and dispatcher returns `2` on no-args.
- `tests/fixtures/` — sample track markdown files used by table-parsing tests.

## Companion skill: `skills/repo-activity-summary/`

A single-file skill (`SKILL.md` only — no Python). Pure prompt engineering on top of three `gh` commands run in parallel: `gh issue list`, `gh pr list`, `gh run list`. Used as a global "what's open across the whole repo" view, complementary to the per-track `work-plan` lens.
