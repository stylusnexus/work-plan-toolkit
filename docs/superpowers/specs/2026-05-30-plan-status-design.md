# Plan Status — Doc & Plan Liveness Tracking

> **For agentic workers:** This is a design spec (the *why* and *what*), not an implementation
> plan. The bite-sized *how* gets written next via the writing-plans skill into
> `docs/superpowers/plans/`. This doc is also test case #1 for the tool it describes:
> the plan-status command should eventually reach a verdict on *this very file*.

**Date:** 2026-05-30
**Status:** Drafted — awaiting review
**Owner:** Eve McGivern (Stylus Nexus)
**Feature home:** `work-plan-toolkit` → new `work-plan` subcommand `plan-status`

---

## Plain-English summary (read this even if you never read code)

We write a lot of plans and design docs — especially through the superpowers
brainstorming → writing-plans → executing flow. They produce genuinely good documents.
Then those documents go into a repo and **die quietly**. Months later nobody can tell
what got built, what's half-done, and what was abandoned.

The reason this is so hard to eyeball turns out to be specific and measurable: the
**checkboxes lie.** A plan's `- [ ]` / `- [x]` boxes are supposed to say "done," but the
agent that executes the plan tracks its progress in a scratchpad (TodoWrite), not by
editing the file. So the boxes stay empty even when the whole feature shipped.

On CritForge — one repo — we measured it: **130 of 152 plans (85%) show fewer than 25% of
their boxes checked, yet have 80%+ of the files they promised to create already sitting on
disk.** They look untouched. They actually shipped. The checkboxes are noise.

The fix exploits a quieter, *honest* signal. The writing-plans skill forbids vague
placeholders and forces every plan to name **exact file paths** it will create, modify, and
test. That makes every plan secretly a **manifest of files that should exist.** We don't
need to trust the checkboxes — we ask git and the filesystem: *of the files this plan
promised, how many now exist and were committed?* That number is the real completion, and
it can be computed mechanically, for free, with no AI, for ~98% of plans.

The tool — `plan-status` — does this for one repo at a time. You point it at a repo
("clean up CritForge"), and it reaches a **decision on every doc**: shipped, partial, dead,
or orphaned. For the rare prose document that has no file-manifest (a freeform design doc),
an AI pass reads it against the git evidence and decides — so nothing is left in limbo. The
decision gets **written back into the doc itself** as a small status header, so the truth
finally lives next to the plan instead of in your head. Optionally, with confirmation, it
cleans up: ticks the boxes whose files demonstrably exist, opens issues for genuinely
unfinished work, and archives the dead ones.

It ships in phases, smallest-useful-first: a read-only report you can trust before you let
it touch anything, then stamping, then the cleanup actions. It's a plain Python subcommand
(no new dependencies), and it emits JSON so that *later*, if it's worth selling or sharing,
a VS Code panel or MCP server can wrap the same engine without a rewrite.

---

## Problem statement

Documents produced by planning workflows accumulate in repos with no reliable signal of
completion. The canonical "done" signal — checkbox state in plan files — is unreliable
because plan execution tracks progress out-of-band (TodoWrite / subagent state) and rarely
writes back to the markdown.

### Evidence (CritForge, measured 2026-05-30)

| Metric | Value |
|---|---|
| Superpowers plans analyzed | 152 |
| Plans with a parseable file-manifest | 150 (98.7%) |
| Plans with **no** manifest (prose) | 2 (1.3%) |
| Total checkboxes across plans | ~6,600 |
| Checked | ~250 (≈4%) |
| **"Lie gap": <25% boxes checked but ≥80% declared files present** | **130 / 152 (85%)** |

Parallel corpora in the same repo compound the problem: `docs/plans/` (174 files,
design+plan pairs) and `.spec-workflow/` (3,585 markdown files). The pattern repeats across
50+ repos in the workspace.

### Root cause

Checkbox state measures *whether the executor edited the file*, not *whether the work
happened*. The honest signal is the **file-manifest**: writing-plans mandates exact
`Create:` / `Modify:` / `Test:` paths and forbids placeholders, so each plan declares the
files that must exist when it's complete.

