# Changelog

Production deploys, newest first. Entries below the marker are written
automatically by `.github/workflows/version-bump.yml` when a deploy PR merges
to `main` — from that PR's title and body. Don't hand-edit below the marker.

<!-- new entries inserted below -->

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

