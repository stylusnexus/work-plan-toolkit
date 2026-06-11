# Changelog

Production deploys, newest first. Entries below the marker are written
automatically by `.github/workflows/version-bump.yml` when a deploy PR merges
to `main` — from that PR's title and body. Don't hand-edit below the marker.

<!-- new entries inserted below -->

## 2026.06.11+60c2651 — 2026-06-11 (#276)

feat: VS Code extension 0.5.0 — issue search, daily-driver commands, lens/sort indicator

VS Code extension **0.5.0** — a daily-driver + discoverability release. Bundles four feature PRs plus a screenshot refresh.

## Highlights

- **feat(vscode): keyword issue search (#272)** — new **Search Issues…** command (title-bar `$(search)` + palette) matches issue titles across every track and the Untracked bucket with a `%wildcard%` grammar: `%depends%` (contains), `fix%` (starts-with), `%audit` (ends-with), bare word = contains; case-insensitive. Matching is client-side. Results open in a dedicated, reusable **Issue Search** tab (grouped by repo, open issues first) — click a row to open on GitHub, or use the per-row reveal button to jump to the owning track in the tree. Strict-CSP, accessible, theme-adaptive; an "as of `<generated_at>`" line + Refresh & re-run.

- **feat(vscode): daily-driver relay commands (#210)** — **Daily Brief**, **Re-orient (Where was I)**, and **Wrap Up Session (Handoff)** are now runnable from the title bar / track right-click menu / palette, relaying the CLI's verbatim output to the Work Plan output channel. Handoff routes through the public-write confirm flow.

- **feat(vscode): active lens + sort indicator (#209)** — the active filter/sort is surfaced inline under the Tracks view title (e.g. `milestone: v2.0.0 · blocked-first`), clearing when you return to All tracks + default sort.

- **fix(vscode): numeric-aware milestone sort (#268)** — milestone entries in the Select View filter now sort numerically (`v0.5.0` before `v0.10.0`) instead of issue-iteration order.

- **docs(vscode): refresh dependency-graph screenshot (#223)** — community contribution (@Hritik-Kumar-dev): neutral demo-data screenshot showing current 0.4.x/0.5.0 features.

## Versions
- VS Code extension hand-bumped **0.4.2 → 0.5.0** (`vscode/package.json`); `## Status` line + root README updated.
- CLI VERSION (CalVer) + npm version are stamped automatically on this merge.

## Verification
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

## CLI — shared-tier planning on one canonical branch (#260)

The shared (`.work-plan/`) tier can now be pinned to **one canonical `plan_branch`** per repo, read and written through a dedicated git worktree — so planning lives off your code branches and never pollutes feature PRs or the `dev → main` deploy diff, yet the CLI and viewer always show the canonical plan from any checkout.

- **`plan-branch <init|status|push> <repo>`** — the bootstrap + share command. `init` creates an **orphan** branch (default `work-plan/plan`, like `gh-pages`; `--branch` overrides) with a `.work-plan/` skeleton, or **connects** to a teammate's already-published branch — **local only**. `status` reports exists / published / unpushed. `push` shares it, gated by a confirm token on **public** repos (with `--dry-run` to preview the exposure first).
- Discovery, shared-track creation (`group`/`new-track`), and the dispatcher's auto-commit all route through the plan-branch worktree when one is configured; repos without a `plan_branch` keep the legacy working-tree `.work-plan/` behaviour unchanged.
- Hardened to the notes-vcs data-safety bar across multiple adversarial review rounds: scoped commits (only the paths a command changed, NUL-delimited porcelain so spaced/non-ASCII filenames are safe), branch-verified worktree reuse, the public-repo exposure gate fails closed, and the whole path honours the never-raise contract.

## VS Code viewer — visibility × tier badge (#259), extension 0.4.1

Every tree item now carries a **visibility × tier badge** (🔒 private / 🌐 public repo, ☁ shared tier) that flags the one **exposed** state — a plan committed to a *public* repo's shared tier is world-visible. Theme-adaptive, with a MarkdownString tooltip explaining the state.

## Docs
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

## Change
The 'Show full map' graph now only shows tracks in the **same repo** as the selected track. Cross-repo tracks share no edges, so showing them together produced noise without value.

- Focus mode: unchanged (neighbourhood of selected track)
- Full map: scoped to selected track's repo

## Version
VSCode extension → 0.3.2

## 2026.06.09+a00489a — 2026-06-09 (#176)

Deploy: Mermaid fix + move subcommand + depends_on surface (#172, #162, #102)

## Changes in this deploy

### #172 — Mermaid label escaping fix
- Replaced HTML entities with safe literal characters in `mermaidLabel`
- Mermaid 11.x's `entityDecode` was silently undoing all entity escaping, allowing `"]` sequences to break the parser
- Fix: `"` → `'`, `[{` → `(`, `]}` → `)`, backtick → `'`

### #173 — `move` subcommand + VSCode right-click
- CLI `move` subcommand (source-first: `work-plan move <issue> <from> <to>`)
- VSCode context menu "Move Issue from Track" with QuickPick destination
- Added to `WriteAction` type with full public-repo confirm gate
- 13 CLI tests + 1 VSCode test

### #175 — Surface `depends_on` in detail panel + README
- New "Depends on:" section in VSCode detail panel with clickable amber chips
- README documentation for cross-track dependencies
- 2 new detail panel tests

## Verification
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

## Deploy to production

**Commits in this deploy:**
- 736bc40 chore(vscode): bump to 0.2.1 for batch-slot publish

**Files changed:** 1 file, +1 / -1 (`vscode/package.json` version 0.2.0 → 0.2.1)

Lands the version bump that was needed to publish the VS Code extension with batch-slot support. The actual feature code shipped in #158; this aligns main with the published 0.2.1 extension.

## 2026.06.09+530f7e8 — 2026-06-09 (#158)

feat(batch-slot,tracks,vscode): batch-slot command + archived-track dedup

## Deploy to production

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

## Summary

- Adds optional `version_suffix` input to `npm-publish.yml` (e.g. `"-1"` → publishes `2026.6.9-1`)
- Allows same-day npm republish when the CalVer semver is already taken, without changing the VERSION file
- Used immediately after creation to publish `@stylusnexus/work-plan@2026.6.9-1` (CLI improvements from #151/#152 that landed after today's first npm publish)

## Migrations

None.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+f7e5ff5 — 2026-06-09 (#155)

feat(reconcile,hygiene): parallel gh fetches, per-call timeouts, progress indicators

## Summary

- **#151** `perf(reconcile,hygiene)`: parallel `gh` fetches in `reconcile --all` via `ThreadPoolExecutor` (4 workers); per-call 15s timeout per track; `--timeout=N` flag forwarded to `duplicates`; per-step timing in `hygiene`
- **#152** `feat(hygiene,reconcile,refresh-md)`: `[N/total]` progress indicator during `--all` sweeps in all three subcommands; also fixes latent `NameError` in `hygiene.py` step-2 timing (referenced `t2` before assignment)
- New test module: `test_reconcile_readonly.py` — timeout/skip behaviour for single-track and multi-track parallel paths

## Commits

```
8e8a29f feat(hygiene,reconcile): per-track progress indicator during --all sweep (#152) (#154)
2332c49 perf(reconcile,hygiene): parallel gh fetches + per-call timeout (#151) (#153)
```

## Migrations

None.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+ac8a3d7 — 2026-06-09 (#150)

docs(readme,skill): clarify refresh-md and hygiene, add read-only callout, vscode README v0.2.0

## Summary

- **SKILL.md + README.md**: rewrote `refresh-md` guidance — removed "you usually don't need this" framing; it's the right tool to run after closing issues. Expanded `hygiene` description to enumerate all three steps (refresh-md + reconcile + duplicates).
- **README.md + vscode/README.md**: added explicit GitHub read-only callout — the toolkit never writes to GitHub; all writes are local markdown files only.
- **vscode/README.md**: added `workPlan.autoRefreshInterval` to the configuration table; bumped Status line from v0.1.0 → v0.2.0 with feature summary.

## Commits

- docs: clarify refresh-md vs hygiene, add read-only callout, vscode README v0.2.0 (#149)

## Test plan
- [ ] README.md hygiene row enumerates all 3 steps
- [ ] SKILL.md refresh-md row says "run after closing issues"
- [ ] vscode/README.md config table includes autoRefreshInterval
- [ ] Read-only GitHub note present in both READMEs
- [ ] Status line in vscode/README.md reads v0.2.0

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+5d07d27 — 2026-06-09 (#148)

feat(viewer): auto-refresh, shared-track tier badge, welcome fix + README settings table

## Summary
- **#134 `workPlan.autoRefreshInterval`** — silent background poll on a user-configured interval (0=off, 30s/1m/5m/15m dropdown); timer restarts on config change
- **#137 Tier badge** — shared tracks show `shared N open` in the tree description; tooltip clarifies shared vs private
- **#118 Welcome state fix** — `viewsWelcome` now gated on `workPlanHasRepos` context key (driven from unfiltered data) so a lens that hides all tracks doesn't show "No repos yet"
- **Docs** — VS Code settings table in README; agent-plugins description updated for shared tracks + coverage/auto-triage

Bumps VS Code extension to **v0.2.0**.

## Commits
- feat(viewer): auto-refresh interval setting (#134) (#145)
- feat(viewer): tier badge on shared tracks + welcome state fix (#137, #118) (#146)
- docs: VS Code settings table + tier badge note in README (#147)
- test: fix Windows path separator in test_group_apply + test_init_repo

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+21c63ea — 2026-06-09 (#144)

feat(shared-notes,coverage,auto-triage): two-tier tracks, coverage report, AI triage, next_up fix

## What's shipping

### Major: shared-notes (two-tier track storage)
Track files can now live inside a repo clone (`.work-plan/<slug>.md`, git-synced) alongside the existing private `notes_root` tier. Register a local clone with `init-repo --local=<path>`; tracks route there automatically. Teammates share planning state via `git pull`/`git push`. `--private` opts out per-command.

Phases A–D:
- Phase A: `discover_tracks` unions shared + private; `AmbiguousTrackError` for same-slug-different-repo
- Phase B: `--repo=<key>` / `<track>@<repo>` disambiguation on all write verbs
- Phase C: write-surface routing (`group`, `new-track`, `close`, `init`)
- Phase D: `init-repo` detects existing `.work-plan/` tracks; `new-track --commit`; `export` tier field

### New: `coverage` command
`/work-plan coverage [--repo=<key>] [--list]` — reports how many open issues are outside the track model. 42% orphan rate measured on a real production repo.

### New: `auto-triage` command
`/work-plan auto-triage [--repo=<key>] [--apply]` — two-step AI assignment of untracked issues to existing tracks. Complements `group` (which creates new tracks).

### Fix: closed issues filtered from `next_up` in export
The VS Code viewer was showing closed issues as actionable next-up nodes. Export now cross-references `next_up` against the fetched issue states and removes confirmed-closed entries.

### Docs
README, SKILL.md, npm description, and VS Code extension description updated with shared-notes setup, group/auto-triage callouts, and `@repo` disambiguation syntax.

---

PRs: #129 (shared-notes phases A–D via #132 #133 #135 #138), #139 (next_up fix), #141 (coverage), #142 (auto-triage), #143 (docs)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.09+f3bc861 — 2026-06-09 (#128)

feat: npm CLI distribution + launcher PATH fix + extension v0.1.1 (screenshots, docs)

Production deploy bundling the post-launch polish: npm distribution for the CLI, the GUI-PATH launcher fix, expanded docs, and the assets/version bump for the extension's `0.1.1` listing refresh.

## CLI — npm distribution
- **`@stylusnexus/work-plan` npm package** (root `package.json` + `scripts/npm-check-deps.js`): ships the Python CLI + launcher so `npm install -g @stylusnexus/work-plan` works (no repo clone). `files`-whitelisted (488 kB, no leaks); pure Python still, no build step. Plus `.github/workflows/npm-publish.yml` (CalVer→semver, `--access public`, `NPM_TOKEN`).
- **Launcher GUI-PATH fix** (`bin/work-plan`): GUI editors (VS Code from Finder/Dock) inherit a stripped PATH without Homebrew, so the CLI's `yq`/`gh` lookups failed and the viewer showed an empty tree. The launcher now prepends `/opt/homebrew/bin:/usr/local/bin`, and resolves symlinks (so the npm global-bin symlink finds its Python). Verified under a simulated minimal PATH.

## Extension — v0.1.1 listing refresh
- **Six listing screenshots** (sidebar, dependency graph, public-repo modal, Untracked bucket, onboarding, command menu) + the README `Screenshots` section.
- **Expanded docs**: a real **Commands & controls** section explaining every command plus **filtering** (Select View lenses) and **sorting**; an **Install** section; status → published.
- **Independent per-registry publish jobs + `--skip-duplicate`** (the resilient `vscode-publish.yml`).
- Version bumped to **0.1.1**.

## Top-level README
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

## The viewer (`vscode/`)
**See** — a sidebar tree (repos → tracks: status dot, open count, blocked/next hints, ⚠ badge on public repos), a Mermaid dependency graph + per-track detail panel (focus toggle), **lenses** (filter by repo / milestone / blocked), **sort** (default / blocked / most-open / name), and an **Untracked bucket** per repo (open GitHub issues that no track references — click to open, right-click to slot).

**Act** — edit fields, set-next, slot, close, refresh, reconcile (draft preview), hygiene, and new-track — every action shells to the CLI. A **public-repo confirm modal** ("Write anyway / Keep private") fires before any write into a public (or unknown-visibility) repo and re-invokes with a confirm token; private repos write straight through.

**Onboard** — a cold-start a new user can drive without the CLI: an empty-state welcome with **Add a repo** and **Set notes location** buttons. Config is auto-seeded by the CLI on first run; a loading bar shows during fetches and concurrent refreshes are coalesced (single-flight).

## The CLI seam (`skills/work-plan/`)
- **`export --json`** (schema 1) — the viewer's read surface: every frontmatter'd track + an additive `untracked` list of open-issues-in-no-track per repo; batched GraphQL issue fetch for speed.
- Generic **`set <track> field=value`**, and a **non-interactive + confirm-token mode** for `slot` / `close` / `init` / `init-repo` (explicit flags instead of `input()` prompts), plus new one-shot **`new-track`** and **`set-notes-root`** commands — so the extension drives every write headlessly.
- **`lib/write_guard`** confirm-token gate; `assume_private_when_unknown` config opt-out for all-private teams (public repos always prompt).

## Notable fixes this cycle
- **#112** repo row read "private ⚠ public" (tier + visibility conflated) → fixed.
- **#95** tree loading indicator + single-flight refresh.
- **#99** Untracked bucket (CLI + viewer).
- **#113** opt out of the confirm gate on *unknown* visibility (PUBLIC never suppressed).
- An `applyLens` fix so additive export fields (like `untracked`) survive lens filtering.

## Tests
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

## What's shipping

- **#77 (#78)** — `refresh-md` and `handoff` now diff frontmatter `github.issues` against the status table and append a row for every newly-slotted issue (previously they only rewrote status cells of existing rows, so the body table drifted from frontmatter silently). Adds `render_issue_row`, `append_rows`, `sync_missing_rows`; live assignee fetch.
- **#79 (#81)** — `sync_missing_rows` now slots each missing row into its frontmatter-order position instead of tacking it onto the end, so the rendered table matches frontmatter ordering (Option A). Existing rows are re-emitted verbatim (minimal diff).

## Files (8)

`commands/canonicalize.py`, `commands/handoff.py`, `commands/refresh_md.py`, `lib/github_state.py`, `lib/status_table.py`, `tests/test_handoff_append_rows.py`, `tests/test_refresh_md.py`, `tests/test_status_table.py`

(The `main..dev` first-parent list shows ~40 commits — phantom diff from prior squash-merges. The genuine deploy is the 8 files above = #77 ∪ #79.)

## Tests

Full suite green (245). `cd skills/work-plan && python3 -m unittest discover tests`

🤖 Generated with [Claude Code](https://claude.com/claude-code)

## 2026.06.04+38a551f — 2026-06-04 (#76)

fix(ci): deploy automation — version-bump on PR-merge, auto-CHANGELOG, docs refresh

## Deploy — fix the version-bump trigger + add auto-CHANGELOG

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