---

## Goals

- **Completeness contract:** pointed at one repo, reach a verdict on *every* discovered
  plan/spec/design doc. No doc left undecided.
- **Trustworthy detection:** derive completion from git + filesystem evidence (the
  file-manifest), not from checkboxes.
- **The doc is the ledger:** persist each verdict as an idempotent status header inside the
  doc. No separate cache or mirror of state (consistent with the toolkit's "GitHub/git is
  canonical, don't cache" philosophy).
- **Gated reconciliation:** optionally close the gap — tick demonstrable boxes, open issues
  for unfinished remainder, archive dead docs — never without confirmation.
- **Wrappable core:** emit JSON so a future MCP server or VS Code extension can render the
  same engine output.

## Non-goals

- **Not** a cross-repo simultaneous dashboard. Unit of operation is one repo; "all repos" =
  run N times.
- **Not** a replacement for GitHub issue state. Issues remain canonical for tracked work.
- **Not** a VS Code extension or MCP server in v1. Those are deferred delivery skins (Phase 4).
- **Not** a generic documentation linter. Scope is plan/spec/design liveness.
- **Not** a prescriber of automation. The tool exposes a fast, scriptable command; *how* it
  gets triggered (git hook, manual) is the user's choice (see "Prevention").

This tool is **git-native by design** — it lives in `work-plan-toolkit`, whose entire model
assumes git + GitHub. Git is a hard dependency here, not an enhancement.

---

## Design

### Unit of operation

One repository, resolved from `--repo <key>` (config lookup) or the current working
directory. All discovery, evidence-gathering, and stamping are scoped to that repo's git
tree.

### Doc taxonomy and detection signal

| Doc type | Locations (defaults, configurable) | Manifest? | Primary signal |
|---|---|---|---|
| Superpowers **plan** | `docs/superpowers/plans/*.md` | Yes | **File-manifest correlation** (mechanical) |
| **Design spec** (prose) | `docs/superpowers/specs/*.md`, `docs/plans/*-design.md` | No | Matching plan's verdict + feature git footprint → LLM verdict |
| **spec-workflow** | `.spec-workflow/specs/**` | Partial | Task-status fields + git footprint |
| **Ad-hoc** plan/design `.md` | repo-configured globs | Usually no | LLM verdict against git evidence |

Discovery globs live in config so a repo that puts plans elsewhere can be onboarded without
code changes.

### Manifest correlation (the mechanical spine)

For each plan:

1. **Parse declared paths** from `Create:` / `Modify:` / `Test:` lines (backtick-quoted;
   strip trailing `:line-range`).
2. **Derive the plan's reference date** from the `YYYY-MM-DD` filename prefix (fallback:
   first git commit touching the file).
