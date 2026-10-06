# Changelog

All notable changes to the **Work Plan Viewer** VS Code extension. Shown on
the Marketplace listing's Changelog tab. See [`README.md`](./README.md#status)
for the fuller narrative (including releases before this file started); new
entries land here going forward on every publish, alongside the `## Status`
line in `README.md`.

## [0.20.0] - 2026-10-06

### Added

- **Stale tracks** lens and **Least recently touched** sort: find active,
  in-progress or blocked tracks that have gone quiet. New setting
  `workPlan.trackStaleDays` (default 14). Display only; nothing is archived or
  edited. The tooltip and detail panel show a human-readable age (#428).
- **Label search**: Search Issues matches GitHub labels with a `label:`
  prefix (`label:security`, `label:priority/%`), case-insensitively with the
  same `%` wildcards, across tracked and untracked issues. Results show each
  issue's labels (#429).
- **Work Plan: Run Diagnostics**: runs the CLI's dependency preflight (Python
  3.9+, git, gh and its sign-in, yq, config, notes_root, plan-branch
  worktrees) and prints every check with its fix (#427).

### Changed

- **Suggest Tracks (with AI)** opens Claude Code with the prompt ready, or
  copies it to the clipboard for other agents, instead of only writing it to
  the output channel (#496).
- Needs a CLI from this release for label search and diagnostics; an older CLI
  is detected and the panel says so.

## [0.19.10] - 2026-08-09

### Fixed

- A transient `gh` probe failure no longer looks like being signed out
  (#485).

## [0.19.9] - 2026-07-23

### Changed

- The track right-click menu is regrouped by how often each action is used,
  with clearer intent-first labels (#475).

## [0.19.8] - 2026-07-19

### Fixed

- Tree-row wording for convergence tracks: owned and referenced open counts no
  longer share the word "open" (#468).

## [0.19.7] - 2026-07-19

### Fixed

- A convergence track that owns no issues but has open cross-track references
  no longer reads as "nothing to do" (#466).

## [0.19.6] - 2026-07-19

### Added

- Cross-track issue references: a track can point at an issue owned by another
  track for coordination visibility via `github.references`, without taking
  ownership (#458).

## [0.19.5] - 2026-07-18

### Fixed

- A failed GitHub open-issues fetch (outage, auth lapse, rate limit) no longer
  looks like "zero untracked issues" (#454).

## [0.19.4] - 2026-07-16

### Added

- This changelog file, so the Marketplace listing shows a Changelog tab.

### Changed

- Republished alongside paired CLI changes: a yq-capability installer check
  (#433) and `brief`/`export` GitHub-read batching for a faster daily brief
  and viewer refresh (#420, #424, #422). Extension code unchanged.

## [0.19.3] - 2026-07-16

### Added

- Config-drift status-bar indicator (#439): a quiet check at activation for
  `config.yml` drift — a renamed local folder or GitHub repo, a broken local
  path, duplicate entries, an invalid `notes_root`, an orphaned notes folder,
  or a stale per-track repo slug. Shows a warning only when something's
  actually wrong; click it for details in the "Work Plan" output channel.
  Pairs with the CLI's `work-plan doctor [--json] [--fix]`.

### Changed

- CLI floor raised to `2026.07.15`.

## [0.19.2] - 2026-07-13

### Added

- Repo-qualified tracks and issues end to end (#430) — same-named tracks or
  same-numbered issues in different repositories no longer collide in graph
  state, detail selection, or write actions.

### Fixed

- Declared plan links now open only when the repo-relative file resolves
  safely inside the configured clone; absolute, traversal, missing, and
  symlinked escapes stay inactive (#195).

## [0.19.1] - 2026-07-10

### Fixed

- A `brief` crash for any track whose `next_up` mixed issue numbers with a
  non-issue token, e.g. an epic name (#417).

### Changed

- Least-privilege `allowed-tools` scoping (#415) on the bundled skills, so
  Claude Code grants scoped Bash rather than unrestricted shell.
