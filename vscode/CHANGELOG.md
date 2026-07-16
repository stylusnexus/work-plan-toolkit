# Changelog

All notable changes to the **Work Plan Viewer** VS Code extension. Shown on
the Marketplace listing's Changelog tab. See [`README.md`](./README.md#status)
for the fuller narrative (including releases before this file started); new
entries land here going forward on every publish, alongside the `## Status`
line in `README.md`.

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
