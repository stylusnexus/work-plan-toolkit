# Usage Examples

End-to-end scenarios showing the four core commands in real workflow contexts.

## Scenario 1: Morning brief — multi-track overview

You wake up. You have three active tracks across two repos. You want to know what's worth opening first.

```bash
/work-plan brief
```

Output (representative):

```
=== work-plan brief — 2026-04-28 (Tue) ===

myproject — 2 active tracks
  P0  v1.0.0  ux-redesign       last touched 4h ago, 3 commits ahead, 32 issues open
  P1  v1.0.0  api-overhaul      last touched 2d ago, no in-flight work, 8 issues open

other-repo — 1 active track
  P0  v0.5.0  payment-rewrite   last touched 1d ago, 1 commit ahead, 4 issues open

Suggested first move: continue ux-redesign (most recent activity, P0)
```

The brief sorts by priority, surfaces the freshest work, and recommends a starting track. Drop into whichever feels right.

## Scenario 2: End of work block — handoff

You spent two hours on `ux-redesign` and shipped a fix. Time to wrap up so a future session (or you tomorrow) can pick up cleanly.

```bash
/work-plan handoff ux-redesign
```

The handoff:

1. Derives what you touched (commits attributed via issue numbers in messages, in-flight branch state)
2. Writes a `### Session — <ts>` entry to the track body
3. Has Claude pick `next_up` based on track priority + open items + project memory (e.g., "this issue gates a held deploy")
4. Persists the pick via `--set-next` so `orient` will surface it later

Output (representative):

```
======================================================================
HANDOFF — ux-redesign
======================================================================
Last handoff: 2026-04-28T18:42  (just now)

WHERE YOU LEFT OFF:
  - Touched: #4148 fix(dashboard): CreditsPill super admin shows '0 generations left'
  - Closed since last handoff: #4148 (merged)

WHAT'S STILL OPEN:
  (31 item(s), source: GitHub)
    🔲 #4149 fix(dashboard): Studio tier should show 'Unlimited'
    🔲 #4150 fix(error): /contact 404 — replace with form
    ... and 29 more

WHAT'S NEXT (Claude's pick):
  → #4167  feat(library): Armory Slice 3 — ArmoryCard + data-source cutover
           (unblocks held #4164 Slice 2 deploy per project memory)

✓ Session log appended.
✓ next_up set to: [4167, 4149, 4150]
```

## Scenario 3: Fresh session — orient

You open a brand-new Claude Code terminal to attack `ux-redesign`. You need full context fast.

```bash
/work-plan orient ux-redesign
```

Output:

```
─── ux-redesign ─────────────────────────────────────────
Priority: P0  ·  Milestone: v1.0.0  ·  Repo: your-org/myproject
Track:  /your/notes_root/myproject/ux-redesign.md
Local:  /path/to/local/checkout

Last session (2026-04-28 18:42):
  Touched: #4148 (merged) — CreditsPill super admin fix

Next pick: #4167  feat(library): Armory Slice 3 — ArmoryCard + data-source cutover

Behind it:
  #4149  fix(dashboard): Studio tier should show 'Unlimited'
  #4150  fix(error): /contact 404 — replace with form

Local: on feat/4148-creditspill-fix (3 ahead of dev, 0 uncommitted)
─────────────────────────────────────────────────────────
```

~15 lines. Copy-paste into the new session's first prompt and it has everything: where you were, what's next, what's behind it, your git state. No hunting through 100 issue lines for the actionable signal.

## Scenario 4: Friday cleanup — hygiene

Friday afternoon. You haven't touched two of your tracks in a week. Some issues you've worked on closed without being marked, some new issues piled up that should be slotted, and you suspect a couple of duplicate issues snuck in.

```bash
/work-plan hygiene
```

This runs three things in sequence:

1. **`refresh-md --all`** — Walks every active track, syncs canonical-table status icons (🔲 → ✅) for issues that closed since last refresh.
2. **`reconcile --all`** — Cross-checks `track/<slug>` GitHub labels against each track's `github.issues` frontmatter list. Adds labeled-but-missing issues, flags listed-but-unlabeled.
3. **`duplicates`** — Title-similarity scan (stdlib `difflib`) across all open issues. Prints suggested `gh issue close ... --reason "duplicate of #X"` consolidation commands.

Run on Fridays before you log off. Takes ~30 seconds for a 10-track / 200-issue repo.

## Bonus: slotting a new issue

You filed a new issue mid-day and want to make sure it's tracked.

```bash
/work-plan slot 4258
```

Lists active tracks, you pick one, the issue gets added to that track's frontmatter `github.issues` list. If you know the track name:

```bash
/work-plan slot 4258 ux-redesign
```

…skips the prompt.

## Bonus: closing a track

Track is done.

```bash
/work-plan close ux-redesign
```

Asks: shipped / parked / abandoned. Shipped and abandoned move the file under `archive/<state>/`. Parked stays in place with `status: parked` in frontmatter so you can resume.
