# Changelog

Production deploys, newest first. Entries below the marker are written
automatically by `.github/workflows/version-bump.yml` when a deploy PR merges
to `main` — from that PR's title and body. Don't hand-edit below the marker.

<!-- new entries inserted below -->

## 2026.07.19+708eb40 — 2026-07-19 (#461)

feat: model cross-track issue references without transferring ownership

### Added
- **Cross-track issue references** (#458): a track can now point at an issue owned by *another* track for coordination visibility via `github.references`, without transferring ownership — `github.issues` stays the sole ownership list used by slot/move/reconcile.
- New CLI: `batch-slot <issue>... <track> --reference` (mutually exclusive with `--move`).
- New VS Code command **Add Cross-Track Reference**, a **· N references** sidebar badge, and a **Referenced issues** table in the detail panel (capped and collapsible like the owned-issues table).
- VS Code extension bumped to v0.19.6.

### Fixed
- `dedupe-tiers --apply` could permanently delete a private track whose only content was cross-track references — `issue_refs()` now accounts for `github.references`.
- Reference writes had no compare-and-swap staleness guard, unlike ownership writes — added `references_fingerprint` + `--expect` support.
- `batch-slot --reference` could add an issue to `references` even when the track already owned it via `issues`, leaving a duplicate entry on disk.
- A cross-track reference's closed state could silently remove an unrelated entry from a track's own `next_up` list.
- References dropped `in_progress` / `blocked_by` / `blocking` on export, unlike owned issues.
- The VS Code detail view's referenced-issues table silently capped at 50 rows with no way to see the rest.
- The milestone-mismatch advisory was unintentionally skipped for `--reference` adds.

## 2026.07.18+657ad04 — 2026-07-18 (#457)

chore(vscode): bump to 0.19.5

### Changed

- `vscode/package.json` and the `vscode/README.md` Status line bumped to 0.19.5, ahead of publishing the GitHub-fetch-error-propagation fix (#454/#455) to the VS Code Marketplace and Open VSX.

PR: #456

## 2026.07.18+a345203 — 2026-07-18 (#455)

fix: surface GitHub fetch failures instead of false-empty results

### Fixed

- `fetch_open_issues()` no longer converts a failed GitHub fetch (bad repo, timeout, non-zero `gh` exit, malformed JSON, rate-limiting) into an indistinguishable empty list. `coverage`, `auto-triage`, `list-open-issues`, and `export` now report the failure explicitly instead of silently claiming "no open issues" / "full coverage."
- `export --json` gains an additive `github_fetch_errors` field; the VS Code extension retains a repo's last-known Untracked bucket and shows a "⚠ GitHub fetch failed" warning instead of implying zero untracked issues, and Suggest Tracks warns distinctly on a fetch failure rather than claiming full coverage.

PR: #454

## 2026.07.16+bcb403e — 2026-07-16 (#453)

chore(vscode): bump to v0.19.4 for the changelog tab

### Changed

- VS Code extension bumped to 0.19.4 — republish only, no extension code change. Bundles the new `vscode/CHANGELOG.md` (added in the previous deploy, #450) so the Marketplace listing's Changelog tab actually reflects it — the tab only refreshes on a new publish, and 0.19.3 was packaged before that file existed. Paired with the CLI release already on `main` (yq capability check #433, `brief`/`export` batching #420/#424/#422).

## 2026.07.16+015434c — 2026-07-16 (#451)

fix(installer): yq capability check + brief/export perf batching

### Fixed

- Both installers only checked that a command named `yq` exists — an incompatible implementation (e.g. kislyuk/yq, the Python jq wrapper) passed that check and then failed at the first config/frontmatter read. Both installers now run a trivial JSON/YAML round-trip probe before any install writes, rejecting incompatible `yq` shims with a clear remediation message. (#433)
- `export --json`'s `untracked` array ordering was silently nondeterministic (a set iteration order that varies with Python's hash randomization) — fixed to a first-seen-order list. Found and fixed alongside #424.

### Changed

- `brief` now groups active tracks by repo and fetches issue state + recent issues once per repo instead of once per track — a 10-track, one-repo brief made 20 GitHub operations where 2 repo-level fetches suffice. (#420)
- `export --json` now fetches per-repo visibility and open-issue state concurrently (bounded thread pool) instead of serially — measured 20.0s → 9.8s on 6 real repos. (#424)
- `export --json` now batches linked plan-badge git history per local clone (reusing plan-status's existing #391 batching machinery) instead of one git spawn per declared path per doc. (#422)

### Added

- `vscode/CHANGELOG.md`, so the Marketplace listing shows a Changelog tab (previously only Details/Features/Dependencies) — seeded with the last 3 published versions.

All four functional changes verified against real GitHub/git data (not just mocks) with before/after output diffs showing zero behavior change; full test suite green (1364 CLI tests + 21 installer/root tests); each PR passed an independent code review pass with no unresolved findings.

## 2026.07.16+e76ad81 — 2026-07-16 (#444)

chore: post-merge follow-ups for doctor release (#439)

### Summary
- Bump VS Code `MIN_CLI_VERSION` to `2026.07.15` to match the CLI's `doctor` subcommand release
- Bump `vscode/package.json` to `0.19.3` and update `vscode/README.md` Status section for the config-drift-detection feature

Follow-up commits to the already-merged #442 (doctor config-drift detection, #439), required before the VS Code Marketplace publish step of this release.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.07.15+cc41310 — 2026-07-15 (#443)

feat: doctor subcommand — config-drift detection + VS Code status-bar hook

### Added
- `work-plan doctor [--json] [--fix]` — detects drift between `config.yml`, local git clones, GitHub, and `notes_root/` track frontmatter (a renamed local folder or GitHub repo config.yml no longer matches, a non-git local path, duplicate entries, an invalid/missing notes_root, an orphaned notes folder, or a stale per-track `github.repo`). `--fix` corrects the two mechanically-safe cases (a GitHub-confirmed rename, a stale track slug) and always re-scans afterward.
- VS Code: a quiet status-bar indicator runs the same scan at activation and shows nothing when config is clean; click it to see the report in the "Work Plan" output channel.

### Fixed
- The exact failure mode that silently broke Auto Focus Repo for a renamed project earlier this session (`musical-family-trees` → `soundstellation-trees` locally and on GitHub, with `config.yml` never updated) — `doctor` catches and can auto-correct this class of drift.

Closes #439

## 2026.07.13+6341563 — 2026-07-13 (#438)

fix: harden plan paths, repo identity, and installers

## Security and correctness

- contain plan/spec discovery, stamping, exported plan links, and shared-track creation within their configured repository roots; atomic stamp replacement prevents hard-link write-through (#195)
- preserve repository-qualified track and issue identity throughout the VS Code graph, detail selection, and write actions (#430)
- preserve unmanaged or user-modified launchers using content-verified ownership markers, abort incomplete installs, and add native Windows installer coverage (#431)

## Distribution updates

- document the new guarantees in the npm-facing root README
- bump the VS Code extension to v0.19.2 and update its Marketplace README
- publish the CLI to npm, publish v0.19.2 to VS Code Marketplace/Open VSX, then repin and refresh the agent-plugins catalog README after tagging

## Verification

- Python unit suite: 1,260 passed
- VS Code: typecheck, 797 tests, production build, and VSIX package passed
- native installer regressions: Unix passed locally; Windows passed in CI
- npm package dry run and Python 3.9 syntax lint passed
- compromised-package catalog scan and npm audit reported zero findings

## 2026.07.10+92f8eef — 2026-07-10 (#419)

fix: brief no longer crashes on mixed next_up; least-privilege allowed-tools scoping (#415, #417)

Release covering three merged PRs since v0.19.0.

## Fixes
- **`brief` crash on mixed `next_up` (#417).** `brief` / `brief --repo=<key>` raised `TypeError: '<' not supported between 'str' and 'int'` for any track whose `next_up` frontmatter mixed issue numbers with a non-issue token (e.g. an epic name like `golden-path-v2`). A new `_numeric_refs()` helper unions the ref lists, keeps only int issue numbers (string tokens aren't fetchable issues), and sorts. Regression test added; full suite 1246 green.

## Hardening
- **Least-privilege `allowed-tools` scoping (#415).** `work-plan` and `repo-activity-summary` now declare `allowed-tools` frontmatter, so Claude Code grants a scoped allowlist (`Bash(work-plan:*), Bash(python3:*), Write` and `Bash(gh:*)`) instead of unrestricted Bash. Documented in README, SECURITY.md, and the architecture security sections.

## VS Code extension
- **v0.19.1** — republished for version parity; extension code unchanged (this release is the CLI `brief` fix + the scoping). Status/changelog updated in `vscode/README.md`.

## Chore
- Slot design-issue #386 into the `cli-viewer-cross` track.

Ships via: version-bump (main) → npm CLI publish → VS Code Marketplace/Open VSX (v0.19.1) → agent-plugins catalog repin.

## 2026.07.03+7d98e1e — 2026-07-03 (#414)

feat: track lifecycle (mark/archive/delete) + plan restore + yq auth fix

VS Code extension **0.19.0** + CLI. Ships three merged pieces.

### Added
- **Track lifecycle — mark / archive / delete** (#329, #328, #330). `mark-cleanup` (reversible 🧹 frontmatter flag + hygiene callout); `archive-track`/`unarchive-track` (reversible set-aside into `archive/parked/`, git-aware, with a viewer **Show Archived Tracks** toggle); `delete-track` (removes the `.md` only — **never touches GitHub issues** — behind a hard modal, type-to-confirm on shared tracks, honest permanent-vs-recoverable messaging). New shared `restore_from_archive` + `git_rm` primitives.
- **Un-archive (restore) a plan** (#388) — `plan-unarchive` + viewer **Restore to Live** on the 📦 Archived folder; the inverse of plan-archive, reusing the restore primitive.

### Fixed
- **A missing `yq` no longer masquerades as "Not signed in to GitHub"** (#410/#411) — the launcher preflight no longer gates `auth-status` behind `yq`, and the viewer distinguishes a failed auth probe from a real sign-out (builds on the #398 `probeOk` work).

### Verification
1242 Python + 759 VS Code tests, tsc + production build clean. The track cluster was code-reviewed (PR #412) — a borderline-critical false-recoverability promise on delete was caught + fixed (message now keys on whether the deletion was actually git-staged).

Genuinely-new since #409: #412 (track lifecycle), #413 (plan-unarchive), plus the #410/#411 yq fix already on dev.

## 2026.06.24+b047035 — 2026-06-24 (#409)

feat(viewer): Plans-view batch + onboarding states + archive correctness

VS Code extension **0.18.0** + CLI. A Plans-view, onboarding, and archive-correctness batch.

### Added
- **Batch Acknowledge / Save-to-Doc / Stamp Baseline** (#396) — multi-select stalled/dead (or any) plans in the Plans view and apply behind one confirm, one refresh per repo, mirroring the multi-select archive. Confirm Verdict stays single-only.

### Fixed
- **Onboarding no longer shows for configured users** (#398) — the auth probe was a hard gate (any `gh` blip wiped the tree to "Connect to GitHub") and "No repos yet" keyed on track count. Now a last-good cache survives a transient probe/load error, and empty-states partition into truly-new (onboarding) / configured-but-no-tracks ("No tracks yet") / load-error ("Couldn't load — Retry"). Preserves the `no-cli` banner from #402.
- **Archive: tracked-staged + gitignored plans handled honestly** (#399, P1) — a tracked plan archives as a staged `git mv` ("commit & push to share"); a gitignored/untracked plan as a plain filesystem move (`archived_local`) instead of a silent "git mv failed". The viewer toast + CLI wording say which.

### Docs
- Freshness pass (#395): README/SKILL/vscode-README cover archive staged-vs-local, batch ack/baseline, and the onboarding states.
- Changelog readability: vscode/README Status restructured into a per-version bulleted list; CHANGELOG sub-heading hierarchy fixed.

### Verification
1202 Python + 758 VS Code tests, tsc + production build clean. Each issue PR-reviewed; the #396 stampBaseline predicate bug was caught + fixed in review.

Commits since last deploy: `1920bf8` (#399), `29caada` (#398), `73af276` (#396), `d270f0d` (#395), plus release/changelog prep.

## 2026.06.23+6dce5e4 — 2026-06-23 (#404)

fix(vscode): distinguish missing CLI from "not signed in" (#402)

VS Code extension **0.17.2**. CLI unchanged (npm publish skipped).

### Fixed
- **Misleading "Not signed in to GitHub" banner (#402).** In a Remote-WSL window (`code .` from WSL), the extension host runs inside WSL and spawns the `work-plan` CLI there. A CLI installed only on Windows ENOENTs, and `checkAuth` was swallowing that into a false "not signed in" state even though `gh` was authenticated. The viewer now distinguishes three causes — **missing CLI** (new "work-plan CLI not found — install it" banner, calling out the WSL/remote "install it where the host runs" gotcha), **gh not installed**, and **not signed in** — each with its own banner + activation toast + Retry message.

### Docs
- README + vscode/README: WSL / Remote-SSH / dev-container install guidance — the CLI (and `gh auth`) must live in the same environment as the extension host.

### Internals
- `CliError.notFound` flag (set on the ENOENT branch only); `AuthState.cliPresent`; a 4th `workPlanGitHubAuthed` context state `"no-cli"` (checked before gh).

### Verification
751 tests pass, tsc clean, production build clean. Code-reviewed (PR #403) — 0 critical/important findings; the 4-state banner machine partitions cleanly (exactly one banner per state).

Commits since last deploy: `4f506e3` (#402 fix, via #403), `d2e8cad` (release prep).

## 2026.06.22+f62c4cc — 2026-06-22 (#401)

fix: free-text track blockers (graph bomb + brief relay)

Ships the free-text-blocker fix to production (VS Code extension **0.17.1** + CLI).

A `blockers:` frontmatter entry can be a free-text note, not just an issue number (surfaced on the CritForge `gpt-5-4-upgrades` track). `Track.blockers` was typed `number[]`, so consumers spliced the raw string into numeric positions.

### Fixed
- **VS Code dependency graph** — a prose blocker was spliced into a Mermaid node id (`i_<prose>`) → "Syntax error in text" across the whole graph pane. Free-text blockers now drop from graph edges (the track still shows ⛔ blocked); pure-`#N`/numeric blockers still draw edges.
- **Detail panel** — free-text blockers render as an escaped chip (was an unescaped `#<sentence>`, an HTML-injection hole); a string-form ref like `"#5548"` now dedupes correctly against its same-repo blocked-by edge (was double-rendering).
- **Sidebar badge** — shows `⛔ blocked` for a free-text-only blocker instead of the whole sentence.
- **`brief` / `orient` relay (CLI)** — print a free-text blocker as prose, not `#<sentence>`; the next-up gate now excludes string-form refs correctly.

### How
`Blocker = number | string` + a shared `blockerIssue()` (TS) / `lib/blockers.py` (Python) normalizer. A bare number / `"5550"` / `"#5550"` resolves to an issue ref; any other string is free-text (an embedded `#5550` in prose is deliberately NOT parsed — it's often an active next_up item). Leading-zero and overflow digit strings are rejected.

### Verification
VS Code 750 tests + tsc + production build clean; CLI 1200 Python tests. PR #400 (the dev merge) passed the full matrix.

### Docs
`vscode/package.json` → 0.17.1, `vscode/README.md` Status line, root README blockers note. agent-plugins catalog repin follows post-tag.

## 2026.06.21+1d0cb70 — 2026-06-21 (#397)

perf(plan-status)+feat(viewer): batch git calls + multi-select archive

Combined deploy: a perf hotfix for the Plans-view hang + multi-select batch archive.

### Changes
- **perf(plan-status): batch per-doc/per-path git calls (#391/#392)** — `plan-status` spawned ~1,800 `git` subprocesses on CritForge (one per doc + one per `Modify:` path) ≈ 40s, hanging the VS Code Plans view. Now one chunked `git log --name-only` walk (`paths_last_commit_dates`) serves the doc date, `committed_since`, and the staleness clock. **~40s → ~14s.** Verdicts unchanged; off-tree pathspecs filtered; back-compat fallback for direct callers.
- **feat(viewer): multi-select batch archive (#393/#394)** — `canSelectMany` on the Plans tree; right-click a multi-selection → **Archive Plan…** archives every archivable (shipped/unverified) doc behind one confirm, one refresh per repo, summary toast. Single-select unchanged. New `archivableSelection()` helper.

### Versions
- VS Code extension: 0.16.0 → **0.17.0**.
- npm: derives `2026.6.21` (already published today) → publish with `version_suffix=-1`.
- MIN_CLI_VERSION unchanged (`2026.06.15`).

### Tests
- CLI 1,193 (9 new); viewer 732 (3 new); typecheck + production build clean.
- Multi-select archive manually verified in a VSIX install.

### Follow-ups filed
- #395 (docs freshness — done), #396 (batch Acknowledge/Baseline for non-shipped plans), #388 (un-archive), #386 (manifest).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.21+4cab67a — 2026-06-21 (#390)

feat(plan-archive): archive a shipped plan — CLI + VS Code viewer

Ships #387 — archive a plan/spec doc scored ✅ shipped into `archive/shipped/`, from the CLI and the VS Code viewer.

### Changes
- **CLI:** new `plan-archive --repo=<key> [--draft] [--yes] [--json] -- <rel>` (per-doc, history-preserving `git mv`; refuses non-shipped; skips collisions, never overwrites); `plan-status --archive-shipped [--include-lie-gap]` batch sweep; `plan-status --include-archived` read (tags archived docs in `--json`); new `lib/archive.py` move primitive; `reconcile_actions.archive_dest(kind=)` + `shipped_rows`; discovery `include_archived` pass; footer hint.
- **VS Code viewer (extension 0.16.0):** right-click **Archive Plan…** (gated on a new `archivable` contextValue token so lie-gap + override-confirmed shipped docs qualify); repo **Archive shipped plans…** bulk action; collapsed **Archived (N)** folder per repo; repo "· N shipped" count; post-archive toast with **Show**; palette suppression.
- **Docs:** README (both command tables + Plans view), SKILL.md, vscode/README.

### Provenance
Spec → UX review → Codex spec-review → 13-task TDD build → defect-scan (clean) → code review (fixed a `--yes` no-op). CLI 1184 tests, viewer 729 tests, typecheck + build clean.

### Notes
- `MIN_CLI_VERSION` unchanged (`2026.06.15`); archive degrades gracefully on older CLIs.
- ⚠️ Manual VS Code F5 E2E not run pre-deploy (shipped on explicit authorization).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.19+9cf7cdc — 2026-06-19 (#385)

fix(viewer): repo focus no longer hides other repos; repo-scope toggle + deps security (VS Code 0.15.0)

Production deploy. VS Code extension **0.15.0**; npm CLI republished from the stamped VERSION.

### Viewer: repo-focus regression fixed (#383)
A repo lens (including the #357 auto-focus, previously on by default) filtered the track list but forwarded the full configured-repos list, so every *other* repo was seeded with zero tracks and rendered as **"No tracks yet — add one"** — indistinguishable from a deleted repo. Opening one repo's folder made every other repo's tracks look gone.

- `applyLens` now scopes the forwarded repos to the active lens; the tree's empty-state renders only for a repo genuinely empty in the raw export.
- **`workPlan.autoFocusRepo` now defaults to OFF** — the Tracks view shows every repo on open.
- `autoFocusRepo` reacts to the setting toggling at runtime (no reload needed).
- The per-repo `Repo: X` lens enumeration is replaced by a single state-aware **Select View** toggle — **Focus current repo** ↔ **Display all repos** — which also writes `workPlan.autoFocusRepo` so the default scope follows your last choice.
- The "fetch open issues" toast now says "untracked open issues" (it excludes already-tracked issues, so "no open issues" was false).

### Dependency security (#384)
Transitive bumps clearing 5 Dependabot alerts: `undici` 7.27.2→7.28.0 and `form-data` 4.0.5→4.0.6 (both build-time, via `@vscode/vsce`), `dompurify` 3.4.8→3.4.11 (bundled via mermaid into the shipped webview).

### Verification
- 721 viewer tests pass; `tsc --noEmit` clean; production build + VSIX package succeed.
- Independent code-review pass on the full deploy diff: **SHIP, no blockers** (verified lens/source re-entrancy, `scopeReposToLens` correctness, empty-state guard).
- `npm audit` → 0 vulnerabilities.

### Deploy notes
- VS Code: `vscode/package.json` → 0.15.0, README Status line updated.
- CLI floor unchanged.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.19+ae4eff6 — 2026-06-19 (#382)

fix(vscode): label AI Suggest-Tracks command '(with AI)' to match the offline toast (0.14.2)

VS Code-only label fix. The offline-match toast hints *try Suggest Tracks (with AI)*, but the AI command was titled "Suggest Tracks for Untracked Issues…" with no "with AI" — the hint pointed at a label that didn't exist. Renamed to **"Suggest Tracks for Untracked Issues (with AI)…"** to mirror the **(offline, no AI)** variant.

Ships VS Code extension **0.14.2**. CLI unchanged → no npm republish. CLI floor `2026.06.15`.

## 2026.06.18+d4980a1 — 2026-06-18 (#380)

fix: auto-slot UX hotfix — JSON early-exits, remove enable gate, drop 'heuristic' jargon (0.14.1)

Hotfix for the v0.14.0 auto-slot feature shipped earlier today. One issue surfaced three UX problems; all fixed.

### fix(auto-triage): --json early-exits emit JSON, not human text
**Suggest Tracks** crashed with `could not parse auto-triage JSON` on a repo with **no active tracks** — the CLI's `--json` scan took the "No active tracks found … run group first" early-exit, which printed a bare human line and returned 0, so the viewer's `JSON.parse(stdout)` threw. The "no untracked — full coverage" exit had the same hazard. Both now emit a parseable `{note: "no_active_tracks" | "full_coverage"}` in `--json` mode (human text kept for the terminal), and the viewer shows a "create a track first" / "full coverage" message instead of an error.

### fix(vscode): remove the auto-slot enable gate
`workPlan.autoSlotSuggestions` (default off) hid the Suggested bucket — so running Suggest Tracks produced suggestions the setting then hid, and the command looked like it did nothing. Removed: nothing generates suggestions in the background, so running the command IS the opt-in. Buckets render whenever a scan has produced them. (Kept `autoSlotConfidenceThreshold`.)

### fix(vscode): drop "heuristic" jargon
The offline command is now **"Suggest Tracks for Untracked Issues (offline, no AI)…"**, the tree badge reads "· offline", and the offline toast reports the **real match count** — saying plainly when nothing matched ("all left untracked; try the AI variant") instead of pointing at an empty bucket.

### Ships
- VS Code extension **0.14.1**.
- npm `@stylusnexus/work-plan` (CLI auto-triage `--json` early-exit fix) — same-day republish, needs `version_suffix`.
- CLI floor unchanged (`2026.06.15`).

Tests: CLI 1162 · VS Code 715 · tsc clean.

## 2026.06.18+64ae461 — 2026-06-18 (#376)

feat: proactive auto-slot offer + collision guard, offline heuristic, webview-handler fix

Deploy of the auto-slot feature set plus a critical webview regression fix. Three issues.

### feat: proactive auto-slot offer + collision guard (#241)
Offer to slot untracked GitHub issues into existing tracks, with an AI-suggested destination per issue, and the hard collision-prevention the issue requires. Built in 4 phases:
- **CAS collision guard** — `slot`/`batch-slot` take `--expect=<fp>` (sha256 of the track's issue list); the write re-reads + merges onto fresh frontmatter and aborts `{stale}` instead of clobbering. Preserves concurrent body/other-field edits.
- **Shared-tier rebase guard** — for a track on a `plan_branch`, fetch + `rebase --autostash` onto origin before writing; `{needs_rebase}` abort on un-rebasable divergence. `/security-review`'d.
- **Suggestion engine** — `auto-triage --json` scan + `batch_id` + a v2 abstain-first answers schema (legacy v1 still applies).
- **Viewer** (opt-in `workPlan.autoSlotSuggestions`) — Suggested (one-click Accept) / Needs-review sub-buckets under Untracked; Accept slots through the guard + public-repo modal, branching on stale/needsRebase. 5 commands, fs.watch, dismiss state.

### feat: offline heuristic suggestion mode (#373)
`auto-triage --heuristic` scores untracked issues against candidate tracks on local signals (milestone / track-label / title-scope keyword overlap), abstain-first, and writes the v2 answers file itself (`source: "heuristic"`) — so the Suggested bucket works with no Claude session (lower-trust, offline). New viewer command **Suggest Tracks (offline heuristic)**; heuristic suggestions are flagged lower-trust.

### fix(vscode): webview handlers dead since 0.9.0 (#374)
Escaped quotes in an inline-script template literal collapsed to a `SyntaxError`, killing the entire messaging IIFE — every webview click handler (track select, focus toggle, the 0.12.0 graph zoom/pan/export controls) was silently dead from 0.9.0 onward. Fixed; added a parse-guard test that `new Function()`-checks every inline script so this class fails CI.

### Ships
- VS Code extension **0.14.0** (Marketplace + Open VSX) — 0.13.0 already shipped 2026-06-16.
- npm `@stylusnexus/work-plan` (CLI: the guard, `auto-triage --json/--heuristic`, v2 answers).
- CLI floor unchanged (`2026.06.15`).

Tests: CLI 1159 · VS Code 715 · tsc clean. Cross-language CAS fingerprint verified.

## 2026.06.16+ebd6045 — 2026-06-16 (#370)

feat: repo-scoping (brief auto-scope + viewer auto-focus), reconcile one-click apply, dedupe-tiers

Deploy of the cwd-aware repo-scoping feature pair plus several CLI/viewer improvements bundled since the last release.

### Highlights

**Repo scoping (cwd-aware) — #358 / #357**
- `which-repo` resolver maps a directory to a configured repo (local clone path first, then git remote) — the shared substrate both surfaces use.
- **CLI:** `brief` auto-scopes to the repo of the cwd when `--repo` is omitted (one-line banner; `--repo=all` for the full view; `brief_auto_scope: false` opt-out). Archived-reopen callouts are scoped to the same repo.
- **Viewer:** the Tracks lens auto-focuses on the open workspace folder's repo (by GitHub slug), with a sticky manual override, re-arm on folder change, and a `workPlan.autoFocusRepo` opt-out.

**Reconcile one-click apply — #221**
- The viewer's Check Label Drift preview now offers an **Apply reconcile** action that performs the write through the public-repo leak guard, instead of sending you to a terminal.

**dedupe-tiers — #359 / #361**
- New `dedupe-tiers` CLI command removes private track copies a shared `.work-plan/` twin supersedes (refuses any whose private copy holds issue refs the shared one lacks). The viewer surfaces a read-only ⚠ tier-duplicate advisory naming the command.

**CI — #5**
- `install.sh` is now smoke-tested on Linux in CI (help, real install, `--target` override, `work_plan.py --help`).

**Chore**
- Removed a dead variable in drift detection and pinned the intentional CLOSED-broad / OPEN-narrow asymmetry with tests.

### Surfaces published this deploy
- **npm** `@stylusnexus/work-plan` (CLI changed).
- **VS Code** `stylusnexus.work-plan-viewer` **0.13.0** (Marketplace + Open VSX).
- agent-plugins catalog repinned to the new tag.

CLI floor for the viewer unchanged (≥ `2026.06.15`); all new viewer features degrade gracefully on an older CLI.

## 2026.06.15+488753b — 2026-06-15 (#356)

feat: graph zoom/export, Plans auto-update, native auto-next picker, verdict legend, settings gear

VS Code extension **v0.12.0** + CLI. Five features (each reviewed, CI-green, merged to `dev` individually).

### Features

- **Dependency graph: zoom / pan / fit-to-width + Export SVG/PNG (#216).** The graph is now a pan/zoom viewport — scroll-wheel zoom, drag-to-pan, header buttons (zoom ±, Fit, Reset), and Export as SVG or PNG. Vanilla JS, no new dependency, CSP-clean. Dense maps stay navigable.
- **Plans view auto-updates on git activity (#287).** Committing a stalled plan's declared files clears its "stalled" verdict without a manual Refresh — a per-repo `.git`-refs watcher debounce-rescans only that repo; time-relative staleness re-evaluates on focus. New `workPlan.plansAutoRefresh` setting (default on).
- **Native auto-next picker for Handoff (#274).** Brings the CLI's `--auto-next` to the viewer (its `[Y/n/edit]` TTY prompt can't run under VS Code's non-TTY stdin). New read-only `handoff --suggest-next` JSON feed → a pre-checked multi-select QuickPick → writes via the audited `handoff --set-next` path (public-repo confirm + session log).
- **Plan verdict-icon legend + plain labels (#348).** An ℹ️ title-bar button opens a self-demonstrating QuickPick decoding each Plans icon; the tooltip leads with a plain label (lie-gap→"Unverified", etc.); two sharpened shapes (stalled→clock, drift→issue-reopened). The #208 distinct-shape a11y invariant is now test-enforced.
- **Settings gear (#352).** A `$(gear)` button (last nav icon in the Tracks title bar) opens the Settings UI scoped to this extension; also "Work Plan: Open Settings" in the palette.

### CLI

- `handoff --suggest-next` — read-only JSON suggestion feed for the native auto-next picker (no prompt, no write). Shares `_compute_auto_next` with the interactive `--auto-next`.

### Compatibility

- VS Code extension `0.11.1` → `0.12.0`. `MIN_CLI_VERSION` → `2026.06.15` (the native auto-next picker needs `handoff --suggest-next`).

### Verification

All merged with green CI (Tests matrix 3.9–3.12 × ubuntu/macos/windows + typecheck/build/lint). 1080 CLI tests + 661 vscode tests pass. Each feature reviewed by the code-reviewer agent; #216 and #287 had one Important finding each, both fixed before merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.15+e3f3cdf — 2026-06-15 (#346)

feat(vscode,export): consistent Edit Fields affordances, untracked-issue fix, npm-12 posture

Deploy of five changes accumulated on `dev`.

### feat
- **vscode**: Edit Track Fields now uses consistent affordances for `launch_priority` (P0–P3 QuickPick) and `milestone_alignment` (suggests existing milestones + type-new/clear escape hatches), matching New Track. (#213 / #345) — ships as extension **v0.11.1**.

### fix
- **export**: a repo whose only track has `issues: []` no longer hides its open issues — `export --json` now computes untracked for every repo that has any track, not just repos with tracked issues. An empty track previously made a repo's open issues vanish entirely (not in the track, not in untracked, and the viewer's trackless fallback shuts off once a track exists). (#342 / #343)

### chore
- **npm**: dropped the redundant `postinstall` script (`scripts/npm-check-deps.js`) so the package is zero-lifecycle-script ahead of npm 12's install-time default-deny; the runtime preflight in `bin/work-plan` already covers the same check. (#280 / #344)
- **deps-dev**: bumped esbuild 0.25 → 0.28.1 in /vscode, resolving the high-severity Dependabot alert (build-time bundler; not shipped). (#294 / #347)
- **vscode**: extension version bump 0.11.0 → 0.11.1.

Commits:
fbf239c chore(deps-dev): bump esbuild 0.25 → 0.28.1 in /vscode (#347)
64857a0 chore(vscode): bump extension to 0.11.1 (#213 Edit Fields affordances)
8c70dda feat(vscode): consistent priority/milestone affordances in Edit Fields (#345)
8dec257 chore(npm): drop redundant postinstall script for npm 12 default-deny compatibility (#344)
73aa009 fix(export): surface untracked issues for repos whose only track is empty (#343)

## 2026.06.15+c80ece1 — 2026-06-15 (#341)

feat: toggle auto next-up per track (#338) — CLI --auto + viewer (0.11.0)

Production deploy: completes #338 — turn auto next-up on/off per track.

### #338
- **CLI:** `set-next-up --auto=on|off` toggles a track's `next_up_auto` flag (standalone or combined with a preset; public-repo confirm-gated). `export --json` `next_up_auto` field reflects the setting.
- **VS Code (0.11.0):** an "Auto next-up: ON/OFF" toggle folded into the "Set Next-Up Order…" QuickPick (✓ current state), and the detail panel's "Next-up order:" row shows `flow · auto` when active.

### Publishes (post-merge)
- CLI changed → **npm** republish (same-day → `2026.6.15-2`).
- VS Code **0.11.0** → Marketplace + Open VSX.
- `MIN_CLI_VERSION` unchanged (`2026.06.14` ≤ deploy VERSION; degrades gracefully).
- Tag + repin the agent-plugins catalog.

### Test plan
- [x] dev CI green; full Python suite 1075 OK; VS Code typecheck + 639 tests + build clean.

## 2026.06.15+a627bc9 — 2026-06-15 (#337)

fix(export): auto-derive next-up so the viewer surfaces the ranking (#326)

CLI-only deploy: closes the #326 viewer gap.

`build_export` now computes the auto next-up via `suggest_next_up` when a track has `next_up_auto: true` (mirroring `brief`/`orient`), so the VS Code viewer — which reads `next_up` straight from `export --json` — finally surfaces the ranked picks instead of just the preset name. Emits a `next_up_auto` flag per track.

### Publishes
- CLI changed → **npm** republish (same-day → `2026.6.15-1`).
- **VS Code NOT republished** (no extension change — the viewer already renders `next_up`).
- Tag + repin the agent-plugins catalog.

### Test plan
- [x] Full Python suite 1064 OK; brief-parity + raw-issues verified in review.
- [x] Live: the track exports `next_up: [1099, 4185, 4228], next_up_auto: true`.

## 2026.06.15+cf5a38f — 2026-06-15 (#335)

feat(vscode): Set Next-Up button in detail panel (0.10.1) + README refresh

VS Code-only deploy.

### What
- **Set Next-Up button** in the track detail panel (#334) — sets next-up from where you're looking, reusing the `workPlan.setNext` command (no picker fallback; resolves the open track). Extension **0.10.0 → 0.10.1**.
- **Docs:** root README VS Code section refreshed to note the viewer's next-up controls (Set Next-Up + the Set Next-Up Order… preset picker), the per-issue in-progress badge, and the blocked-by/blocking dependency surfacing.

### Publishes (post-merge)
- **VS Code 0.10.1** → Marketplace + Open VSX.
- **npm skipped** — the CLI is unchanged since the last deploy (delta is VS Code + docs only).
- `MIN_CLI_VERSION` unchanged (`2026.06.14` ≤ deploy VERSION; the button needs no new CLI surface).
- Tag the deploy + repin the agent-plugins catalog to the new tag.

### Test plan
- [x] dev CI green; VS Code typecheck + 629 tests + build clean.
- [x] No `skills/` changes in the delta (CLI untouched) → npm correctly skipped.

## 2026.06.15+d52d670 — 2026-06-15 (#333)

feat: configurable per-track next-up ordering (#326) + issue-link fix (0.10.0)

Production deploy: the configurable auto next-up feature (#326, all 3 phases) plus the detail-panel issue-link fix.

### #326 — configurable per-track next-up ordering
Replaces the hardcoded next-up ranking with a dependency-aware default + per-track presets.
- **New default ranking:** in-progress-first → milestone → (blocked-by excluded, in-progress exempt) → unblocking fan-out → priority → recency → issue#. Uses #257's `blocked_by`/`blocking` edges (blocked = gate, fan-out = boost) and the in-progress signal.
- **Presets** (`lib/next_up.py`): `flow` (default), `priority-driven`, `backlog` — per-track via `next_up_order: {preset}` frontmatter, with a global `next_up_default` in config.
- **New CLI command** `set-next-up <track> --preset=<p>` (guarded, public-repo confirm-gated). `export --json` emits `next_up_preset` per track.
- **VS Code (0.10.0):** a "Set Next-Up Order…" track-menu QuickPick (writes via the CLI confirm flow) + a detail-panel preset indicator (`workPlan.showNextUpPreset` setting). Degrades gracefully on older CLIs.

### Issue-link fix (was 0.9.2 on dev, ships in 0.10.0)
Detail-panel + search issue-number links now carry a real `https://github.com/<repo>/issues/<n>` href, so clicking opens GitHub even if the webview script is blocked/stale (previously such a click silently scrolled to the top). Adds the missing `font-src` CSP directive.

### Versions / publishes (post-merge)
- CLI changed → **npm** republish (same-day → `2026.6.14-2`).
- VS Code extension **0.9.1 → 0.10.0** (Marketplace + Open VSX).
- `MIN_CLI_VERSION` stays `2026.06.14` (≤ deploy VERSION; the preset feature degrades gracefully).
- Tag the deploy + **repin the agent-plugins catalog** (Codex + Claude indexes) to the new tag.

### Test plan
- [x] dev CI green; full Python suite + VS Code typecheck/test/build all pass (1062 Python, 619 VS Code).
- [x] Pre-deploy check: MIN_CLI_VERSION ≤ VERSION; export perf 9.9s at real scale (no regression); `next_up_preset` emitted.

## 2026.06.14+6579bf7 — 2026-06-14 (#323)

fix(git_state): batch hot-branch detection — fixes multi-minute VS Code reload hang (#271)

Emergency perf hotfix. The 2026.06.14 deploy's #271 hot-branch detection made `hot_issue_numbers` O(branches) in git subprocesses, called once per track. On the CritForge clone (261 feat/fix branches × ~25 tracks sharing it) `export --json` took ~16 minutes — hanging every VS Code reload (the viewer runs export on activation).

Fix: one `git for-each-ref` (tip commit times) + in-memory recency filter, plus a per-clone process memo. **39.7s → 0.33s** per call; **full export 2–3 min → 12s**. Same results.

CLI change → **npm republish** (`2026.6.14` already taken today → `version_suffix=-1`). VS Code extension unchanged → no Marketplace republish.

### Test plan
- [x] dev CI green on the fix merge; full suite 1016 OK
- [x] Verified live against the 261-branch CritForge clone

## 2026.06.14+ce7d3fc — 2026-06-14 (#321)

fix(vscode): hotfix MIN_CLI_VERSION gate — 0.9.1 (false CLI-incompatible warning)

Emergency hotfix deploy. v0.9.0 (deployed earlier today) gated `MIN_CLI_VERSION = "2026.06.15"` while the CLI shipped as `2026.06.14`, so every user who updated the extension saw a false **"CLI version may be incompatible"** warning that "Update" could not resolve.

### #257 follow-up
- `MIN_CLI_VERSION` → `2026.06.14` (the deploy that actually added the gated export fields).
- Guard test: the gate can never be set ahead of the repo's own CLI `VERSION`.
- VS Code extension **0.9.0 → 0.9.1**. CLI unchanged → **VS Code-only republish; npm skipped** (CLI `2026.6.14` already published and identical).

### Test plan
- [x] dev CI green on the fix merge
- [x] VS Code typecheck + 603 tests + production build clean

## 2026.06.14+ef58902 — 2026-06-14 (#319)

feat: GitHub-native blocked-by/blocking edges (read-only) + issue-level in-progress (#257, #271)

Production deploy bundling two features that have landed on `dev` since the `2026.06.13` release (main/Marketplace were at CLI `2026.06.13` / VS Code `0.7.1`).

### #257 — surface GitHub-native blocked-by / blocking (read-only)
Reads GitHub's native issue `blockedBy`/`blocking` edges **live** (never cached) and surfaces them read-only — no ordering or status change.
- **CLI:** Issue-only GraphQL fragment (`blockedBy`/`blocking` with connection `totalCount` for truncation), OPEN-filtered into `{number, repo, title}` edges, threaded onto issues; `brief`/`orient` annotate next-up / next-pick / behind-it rows with `⊘ blocked by #N` (cross-repo → `owner/repo#N`), repo-scoped dedupe against manual blockers.
- **VS Code (0.9.0):** `IssueDep` type + `[]`-normalize at the export boundary + `MIN_CLI_VERSION` → `2026.06.15`; same-repo `--x` blocked-by edge in the focused dependency graph; `⛓` disclosure on detail-panel issue rows expanding to `⊘ blocked-by` / `⇒ blocking` chips.
- Read-only: the GitHub-mutation inventory is unchanged. Live authenticated GraphQL gate passed (Issue arm resolves, PR arm doesn't reject, end-to-end parse verified, dependency torn down).

### #271 — issue-level in-progress (the 0.8.0 work, not yet on main)
- **CLI:** `in-progress <n> [--clear]` adds/removes the `work-plan:in-progress` label (public-repo gated); `brief`/`orient` also derive in-progress from a hot `feat/<n>-`/`fix/<n>-` branch.
- **VS Code:** per-issue in-progress badge + Mark/Clear toggle in the detail panel; plus the 0.7.1→0.8.0 follow-up fixes (Close-on-GitHub button render, open-plan webview guard).

### Versions / publishes (post-merge)
- VS Code extension `0.7.1` → **0.9.0** (`vscode/package.json` + `vscode/README` Status already bumped on dev).
- CLI npm: first `2026.6.14` publish (no same-day collision with `2026.6.13`).
- `VERSION` / plugin manifests stamped automatically by `version-bump.yml` on merge.

### Test plan
- [x] dev CI green on the merge commit (Tests + VS Code Extension matrices)
- [x] Python `1014 OK`; VS Code typecheck clean + `602 pass` + esbuild production build clean
- [x] Phase A authenticated GraphQL gate recorded in #318

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.13+22f59a8 — 2026-06-13 (#316)

fix+feat: dark-mode a11y contrast, progress bar (#220) + activity badge (#215), Untracked/close-button fixes

Accessibility + polish follow-up to the 0.7.0 release. VS Code extension **0.7.0 → 0.7.1**.

### Accessibility (dark-mode contrast)
The reported "hard to see in dark mode" traced to `charts.*` ThemeColors (built for chart fills, muted on dark, missing WCAG 1.4.3 3:1 for icons). Swapped the tree's status/verdict icon colors to theme-tuned, list-semantic tokens — blocked/lie-gap → `list.errorForeground`, stalled/drift → `list.warningForeground`, shipped → `charts.green`, parked/dead/ack'd → `descriptionForeground`, plan "active" unified on `charts.blue`. Distinct icon **shapes** still carry the meaning, so nothing is colour-only. Webview: dropped compounding `opacity` on muted text, raised the detail-panel Move/Close action icons to legible-at-rest, extended the forced-colors override, bumped search closed-state weight.

### Features
- **#220** — a labelled open/closed progress bar in the per-track detail card + a `N open · C/T` count in the tree description.
- **#215** — an activity-bar badge: blocked-track count (fallback total open), host-themed.

### Fixes (v0.7.0 regressions)
- **#303** — Fetch Open Issues now excludes already-tracked issues (a tracked issue no longer surfaces under Untracked), and the on-demand fetch cache no longer overrides a tracked repo's live untracked list.
- **#305** — the detail-panel Close-on-GitHub button rendered as a gray box (font-fragile glyph + unstyled); now styled + a reliable glyph.

### Docs
README + vscode/README document the new surfaces; the agent-plugins catalog README was brought current to the 0.7.0 surface in a companion commit.

CI green across the 3.9–3.12 × {ubuntu,macos,windows} matrix + lint + vscode build. CLI 959 tests, viewer 527.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.13+bb0dbea — 2026-06-13 (#314)

feat: Plans-view plan-writes, GitHub issue-close + auth fast-fail, track↔plan link & push-track

A large feature batch (9 PRs) making the VS Code Plans view *act* instead of only report, plus GitHub-path hardening and track-sharing.

### Plan frontmatter writes (#286 — all confirm-gated, frontmatter-only)
- **Confirm Verdict** (`plan-confirm`) — pin a human `verdict_override` to silence a false "shipped but boxes unchecked" lie-gap.
- **Acknowledge & Save to Doc** (`plan-ack`) — a durable, shared `acknowledged` ack (vs the per-machine default).
- **Stamp Baseline — Watch for Drift** (`plan-baseline`) — records the verdict; `plan-status` then flags **drift** when a once-shipped plan silently regresses (declared files deleted/moved).
- Read-only **off-tree manifest** flag — surfaces declared paths that resolve outside the repo.
- Shared, escape-guarded + public-repo-gated frontmatter writer (`lib/plan_fm`).

### Track ↔ plan link (#285)
- A track declares its plan via `plan:` frontmatter; `export` resolves an execution badge; the detail panel offers one-click **Plan** navigation. No fuzzy matching.

### GitHub path
- **Close Issue on GitHub** (`close-issue`, #305) — close an issue (optional comment) from the untracked-issue right-click or a detail-panel row, gated by a mandatory "cannot be undone" modal. Joins `plan-status --issues` (create) as the toolkit's second opt-in, gated GitHub write.
- **Fast-fail auth** (`auth-status`, #307) — a "Not signed in to GitHub" / "GitHub CLI not found" banner + Sign-in path replaces the silently-empty tree.
- **Fetch Open Issues** (#303) — pull a trackless registered repo's open issues on demand into its Untracked bucket.

### Track sharing (#306)
- **Push to Shared Tier** (`push-track`) — promote a private track into the repo's shared `.work-plan/` plan branch and push (public-repo exposure gated).

### Docs/security
- READMEs reframe the GitHub-write posture (two opt-in gated writes: create + close) and SECURITY.md documents the new write surfaces (frontmatter writers, close-issue, push-track).

CI green across the 3.9–3.12 × {ubuntu,macos,windows} matrix + lint + vscode build on every PR; the full dev→main diff was code-reviewed clean (no blockers/highs). CLI 959 tests, viewer 516.

VS Code extension bumped 0.6.3 → **0.7.0**.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.13+d35a663 — 2026-06-13 (#300)

feat(vscode): track-only repos show as a greyed "not registered" row in Plans (ext 0.6.3)

### Summary

Closes the other half of the Tracks/Plans asymmetry (companion to 0.6.2). A repo with **tracks but no `repos:` config entry** can't be scanned by the Plans view — it resolves a local clone by config *folder key*, which a track-only repo lacks — so it was silently absent from Plans while appearing in Tracks.

Plans now lists such repos as a **greyed, non-expandable "not registered" leaf** after the real repo nodes: `circle-slash` icon, "not registered" description, a tooltip explaining why, and a click that launches **Add Repo** prefilled with the slug (and a key derived from it).

### How

- `unregisteredTrackRepos(export)` — a pure, vscode-free helper: distinct, sorted GitHub slugs that tracks reference but `exp.repos` doesn't contain (null/empty excluded).
- New `PlanNode` variant `{ kind: "unregistered"; slug }`; roots render registered repos first, then unregistered leaves.
- Sourced from the **raw** export and kept **separate from the scan list**, so Scan All / the stalled roll-up never try to scan a repo with no registered clone.
- `workPlan.addRepo` gains an optional `{ github, key }` seed, guarded with `typeof seed?.github === "string"` so a menu/palette context can't masquerade as a prefill.

### Tests (plain English)

New `unregisteredTrackRepos` suite: slug absent from repos → returned; slug present → excluded; duplicate track slugs → once; null/empty repo → excluded; missing `repos` field → all returned; all-registered → empty; result sorted.

### Verification

- `npm test` → 477 pass (+7 new)
- `npm run typecheck` → clean
- `vsce package` → clean (1.26 MB)
- code-reviewer pass (scan-path isolation + seed guard confirmed; a README changelog dup it flagged is fixed)

### Scope

VS Code-only — Python CLI unchanged, so **npm publish is skipped**. Bumps extension to **0.6.3**; Marketplace + Open VSX publish via the GitHub Release after merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.13+571c7a6 — 2026-06-13 (#298)

fix(vscode): zero-track registered repos now show in the Tracks view (ext 0.6.2)

### Summary

A registered repo with **no tracks yet** (e.g. a just-added `agent-armor`) appeared in the **Plans** view but was missing from **Tracks**. Root cause: the Tracks view renders from the lens-filtered export, and `applyLens` rebuilt the `Export` forwarding only `tracks`/`untracked` — silently dropping the configured `repos` list (#288). So `buildTree`'s empty-repo seeding loop iterated `[]` and zero-track repos vanished under every lens, including "All". The Plans view reads the raw export, so it kept showing them. Same class of bug as the `#99` untracked-forwarding fix, one field over.

### Changes

- `applyLens` now forwards `repos` unchanged (alongside `untracked`).
- Regression test block in `lenses.test.ts` (`#288`): forwards under `all`, forwards under a `repo` lens, undefined when absent.
- VS Code extension bumped **0.6.1 → 0.6.2**; README `## Status` line updated.

### Scope

VS Code-only — the Python CLI is unchanged, so **npm publish is skipped** (same as the 0.5.1 precedent). Marketplace + Open VSX publish via the GitHub Release after merge.

### Verification

- `npm test` → 470 pass (incl. 3 new)
- `npm run typecheck` → clean
- `vsce package` → packages cleanly (1.26 MB)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.13+30f6244 — 2026-06-13 (#296)

fix(vscode): Plans view papercuts (ext 0.6.1)

Extension-only patch (no CLI change; `MIN_CLI_VERSION` unchanged). VS Code extension **0.6.1**.

Post-0.6.0 UX fixes to the new Plans view, from live use:
- **Plans section collapsed by default** so Tracks stays the hot path.
- The **"Scan all repos for stalled plans…" empty-state is clickable** — runs the scan directly (the title-bar icon alone was undiscoverable).
- **Scan All uses a `$(telescope)` icon** instead of `$(search)` (the magnifying glass read as the Tracks Search and was ambiguous).
- **Trimmed the Plans title bar** — Toggle Show Acknowledged moved to the `…` overflow, leaving Scan All + Refresh.

npm publish skipped (CLI unchanged); VS Code Marketplace + Open VSX publish via the release.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.13+627d944 — 2026-06-13 (#293)

feat: Plans view, registered-repo management, list-pickers, Open Track File

Deploy of the 2026.06.13 release. Extension **0.6.0**; CLI floor **2026.06.13**.

### Highlights

#### Plans view (#164)
A new read-only **"Plans"** tree in the VS Code extension surfacing plan/spec docs and their `plan-status` health, loud on the two states that matter to spec-driven work:
- **stalled** — a `partial` plan whose *declared manifest files* have gone cold (no commit within the threshold) = "started executing, drifted off". Keyed off manifest-file git activity, not the (gitignored) plan doc's own date.
- **lie-gap** — scored shipped but its own phase checkboxes aren't ticked.
Lazy per-repo scanning, a cross-repo **"Scan All"** stalled roll-up (bounded-concurrent + streaming), click-to-open, **acknowledge/dismiss** (local, demote-not-hide), and a `workPlan.stallDays` threshold ("Match CLI" / 14/30/45/60/90). CLI side: `plan-status --json` gains `manifest_last_touched`/`stalled`/`lie_gap`/`unchecked_items`/`stall_days` + `--stall-days` flag and config.

### Registered repos are first-class (#288, #290)
`export --json` emits a top-level `repos[]` of every configured repo. A registered repo now appears in the sidebar **even with no tracks** (right-click → **New Track** to start) and in the Plans view if it has a local clone. Full repo management: **Add Repo** (honest feedback, re-add to set local), **Remove Repo**, **Clear Local Path** — destructive actions behind clear blocking modals that itemize what is/isn't deleted.

### Quality-of-life
- **Open Track File** (#211) — open a track's underlying `.md` from the tree or detail panel.
- **List-pickers** (#212, #282) — Move, Set Next-Up, and Add Issue to Track now pick from the known issue list (filterable) instead of retyping numbers.

### CLI data-integrity fixes (#255, #256)
- `reconcile --all` now keys state by `(repo, path)` — no more cross-repo membership bleed on duplicate slugs.
- `refresh-md` skips a track on an incomplete GitHub fetch instead of overwriting valid rows with `(not fetched)`.

### Notes
- `MIN_CLI_VERSION` → 2026.06.13 (the Plans view + repos[] listing need the new export/plan-status fields; older CLI shows a compat warning).
- Deferred follow-ups: #285 (track↔plan nav), #286 (V2 plan writes), #287 (reactive staleness).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.11+cbd3f57 — 2026-06-11 (#278)

fix(vscode): Daily Brief icon + re-entrancy guard (0.5.1)

Small VS Code extension fix — **0.5.1**.

- **fix(vscode): clearer Daily Brief icon + re-entrancy guard** — swap the Daily Brief title-bar `$(list-unordered)` (VS Code's hamburger/list glyph) for `$(checklist)`, and guard re-entrancy so repeat-clicks no longer spawn concurrent `brief` runs + stacked progress toasts.

### Versions
- VS Code extension hand-bumped **0.5.0 → 0.5.1** (`vscode/package.json` + `## Status`).
- **CLI/npm is unchanged** (Python skill untouched) — no npm republish this deploy; only the VS Code extension publishes.

### Verification
- vscode: typecheck clean, 416 tests pass, build OK.

## 2026.06.11+60c2651 — 2026-06-11 (#276)

feat: VS Code extension 0.5.0 — issue search, daily-driver commands, lens/sort indicator

VS Code extension **0.5.0** — a daily-driver + discoverability release. Bundles four feature PRs plus a screenshot refresh.

### Highlights

- **feat(vscode): keyword issue search (#272)** — new **Search Issues…** command (title-bar `$(search)` + palette) matches issue titles across every track and the Untracked bucket with a `%wildcard%` grammar: `%depends%` (contains), `fix%` (starts-with), `%audit` (ends-with), bare word = contains; case-insensitive. Matching is client-side. Results open in a dedicated, reusable **Issue Search** tab (grouped by repo, open issues first) — click a row to open on GitHub, or use the per-row reveal button to jump to the owning track in the tree. Strict-CSP, accessible, theme-adaptive; an "as of `<generated_at>`" line + Refresh & re-run.

- **feat(vscode): daily-driver relay commands (#210)** — **Daily Brief**, **Re-orient (Where was I)**, and **Wrap Up Session (Handoff)** are now runnable from the title bar / track right-click menu / palette, relaying the CLI's verbatim output to the Work Plan output channel. Handoff routes through the public-write confirm flow.

- **feat(vscode): active lens + sort indicator (#209)** — the active filter/sort is surfaced inline under the Tracks view title (e.g. `milestone: v2.0.0 · blocked-first`), clearing when you return to All tracks + default sort.

- **fix(vscode): numeric-aware milestone sort (#268)** — milestone entries in the Select View filter now sort numerically (`v0.5.0` before `v0.10.0`) instead of issue-iteration order.

- **docs(vscode): refresh dependency-graph screenshot (#223)** — community contribution (@Hritik-Kumar-dev): neutral demo-data screenshot showing current 0.4.x/0.5.0 features.

### Versions
- VS Code extension hand-bumped **0.4.2 → 0.5.0** (`vscode/package.json`); `## Status` line + root README updated.
- CLI VERSION (CalVer) + npm version are stamped automatically on this merge.

### Verification
- vscode: typecheck clean, **416** tests pass, production build OK.
- Full Python + vscode CI matrix green on dev.

## 2026.06.11+51bbb9a — 2026-06-11 (#267)

fix(vscode): render visibility×tier badge as Unicode glyphs in the tree

Ships the VS Code extension **v0.4.2**.

### Fixed
- **Visibility × tier badge rendered raw codicon tokens.** The per-track badge emitted `$(globe)` / `$(lock)` / `$(cloud)` / `$(warning)` as literal text in the tree, because `TreeItem.description` is plain text and never resolves `$(icon)` syntax. The badge now uses Unicode glyphs (🌐 / 🔒 / ☁️, ⚠️ for the exposed state) so it renders as intended. The hover tooltip was already correct (themed `MarkdownString`) and is unchanged.

No CLI changes this deploy — viewer-only fix. Extension bumped 0.4.1 → 0.4.2; `vscode/README.md` Status line updated.

## 2026.06.11+b34452d — 2026-06-11 (#265)

feat: canonical plan branch for the shared tier + visibility×tier badge (extension 0.4.1)

Production deploy. Extension bumped to **0.4.1**. Ships the #260 canonical-plan-branch feature (CLI) and the #259 visibility × tier badge (VS Code viewer).

### CLI — shared-tier planning on one canonical branch (#260)

The shared (`.work-plan/`) tier can now be pinned to **one canonical `plan_branch`** per repo, read and written through a dedicated git worktree — so planning lives off your code branches and never pollutes feature PRs or the `dev → main` deploy diff, yet the CLI and viewer always show the canonical plan from any checkout.

- **`plan-branch <init|status|push> <repo>`** — the bootstrap + share command. `init` creates an **orphan** branch (default `work-plan/plan`, like `gh-pages`; `--branch` overrides) with a `.work-plan/` skeleton, or **connects** to a teammate's already-published branch — **local only**. `status` reports exists / published / unpushed. `push` shares it, gated by a confirm token on **public** repos (with `--dry-run` to preview the exposure first).
- Discovery, shared-track creation (`group`/`new-track`), and the dispatcher's auto-commit all route through the plan-branch worktree when one is configured; repos without a `plan_branch` keep the legacy working-tree `.work-plan/` behaviour unchanged.
- Hardened to the notes-vcs data-safety bar across multiple adversarial review rounds: scoped commits (only the paths a command changed, NUL-delimited porcelain so spaced/non-ASCII filenames are safe), branch-verified worktree reuse, the public-repo exposure gate fails closed, and the whole path honours the never-raise contract.

### VS Code viewer — visibility × tier badge (#259), extension 0.4.1

Every tree item now carries a **visibility × tier badge** (🔒 private / 🌐 public repo, ☁ shared tier) that flags the one **exposed** state — a plan committed to a *public* repo's shared tier is world-visible. Theme-adaptive, with a MarkdownString tooltip explaining the state.

### Docs
README gains a "Canonical plan branch" section (with the CI-exclude tip) and a `plan-branch` command-table row; the extension README documents the badge and the 0.4.1 status.

Closes #259, #260.

## 2026.06.11+8c21445 — 2026-06-11 (#258)

feat: viewer UX + accessibility overhaul, notes-vcs safety, CLI clarity (extension 0.4.0)

Production deploy. Extension bumped to **0.4.0** (feature-heavy, non-breaking).

### VS Code viewer — UX
- **De-noised command palette**: commands moved the `Work Plan:` prefix into the `category` field, so titles are clean, searchable verbs; argument-only commands gated out of the palette.
- **Clearer command names**: *Refresh Track Body → Sync Issue States from GitHub*, *Reconcile (preview) → Check Label Drift (preview)*, *Slot Issue into Track → Add Issue to Track*, *Set Next-Up → Set Next-Up & Log Session* (it runs `handoff --set-next`, which also logs a session). CLI `--help` aligned.
- **Frequency-grouped track context menu** with separators fencing the destructive actions, plus **confirmation modals** before *abandon* (Close) and *Rename*.
- **Per-milestone filter**: an explicit *filter* control on each milestone band re-scopes the whole view; the result is clearable straight from its toast.
- **Progress feedback** on every write command.

### VS Code viewer — theming & accessibility
- **Editor-theme-adaptive** webview: Mermaid graph + detail-card colours follow light / dark / high-contrast (via `--vscode-charts-*` tokens + a forced-colors fallback), re-rendering on theme change.
- **Accessibility sweep**: distinct *shapes* for track status (not colour alone), keyboard-operable disclosures and depends-on chips with `aria-expanded`/labels, focus-visible move button, table `scope`/caption semantics, a graph text alternative, and a non-colour `⛔` marker on blocked graph nodes.

### Local history (notes-vcs) — opt-in, hardened
- Opt-in personal version control for the private `notes_root` tier with one-click Undo in the viewer, now with **safety boundaries**: refuses a `notes_root` that has a git remote or is a repo work-plan didn't create; commits **only the files a command changed** (pre-existing edits preserved); Undo/revert is gated on repo ownership + no-remote and on the new commit sitting directly on the previously-seen HEAD.

### CLI & housekeeping
- Clarified `refresh-md` / `reconcile` / `set` vs `handoff --set-next` help text.
- Stopped tracking agent scratch state (`.claude/agent-memory`, worktrees) in this public repo.

Closes #103, #207, #208, #214, #217, #218, #219, #224, #227, #228, #229, #230, #231, #232, #233, #238, #244, #248, #249, #250.

## 2026.06.10+a3d10bf — 2026-06-10 (#222)

feat: rename-track + milestone-ordered tracks (CLI & viewer)

Production deploy. Highlights since the last release:

### `rename-track` (#174)
New `rename-track <old-slug | old@repo> <new-slug>` CLI verb — renames a track's slug: moves the `.md` file (write-new-then-unlink-old, so a failed write leaves the original intact), updates the frontmatter `track` field + `last_touched`, and reuses the public-repo confirm-token gate. Shared tracks get an opt-in `--commit`; `--fix-refs` rewrites sibling tracks' `depends_on`. Surfaced in the VS Code viewer as a **Rename Track** right-click action.

### Milestone ordering within tracks (#101)
A track that mixes near-term and far-future issues now keeps "what's next" above "someday", everywhere it renders:
- **Viewer:** per-track milestone bands are ordered active-milestone-first (the track's `milestone_alignment` band first), not alphabetically.
- **CLI:** the canonical issue table is a single milestone-ordered table with a `Milestone` column (active milestone first, groups divided by a blank row). `refresh-md` re-derives it each run, so it self-heals instead of decaying. Replaces the old multi-section rendering that didn't round-trip.
- No-drift by construction: the markdown table and the viewer both derive order from the one `milestone_sort_key`; the canonicalize → refresh-md round-trip is byte-identical.

### VS Code extension → v0.3.6
Adds the Rename Track action and active-milestone-first band ordering. Marketplace + Open VSX.

### Docs
- CLAUDE.md: cross-project **model-routing** guidance; a deploy note to keep the `vscode/README.md` Status line in lockstep with the extension version.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.10+9dce675 — 2026-06-10 (#203)

fix(security): CLI + VS Code extension hardening (injection fixes, extension RCE)

Security release from a full review of the CLI and the VS Code extension, plus CI and public-repo hygiene. VS Code extension → 0.3.5; npm CLI republished.

### Security fixes
- **yq expression injection** in `set-notes-root` — a path containing `"` could rewrite arbitrary `config.yml` keys. Values now pass to `yq` via `strenv()`/`env()` (#191).
- **git option injection** via dash-led `github.branches` frontmatter → arbitrary file overwrite (`git log --output=`). Dash-led revs are now rejected (#192).
- **VS Code extension RCE** — `workPlan.cliPath` was workspace-overridable and spawned on activation. Now machine-scoped + `untrustedWorkspaces: { supported: false }` (#193).
- **Argument injection** via `--`-prefixed track names — CLI now honours a `--` end-of-options separator and rejects dash-led track filenames; the extension passes positionals after `--` (#194).
- **Hardening**: path-write containment + symlink-write guard (#195); `gh`/`git` subprocess timeouts, repo-slug validation, answers int-coercion (#196); webview confirm-modal consistency, Mermaid label newline handling, CSP/escaper nits (#197).

### Also in this release
- **CI**: GitHub Actions bumped to Node-24 majors (checkout v6, setup-node v6, upload-artifact v7, download-artifact v8) (#190).
- **Public-repo readiness**: CLAUDE.md now tracked for contributors; internal project references + a leaked maintainer path scrubbed repo-wide; SECURITY.md advisory history updated; issue templates + agent-doc cross-links added (#200, #201).

### Versions
- VS Code extension → **0.3.5**
- npm CLI republished (same-day CalVer, `-1` suffix)

Full suite green (Python 657 + lint matrix; vscode typecheck + 335 tests).

## 2026.06.10+a6052bf — 2026-06-10 (#189)

feat: reconcile auto-move + non-TTY hang fix, list --sort, viewer status lens

Production deploy. Ships four issues plus docs and the VS Code extension bump to 0.3.4.

### Fixes
- **#183 — `fix(prompts)`: non-TTY prompt hang.** `hygiene`/`reconcile` launched from the VS Code extension could block forever on a prompt (stdin is an open pipe that never delivers a line and never EOFs). All prompt helpers now fall back to their default when stdin is not a TTY. Adds `reconcile --yes` (auto-apply, local-write only) and `hygiene` forwards it.

### Features
- **#163 — `feat(reconcile)`: label-driven auto-move.** In an `--all`/`--repo` sweep, an issue relabeled from one track to another in the same repo is moved (removed from the old, added to the new) instead of dangling as a FLAG + duplicate ADD. Ambiguous targets stay FLAGs. PUBLIC-repo destinations are skipped under `--yes`.
- **#181 — `feat(list)`: `--sort`.** `list --sort=recent` (by `last_touched`) and `--sort=priority` (P0→P3, recency tiebreak); default keeps discovery order.
- **#180 — `feat(viewer)`: status filter lens.** New Active / Shipped / Parked lens in the VS Code viewer's Select View.

### Chore / docs
- VS Code extension bumped `0.3.3 → 0.3.4` for the status-lens Marketplace + Open VSX release.
- README + vscode/README updated for the new flags and lens.

Full suite green (644 tests).

## 2026.06.09+f25e6e1 — 2026-06-09 (#178)

docs: update READMEs for v0.3.2 features

README updates for the v0.3.2 feature set: move subcommand, depends_on chips, repo-scoped full map.

## 2026.06.09+03c8f5e — 2026-06-09 (#177)

Deploy: repo-scoped full map (v0.3.2)

### Change
The 'Show full map' graph now only shows tracks in the **same repo** as the selected track. Cross-repo tracks share no edges, so showing them together produced noise without value.

- Focus mode: unchanged (neighbourhood of selected track)
- Full map: scoped to selected track's repo

### Version
VSCode extension → 0.3.2

## 2026.06.09+a00489a — 2026-06-09 (#176)

Deploy: Mermaid fix + move subcommand + depends_on surface (#172, #162, #102)

### Changes in this deploy

#### #172 — Mermaid label escaping fix
- Replaced HTML entities with safe literal characters in `mermaidLabel`
- Mermaid 11.x's `entityDecode` was silently undoing all entity escaping, allowing `"]` sequences to break the parser
- Fix: `"` → `'`, `[{` → `(`, `]}` → `)`, backtick → `'`

#### #173 — `move` subcommand + VSCode right-click
- CLI `move` subcommand (source-first: `work-plan move <issue> <from> <to>`)
- VSCode context menu "Move Issue from Track" with QuickPick destination
- Added to `WriteAction` type with full public-repo confirm gate
- 13 CLI tests + 1 VSCode test

#### #175 — Surface `depends_on` in detail panel + README
- New "Depends on:" section in VSCode detail panel with clickable amber chips
- README documentation for cross-track dependencies
- 2 new detail panel tests

### Verification
- 620 Python tests pass
- 308 VSCode tests pass

## 2026.06.09+f86ff30 — 2026-06-09

**Features:**
- **orient**: `--repo=<key>` and `track@repo` disambiguation (#166, closes #129)
- **perf**: batched GraphQL issue fetching — ~9× speedup (#167, closes #106)
- **group/auto-triage**: `--limit=N` flag, default 100 (#168, closes #165)
- **viewer**: detail panel 50-row cap with collapsible overflow (#170, closes #169)
- **docs**: architecture.md + updated READMEs (#171, agent-plugins#2)

**Carried from dev:**
- `depends_on` replaces `related_tracks` for cross-track edges
- `move` subcommand + VS Code Move to track (#162)
- Milestone sections + ordering in canonicalize (#101)

## 2026.06.09+c8a85a8 — 2026-06-09 (#159)

chore(vscode): bump extension to 0.2.1 for batch-slot publish

### Deploy to production

**Commits in this deploy:**
- 736bc40 chore(vscode): bump to 0.2.1 for batch-slot publish

**Files changed:** 1 file, +1 / -1 (`vscode/package.json` version 0.2.0 → 0.2.1)

Lands the version bump that was needed to publish the VS Code extension with batch-slot support. The actual feature code shipped in #158; this aligns main with the published 0.2.1 extension.

## 2026.06.09+530f7e8 — 2026-06-09 (#158)

feat(batch-slot,tracks,vscode): batch-slot command + archived-track dedup

### Deploy to production

**Commits in this deploy:**
- e2a14dd feat(batch-slot,tracks): batch-slot command + archived-track dedup (#131, #140) (#157)

**Files changed:** 8 files, +657 / -8

- `skills/work-plan/commands/batch_slot.py` — new `batch-slot` subcommand (slot multiple issues at once)
- `skills/work-plan/lib/tracks.py` — archived-track dedup logic
- `skills/work-plan/tests/test_batch_slot.py` — 291-line test suite for batch-slot
- `skills/work-plan/tests/test_tracks.py` — archived-track dedup tests
- `skills/work-plan/work_plan.py` — subcommand registration
- `vscode/package.json` + `vscode/src/extension.ts` + `vscode/src/write.ts` — VS Code extension support

**CI:** 587 tests pass · vscode typecheck clean

## 2026.06.09+a6f1298 — 2026-06-09 (#156)

chore(npm): add version_suffix input for same-day republish

### Summary

- Adds optional `version_suffix` input to `npm-publish.yml` (e.g. `"-1"` → publishes `2026.6.9-1`)
- Allows same-day npm republish when the CalVer semver is already taken, without changing the VERSION file
- Used immediately after creation to publish `@stylusnexus/work-plan@2026.6.9-1` (CLI improvements from #151/#152 that landed after today's first npm publish)

### Migrations

None.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+f7e5ff5 — 2026-06-09 (#155)

feat(reconcile,hygiene): parallel gh fetches, per-call timeouts, progress indicators

### Summary

- **#151** `perf(reconcile,hygiene)`: parallel `gh` fetches in `reconcile --all` via `ThreadPoolExecutor` (4 workers); per-call 15s timeout per track; `--timeout=N` flag forwarded to `duplicates`; per-step timing in `hygiene`
- **#152** `feat(hygiene,reconcile,refresh-md)`: `[N/total]` progress indicator during `--all` sweeps in all three subcommands; also fixes latent `NameError` in `hygiene.py` step-2 timing (referenced `t2` before assignment)
- New test module: `test_reconcile_readonly.py` — timeout/skip behaviour for single-track and multi-track parallel paths

### Commits

```
8e8a29f feat(hygiene,reconcile): per-track progress indicator during --all sweep (#152) (#154)
2332c49 perf(reconcile,hygiene): parallel gh fetches + per-call timeout (#151) (#153)
```

### Migrations

None.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+ac8a3d7 — 2026-06-09 (#150)

docs(readme,skill): clarify refresh-md and hygiene, add read-only callout, vscode README v0.2.0

### Summary

- **SKILL.md + README.md**: rewrote `refresh-md` guidance — removed "you usually don't need this" framing; it's the right tool to run after closing issues. Expanded `hygiene` description to enumerate all three steps (refresh-md + reconcile + duplicates).
- **README.md + vscode/README.md**: added explicit GitHub read-only callout — the toolkit never writes to GitHub; all writes are local markdown files only.
- **vscode/README.md**: added `workPlan.autoRefreshInterval` to the configuration table; bumped Status line from v0.1.0 → v0.2.0 with feature summary.

### Commits

- docs: clarify refresh-md vs hygiene, add read-only callout, vscode README v0.2.0 (#149)

### Test plan
- [ ] README.md hygiene row enumerates all 3 steps
- [ ] SKILL.md refresh-md row says "run after closing issues"
- [ ] vscode/README.md config table includes autoRefreshInterval
- [ ] Read-only GitHub note present in both READMEs
- [ ] Status line in vscode/README.md reads v0.2.0

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+5d07d27 — 2026-06-09 (#148)

feat(viewer): auto-refresh, shared-track tier badge, welcome fix + README settings table

### Summary
- **#134 `workPlan.autoRefreshInterval`** — silent background poll on a user-configured interval (0=off, 30s/1m/5m/15m dropdown); timer restarts on config change
- **#137 Tier badge** — shared tracks show `shared N open` in the tree description; tooltip clarifies shared vs private
- **#118 Welcome state fix** — `viewsWelcome` now gated on `workPlanHasRepos` context key (driven from unfiltered data) so a lens that hides all tracks doesn't show "No repos yet"
- **Docs** — VS Code settings table in README; agent-plugins description updated for shared tracks + coverage/auto-triage

Bumps VS Code extension to **v0.2.0**.

### Commits
- feat(viewer): auto-refresh interval setting (#134) (#145)
- feat(viewer): tier badge on shared tracks + welcome state fix (#137, #118) (#146)
- docs: VS Code settings table + tier badge note in README (#147)
- test: fix Windows path separator in test_group_apply + test_init_repo

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+21c63ea — 2026-06-09 (#144)

feat(shared-notes,coverage,auto-triage): two-tier tracks, coverage report, AI triage, next_up fix

### What's shipping

#### Major: shared-notes (two-tier track storage)
Track files can now live inside a repo clone (`.work-plan/<slug>.md`, git-synced) alongside the existing private `notes_root` tier. Register a local clone with `init-repo --local=<path>`; tracks route there automatically. Teammates share planning state via `git pull`/`git push`. `--private` opts out per-command.

Phases A–D:
- Phase A: `discover_tracks` unions shared + private; `AmbiguousTrackError` for same-slug-different-repo
- Phase B: `--repo=<key>` / `<track>@<repo>` disambiguation on all write verbs
- Phase C: write-surface routing (`group`, `new-track`, `close`, `init`)
- Phase D: `init-repo` detects existing `.work-plan/` tracks; `new-track --commit`; `export` tier field

#### New: `coverage` command
`/work-plan coverage [--repo=<key>] [--list]` — reports how many open issues are outside the track model. 42% orphan rate measured on a real production repo.

#### New: `auto-triage` command
`/work-plan auto-triage [--repo=<key>] [--apply]` — two-step AI assignment of untracked issues to existing tracks. Complements `group` (which creates new tracks).

#### Fix: closed issues filtered from `next_up` in export
The VS Code viewer was showing closed issues as actionable next-up nodes. Export now cross-references `next_up` against the fetched issue states and removes confirmed-closed entries.

#### Docs
README, SKILL.md, npm description, and VS Code extension description updated with shared-notes setup, group/auto-triage callouts, and `@repo` disambiguation syntax.

---

PRs: #129 (shared-notes phases A–D via #132 #133 #135 #138), #139 (next_up fix), #141 (coverage), #142 (auto-triage), #143 (docs)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+f3bc861 — 2026-06-09 (#128)

feat: npm CLI distribution + launcher PATH fix + extension v0.1.1 (screenshots, docs)

Production deploy bundling the post-launch polish: npm distribution for the CLI, the GUI-PATH launcher fix, expanded docs, and the assets/version bump for the extension's `0.1.1` listing refresh.

### CLI — npm distribution
- **`@stylusnexus/work-plan` npm package** (root `package.json` + `scripts/npm-check-deps.js`): ships the Python CLI + launcher so `npm install -g @stylusnexus/work-plan` works (no repo clone). `files`-whitelisted (488 kB, no leaks); pure Python still, no build step. Plus `.github/workflows/npm-publish.yml` (CalVer→semver, `--access public`, `NPM_TOKEN`).
- **Launcher GUI-PATH fix** (`bin/work-plan`): GUI editors (VS Code from Finder/Dock) inherit a stripped PATH without Homebrew, so the CLI's `yq`/`gh` lookups failed and the viewer showed an empty tree. The launcher now prepends `/opt/homebrew/bin:/usr/local/bin`, and resolves symlinks (so the npm global-bin symlink finds its Python). Verified under a simulated minimal PATH.

### Extension — v0.1.1 listing refresh
- **Six listing screenshots** (sidebar, dependency graph, public-repo modal, Untracked bucket, onboarding, command menu) + the README `Screenshots` section.
- **Expanded docs**: a real **Commands & controls** section explaining every command plus **filtering** (Select View lenses) and **sorting**; an **Install** section; status → published.
- **Independent per-registry publish jobs + `--skip-duplicate`** (the resilient `vscode-publish.yml`).
- Version bumped to **0.1.1**.

### Top-level README
- `npm install -g` path in Quick install + the per-platform table; a **VS Code extension** section (Marketplace/Open VSX + cliPath); an **Updating** table; a hero screenshot.

After merge: run **npm-publish** (first `@stylusnexus/work-plan` release) and **vscode-publish** (extension `0.1.1`, now with screenshots).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+8c10fe0 — 2026-06-09 (#124)

ci(vscode): Node CI job + Marketplace/Open VSX publish scaffolding (#87 Phase 4)

Promotes the **#87 Phase 4** CI + packaging plumbing to production so the extension's publish pipeline is live on `main`.

- **`vscode.yml`** — the extension's own Node CI (typecheck · `node --test` · esbuild · `vsce package` → VSIX artifact), scoped to `vscode/**`. The Python/Node boundary.
- **`vscode-publish.yml`** — publish job (VS Code Marketplace + Open VSX), **dormant** until a Release is cut or it's dispatched manually; uses the `VSCE_PAT` / `OVSX_TOKEN` repo secrets.
- **`vscode/package.json`** — Marketplace fields (repository, icon, keywords, …) + `package`/`publish:*` scripts + `@vscode/vsce` + `ovsx` devDeps.
- **`vscode/media/icon.png`** (real raster icon) + **`vscode/LICENSE`** (packaged into the VSIX) + the AGENTS.md Python/Node boundary note.

No CLI behavior change; the viewer's runtime is unchanged from the previous deploy. Tests green (Python matrix + the new `vscode.yml` job). After this lands, a `v0.1.0` Release publishes the extension.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.07+e972a11 — 2026-06-07 (#122)

feat: ship the VS Code viewer (Phases 1–3) — see, write, and onboard work-plan tracks (#87)

First production ship of the **`work-plan` VS Code viewer** — the human face of the CLI. Everything below was merged to `dev` incrementally (each PR reviewed + tested); this deploy promotes the whole viewer (Phases 1–3) plus its CLI seam to `main`.

### The viewer (`vscode/`)
**See** — a sidebar tree (repos → tracks: status dot, open count, blocked/next hints, ⚠ badge on public repos), a Mermaid dependency graph + per-track detail panel (focus toggle), **lenses** (filter by repo / milestone / blocked), **sort** (default / blocked / most-open / name), and an **Untracked bucket** per repo (open GitHub issues that no track references — click to open, right-click to slot).

**Act** — edit fields, set-next, slot, close, refresh, reconcile (draft preview), hygiene, and new-track — every action shells to the CLI. A **public-repo confirm modal** ("Write anyway / Keep private") fires before any write into a public (or unknown-visibility) repo and re-invokes with a confirm token; private repos write straight through.

**Onboard** — a cold-start a new user can drive without the CLI: an empty-state welcome with **Add a repo** and **Set notes location** buttons. Config is auto-seeded by the CLI on first run; a loading bar shows during fetches and concurrent refreshes are coalesced (single-flight).

### The CLI seam (`skills/work-plan/`)
- **`export --json`** (schema 1) — the viewer's read surface: every frontmatter'd track + an additive `untracked` list of open-issues-in-no-track per repo; batched GraphQL issue fetch for speed.
- Generic **`set <track> field=value`**, and a **non-interactive + confirm-token mode** for `slot` / `close` / `init` / `init-repo` (explicit flags instead of `input()` prompts), plus new one-shot **`new-track`** and **`set-notes-root`** commands — so the extension drives every write headlessly.
- **`lib/write_guard`** confirm-token gate; `assume_private_when_unknown` config opt-out for all-private teams (public repos always prompt).

### Notable fixes this cycle
- **#112** repo row read "private ⚠ public" (tier + visibility conflated) → fixed.
- **#95** tree loading indicator + single-flight refresh.
- **#99** Untracked bucket (CLI + viewer).
- **#113** opt out of the confirm gate on *unknown* visibility (PUBLIC never suppressed).
- An `applyLens` fix so additive export fields (like `untracked`) survive lens filtering.

### Tests
**448** offline Python (`unittest`) + **275** TS (`node --test`) green; build clean. The Python CI matrix (3.9–3.12 × ubuntu/macos/windows) runs on this PR. A dedicated `vscode/` CI job + Marketplace / Open VSX publishing are **Phase 4** (next).

Issues shipped: #87 (Phases 1–3), #92, #93, #94, #95, #96, #99, #104, #105, #107, #108, #110, #112, #113.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.07+9f049ec — 2026-06-07 (#91)

docs+chore: public-repo doc refresh + broaden .gitignore

Docs/chore deploy (no code):
- **Broaden `.gitignore`** for a public repo: `.vscode/`, `.idea/`, `*.code-workspace`, secrets (`.env*`, `*.pem`), build/deps (`node_modules/`, `dist/`, `out/`, `*.vsix` — for the incoming `vscode/` extension), python envs, logs. Nothing tracked matched (purely preventive).
- **Architecture docs** refreshed for the plugin era (one-engine-two-faces, plugin packaging, plan-status subsystem, corrected install flows, updated counts).
- **CONTRIBUTING.md**: PRs target `dev`; CI is configured; ~250 tests; git-native sharing in-scope.
- **notes/README.md**: corrected stale default-`notes_root` premise.
- **shims**: add `plan-status`; plugin-first framing.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.07+4777cca — 2026-06-07 (#90)

chore: untrack internal planning docs from public repo + plugin-first README

Production deploy. Two things:

- **Remove `docs/superpowers/` from the public repo.** Internal planning (specs/plans/mockups) is kept local going forward — `.gitignore` now excludes `docs/superpowers/`, `docs/specs/`, `docs/plans/`. This untracks the previously-committed files from `main` (local copies retained on disk; they remain in git history, not purged).
- **Plugin-first README** — badges, quick-install (Claude/Codex plugin + script), namespacing note (`/work-plan X` → `/work-plan:X`), marketplace link.

No code changes; full offline suite green (250 + bin test). `version-bump.yml` will bump CalVer + sync the manifests on merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.07+46f9db9 — 2026-06-07 (#89)

feat(plugin): Codex plugin manifest + install-paths docs/CI

Production deploy carrying Phase 2 + Phase 3 leftovers.

- **Codex plugin manifest (#86):** `.codex-plugin/plugin.json` (with `"skills": "./skills/"`), so Codex users get a native manifest. Verified: `codex plugin add` installs it (enabled) with both skills in the cache.
- **Install docs + CI (#88):** README three-install-paths section (Claude plugin / Codex plugin / install.sh); `tests/test_bin_wrapper.py` wired into CI (Linux/macOS).

`version-bump.yml` will bump VERSION and sync **both** manifests (`.claude-plugin` + `.codex-plugin`) on merge. After this, the next tag + marketplace `ref` bump publishes the Codex manifest to installed users.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.07+80c7f8c — 2026-06-07 (#85)

feat(plugin): Claude Code plugin packaging (Phase 1) + org-sharing specs

Production deploy of the org-sharing work. Ships:

- **Phase 1 plugin packaging (#83):** `bin/work-plan` launcher, `.claude-plugin/plugin.json` (CalVer), namespaced command suite (`/work-plan:brief` …), self-seeding config, dispatcher-only `install.sh`/`install.ps1` (lockstep), Windows `.cmd` launcher.
- **version-bump manifest sync (#84):** deploys now write CalVer into the plugin manifest(s) alongside VERSION.
- **Org-sharing specs + plans + repo-local `AGENTS.md`** (docs already on dev).

Verified: 250 unit tests + bin test green; real local `marketplace add → install → details` confirmed the namespaced suite with no name collision; CalVer passes `claude plugin validate`.

Post-merge: `version-bump.yml` will bump VERSION + sync the manifest; then this work becomes taggable for the `stylusnexus/agent-plugins` marketplace.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.06+7909ca5 — 2026-06-06 (#82)

feat(status-table): sync missing canonical rows and slot them in frontmatter order (#77, #79)

Production deploy: dev → main. Ships two stacked changes to the canonical issue-table sync.

### What's shipping

- **#77 (#78)** — `refresh-md` and `handoff` now diff frontmatter `github.issues` against the status table and append a row for every newly-slotted issue (previously they only rewrote status cells of existing rows, so the body table drifted from frontmatter silently). Adds `render_issue_row`, `append_rows`, `sync_missing_rows`; live assignee fetch.
- **#79 (#81)** — `sync_missing_rows` now slots each missing row into its frontmatter-order position instead of tacking it onto the end, so the rendered table matches frontmatter ordering (Option A). Existing rows are re-emitted verbatim (minimal diff).

### Files (8)

`commands/canonicalize.py`, `commands/handoff.py`, `commands/refresh_md.py`, `lib/github_state.py`, `lib/status_table.py`, `tests/test_handoff_append_rows.py`, `tests/test_refresh_md.py`, `tests/test_status_table.py`

(The `main..dev` first-parent list shows ~40 commits — phantom diff from prior squash-merges. The genuine deploy is the 8 files above = #77 ∪ #79.)

### Tests

Full suite green (245). `cd skills/work-plan && python3 -m unittest discover tests`

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.04+38a551f — 2026-06-04 (#76)

fix(ci): deploy automation — version-bump on PR-merge, auto-CHANGELOG, docs refresh

### Deploy — fix the version-bump trigger + add auto-CHANGELOG

- **CI fix:** `version-bump.yml` now fires on `pull_request: closed (merged)` (a `gh --admin` merge doesn't emit a `push` event, which is why VERSION stalled at 2026.04.30 since deploys #65/#67/#74) + a `workflow_dispatch` manual fallback.
- **CHANGELOG:** the workflow now prepends an entry from each deploy PR's title/body; `CHANGELOG.md` seeded with the full 34-deploy backfilled history.
- **Docs:** README/SECURITY refreshed for the full plan-status surface (`--llm`, `--archive`, `--issues`, 🧳 foreign), test count 202 → 234.

Once this lands on `main`, the new trigger governs future deploys (auto VERSION bump + CHANGELOG). A manual `workflow_dispatch` will stamp today's VERSION immediately after merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.04 — 2026-06-04 (#74)

feat(plan-status): doc/plan liveness tracking (report, stamp, LLM, reconcile, foreign)

Shipped the complete `work-plan plan-status` capability: a read-only liveness report (✅ shipped / 🟡 partial / 💀 dead / 👻 manifest-less / 🧳 foreign), idempotent status-header stamping (`--stamp`), two-step LLM verdicts for prose/ambiguous docs (`--llm`), and gated reconcile actions (`--archive`, `--issues`). Phases #68, #70, #71, #72, #73.

---

### Backfilled history

_Pre-#74 deploys, reconstructed from merged PR titles._

- **2026-05-22** (#67) — fix(handoff): filter closed next_up entries from Suggested first action
- **2026-05-22** (#65) — fix(handoff): attribute commits via body issue refs, not just subject
- **2026-05-19** (#63) — feat(slot): detect prior ownership and prompt to move (#62)
- **2026-05-09** (#61) — fix(reconcile,hygiene): include PRs in label query; graceful multi-repo dupes
- **2026-05-03** (#60) — feat(brief,handoff,orient): surface milestone alongside priority (#58)
- **2026-05-03** (#59) — fix(brief,orient): surface stale closed next_up entries (#57)
- **2026-05-02** (#56) — feat(brief): scope brief and hygiene to one repo via --repo=<key>
- **2026-05-02** (#55) — docs: clarify when refresh-md is actually needed
- **2026-05-01** (#54) — feat(handoff): auto-next skips sibling-claimed issues silently
- **2026-05-01** (#52) — feat(handoff): warn on cross-track next_up collisions
- **2026-05-01** (#49) — ci: add workflow_dispatch to Tests workflow
- **2026-05-01** (#47) — feat(reconcile): clarify vs refresh-md and hint when track looks hand-curated
- **2026-05-01** (#46) — feat(handoff): attribute commits via github.paths globs + soft signal when 0 attributed
- **2026-04-30** (#45) — docs(readme): update for today's surface changes
- **2026-04-30** (#43) — feat(handoff,brief): auto-suggest next_up via --auto-next + next_up_auto
- **2026-04-30** (#40) — feat(reconcile): add --draft for non-interactive preview
- **2026-04-30** (#38) — docs(skill): add reconcile to argument-hint, bump 4→5 essentials
- **2026-04-30** (#36) — chore(reconcile,ci): lock read-only contract + Python 3.9 lint guard
- **2026-04-30** (#33) — feat(reconcile): per-track github.labels override + --reconcile short flag
- **2026-04-30** (#31) — chore(release): wire VERSION constant to a file with auto-bump on main
- **2026-04-30** (#29) — test: assert --version writes only to stdout (not stderr)
- **2026-04-30** (#27) — ci: add windows-latest runner and concurrency cancellation to Tests workflow
- **2026-04-30** (#21) — feat(work-plan): add --version/-v flag
- **2026-04-29** (#20) — docs: add SECURITY.md with reporting policy, threat model, and advisories
- **2026-04-29** (#19) — fix(security): move two-step AI subcommand state out of /tmp (#18)
- **2026-04-29** (#16) — ci: add macos-latest runner to Tests workflow
- **2026-04-29** (#12) — ci: pin mikefarah/yq to v4.53.2 in test workflow and README
- **2026-04-29** (#13) — fix(tests): use future annotations in test_where_was_i for Python 3.9
- **2026-04-29** (#10) — ci: add work-plan unittest workflow
- **2026-04-29** (#9) — docs: honest cross-LLM compatibility matrix + Cursor/Copilot shims
- **2026-04-29** (#8) — docs: add CODE_OF_CONDUCT.md (Contributor Covenant 2.1) (closes #7)
- **2026-04-29** (#2) — docs: add 'How it works' Mermaid diagram + daily rhythm
- **2026-04-29** (#1) — docs: add PR template