3. **Score each path by kind** — existence alone is not enough, because `Modify:` targets
   usually pre-existed:
   - `Create:` → **exists on disk now?** (clean yes/no)
   - `Test:` → exists on disk now?
   - `Modify:` → **was the path committed *after* the plan's reference date?** (`git log
     --since -- path`) — existence proves nothing for a pre-existing file.
4. **Completion %** = satisfied paths ÷ declared paths, reported with the Create/Modify/Test
   breakdown so a Modify-heavy plan isn't misread.
5. **Liveness** = newest last-commit date across declared paths (dead = 0 satisfied AND no
   referenced path committed in N days; N configurable).

> The 2026-05-30 probe scored Create/Test by existence only and still cleanly classified
> 150/152 plans, because these plans are Create-heavy. The shipped tool adds the `Modify:`
> git-log correlation so Modify-heavy plans are scored correctly.

### LLM-deepening (the scalpel)

Every manifest-less doc (prose specs, ad-hoc) is routed to the LLM pass — per the decision
that the completeness contract admits **no "undecided" bucket**. Mechanism mirrors the
existing two-step subcommands (`group`, `suggest-priorities`):

1. CLI gathers the doc text + git evidence (matching plan verdict, feature footprint,
   referenced-symbol presence) and writes a prompt.
2. The model emits JSON: `{verdict, confidence, one_line_rationale}` per doc, saved via the
   Write tool to `~/.claude/work-plan/cache/plan_status.answers.json`.
3. CLI re-run with `--apply` consumes the JSON and stamps verdicts.

On a real repo this is a small set (CritForge: 2 of 152 plans), so cost stays low even with
"resolve every prose doc."

### Verdict states

| Verdict | Evidence | Glyph |
|---|---|---|
| **shipped (boxes stale)** | all/nearly-all declared paths satisfied | ✅ |
| **partial** | some declared paths satisfied | 🟡 |
| **dead** | 0 satisfied, untouched > N days | 💀 |
| **orphaned spec** | prose doc, no matching plan, no git footprint | 👻 |

### The ledger: status header stamping

Each doc carries its own verdict as an **idempotent** block (rewritten in place, never
appended twice), e.g.:

```markdown
<!-- plan-status: BEGIN -->
> **Status:** ✅ shipped (boxes stale) · files 17/17 present · last touched 2026-04-02 · stamped 2026-05-30
<!-- plan-status: END -->
```

Re-running re-derives evidence and only flips the verdict when evidence changed. This makes
the doc self-describing and removes any need for a separate state store.

### Reconcile actions (Phase 3, all confirmation-gated)

| Verdict | Offered action |
|---|---|
| ✅ shipped | tick checkboxes whose `Create:`/`Test:` files demonstrably exist; offer archive |
| 🟡 partial | stamp the gap; offer to open a GitHub issue listing unsatisfied paths |
| 💀 dead | offer to move to `docs/superpowers/plans/archive/abandoned/` |
| 👻 orphaned | flag for human decision (keep / write plan / kill) — never auto-acted |

Box-ticking only flips boxes whose corresponding file is proven present — it never marks a
step done on inference alone.

### Command surface

```
work-plan plan-status [--repo <key>] [--json] [--apply] [--draft] [--since-days N] [--type plan|spec|all]
```

- Default: human-readable report (paste-able verbatim, like `brief` / `handoff`).
- `--json`: machine output for future wrappers (Phase 4).
- `--apply`: consume LLM answers + execute gated reconcile actions.
- `--draft`: preview proposed stamps/actions without writing (mirrors `reconcile --draft`).
- Registered in **both** `SUBCOMMANDS` and `DESCRIPTIONS` in `work_plan.py` (help is
  hand-written).

### Architecture fit

- `commands/plan_status.py` — thin orchestration (`run(args) -> int`).
- `lib/doc_discovery.py` — walk configured globs → `Doc` dataclasses.
- `lib/manifest.py` — parse declared paths, score against disk + git.
- `lib/verdict.py` — pure verdict logic over gathered evidence (no I/O → easily unit-tested).
- `lib/status_header.py` — idempotent stamp read/write.
- Reuses existing `lib/git_state.py`, `lib/github_state.py`, `lib/frontmatter.py`,
  `lib/config.py`, `lib/prompts.py`.

Hard constraints honored: **pure Python 3.9+ stdlib**, all git/GitHub via `git`/`gh`
subprocess, tests mock all subprocess calls (offline), `yq` = mikefarah/yq.

---

## Prevention — keeping docs alive (the other half)

Detection (above) is the *cure*. Prevention is stopping the graveyard from growing. Two
principles, both preserved:

1. **Never modify the user's instruction files.** `CLAUDE.md` / `AGENTS.md` are user-owned;
   documented best practice is that tooling *complements* them, never scribbles into them.
   The tool writes its verdicts into the *plan docs* (the stamp header), never into
   instruction files.
2. **Run the tool, not the agent's discipline.** Whatever the trigger, it invokes the
   command — never relies on an agent hand-ticking boxes (measured failing ~96% of the
   time).

Since this tool is git-native, the natural, self-contained trigger is a **git `post-merge`
hook** that runs `plan-status` (Phase 1) / the stamp (Phase 2) on the repo. `post-merge` is
a sharp signal — "a branch just merged" is exactly when a plan typically completes. It lives
in git plumbing, touches no instruction file, and is opt-in (offered by the tool's install /
`init-repo`, wiring `core.hooksPath`; never auto-installed). The skill's own `SKILL.md`
description supplies the soft, zero-footprint nudge for interactive Claude sessions ("use
when starting or ending a work session"). A Claude `SessionEnd` hook is an optional
convenience layer, not the backbone.

Prevention is its own small piece built alongside Phase 2 — **not part of Phase 1**.

---

## Phasing

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **1** | Read-only report: discover → classify → manifest-correlate → verdict. No mutation. | Run against CritForge; verdicts match known ground truth for a sampled set; the 130 lie-gap plans report ✅. |
| **2** | Status-header stamping + demonstrable-box ticking. Idempotent. | Re-running produces zero spurious diffs; headers update only on evidence change. |
| **3** | Gated reconcile actions (archive, open issues). | Each action requires confirmation; dry-run (`--draft`) preview available; CritForge graveyard reconciled. |
| **4 (deferred)** | JSON consumers: MCP server / VS Code panel. | Out of scope for now; `--json` contract is the seam. |

---

## Test cases (plain English)

**Manifest parsing**
- Extracts `Create:`/`Modify:`/`Test:` paths from backtick-quoted lines.
- Strips a trailing `:120-145` line range before checking existence.
- Ignores non-path backticks (commands, URLs, type names).
- A plan with zero declared paths is classified as manifest-less (routes to LLM).

**Manifest scoring**
- `Create:` path that exists → satisfied; missing → unsatisfied.
- `Modify:` path committed after the plan date → satisfied; pre-existing but untouched
  since → unsatisfied (existence alone does not satisfy a Modify).
- Completion % reports the Create/Modify/Test breakdown.

**Verdict logic** (pure, no I/O)
- All paths satisfied + boxes <25% → ✅ shipped (boxes stale).
- Some satisfied → 🟡 partial.
- Zero satisfied + untouched beyond threshold → 💀 dead.
- Prose doc, no matching plan, no footprint → 👻 orphaned.

**Status header (idempotency)**
- First stamp inserts a BEGIN/END block.
- Re-stamp with identical evidence leaves the file byte-identical.
- Re-stamp with changed evidence rewrites only the block, not the doc body.

**Discovery**
- Honors configured globs per repo; a repo with plans in a non-default dir is found.
- `--repo` resolves via config; bare invocation uses cwd's repo.

**Reconcile (gated)**
- Box-ticking flips only boxes whose file is proven present; never on inference.
- Archive/issue actions are skipped without confirmation; `--draft` previews without writing.

---

## Risks & open questions

- **Modify-heavy plans:** existence under-counts; mitigated by git-log correlation, but
  squash-merges can blur per-file dates. Mitigation: fall back to plan-date vs. file
  last-commit, accept some fuzziness, surface confidence.
- **Renamed/moved files:** a declared path that was later renamed reads as missing. Phase 1
  accepts this as a false-"partial"; a later pass could consult `git log --follow`.
- **spec-workflow scale:** 3,585 files in one repo — discovery must be cheap and the LLM
  pass must not fan out over auto-generated task files. Mitigation: classify spec-workflow
  task files as a group via their status fields, not per-file LLM.
- **Stamping prose docs:** acceptable to write a status header into a human-authored design
  doc? Assumed yes (idempotent, clearly delimited); confirm during review.
- **Cross-tool box-ticking:** should Phase 3 ticking write back to plans the executor will
  never re-read? Low risk (idempotent), but note for review.

---

## Validation corpus

**CritForge is intentionally left un-cleaned.** Its 152 plans (130 in the lie gap) are the
ground-truth fixture for Phases 1–3: Eve knows which features shipped, so verdicts can be
checked against reality, and the graveyard is the only realistic test of the reconcile
actions. Manual cleanup is deferred until the tool can do it.
