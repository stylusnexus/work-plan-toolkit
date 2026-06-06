# Org Sharing — Shared Track Notes (Per-Repo `.work-plan/`)

> **For agentic workers:** This is a design spec (the *why* and *what*), not an implementation
> plan. The bite-sized *how* gets written next via the writing-plans skill into
> `docs/superpowers/plans/`. This is the **second of two** org-sharing specs — the
> *data-sharing* half. The sibling, *tool-sharing*, is
> `docs/superpowers/specs/2026-06-05-org-sharing-plugin-packaging-design.md` and is assumed
> done/independent here.

**Date:** 2026-06-05
**Status:** Drafted — awaiting review
**Owner:** Eve McGivern (Stylus Nexus)
**Feature home:** `work-plan-toolkit` → `lib/config.py`, `lib/tracks.py`, `lib/github_state.py`,
and the track-writing commands (`init-repo`, `slot`, `handoff`, `close`).

---

## Plain-English summary (read this even if you never read code)

Spec #1 made sure everyone runs the *same* `/work-plan` tool. This spec makes sure everyone can
see the *same plans*.

Today your planning "tracks" — the little YAML-headed markdown files that point at GitHub issues —
all live in **one private folder on your machine** (`Project Notes/`). Nobody else can see them,
and they don't travel with the code they describe. If you switch laptops, or a teammate clones the
repo, the tracks aren't there.

The change: let a track live **inside the repo it's about**, in a hidden, committed `.work-plan/`
folder. Anyone who clones that repo gets the same tracks, kept in sync by ordinary `git pull` —
the same mechanism `plan-status` already uses to ship its verdicts. Your existing private folder
keeps working unchanged for anything you *don't* want to commit; it becomes the "private tier."

Two guardrails make this safe and friendly. Because some repos are **public**, the tool gives you
a **heads-up before it writes a track into a public repo**, so you never leak planning by accident.
And every `.work-plan/` folder gets a short **README** explaining what it is and linking to the
toolkit — so a stranger (or future-you) browsing the repo isn't baffled by a mystery folder, and
can install `/work-plan` themselves.

This is solo-first by design: today there is effectively one user. The two-tier model isn't about
merging a team's data — it's a **privacy switch** (which tracks ride along in the repo vs. stay on
my machine) that *also* makes the future multi-developer story work with no rewrite.

---

## Problem statement

`config.notes_root` is a single per-user directory. `discover_tracks` walks it recursively and
treats the first path component as a repo key (`notes_root/<folder>/<track>.md` → `repos.<folder>`).
The track files are therefore:

1. **Per-user** — they exist only on the machine whose `notes_root` holds them.
2. **Detached from the code** — a track describing CritForge lives in `Project Notes/critforge/`,
   not in CritForge, so cloning CritForge gives you none of its planning context.
3. **Untravelled** — there is no sync path. A second machine, or a teammate, starts from nothing.

`plan-status` already solved the *verdict* half of data-sharing: it derives liveness live from each
repo's git (no cache) and `--stamp`/`--archive` **commit into the repo**, so verdicts travel via
`git pull`. The remaining gap is the **tracks themselves** — the planning layer above issues — which
never learned to live in the repo.

### Current visibility reality (measured 2026-06-05)

| Repo | Visibility |
|---|---|
| `stylusnexus/work-plan-toolkit` | PUBLIC |
| `stylusnexus/CritForge` | PRIVATE |
| `stylusnexus/discogorama-recs` | PRIVATE |

This mix is why "just commit tracks into every repo" is wrong: committing a track into
work-plan-toolkit would publish planning notes into a public history permanently. Visibility, not
team-merge semantics, is the dominant design force for a solo user.

---

## Goals

1. A track can live in its repo at `<repo>/.work-plan/<track>.md`, committed, travelling via git.
2. Cloning a repo (on a new machine or by a teammate) surfaces that repo's tracks with no extra
   setup beyond registering the clone.
3. The existing private `notes_root` keeps working unchanged, as the "private tier."
4. The tool never writes planning into a **public** repo without a visible heads-up.
5. Every `.work-plan/` folder is self-describing (README) and points to the toolkit.
6. No new required config key; no caching of GitHub state; pure-stdlib constraint preserved.
7. `--private` (and the shared-vs-private model it controls) is **clearly documented** in the
   plugin repo's user-facing docs and surfaced in the setup flow — not a hidden flag.

## Non-goals

- **Removing `notes_root`.** It is the private tier, not legacy-to-delete.
- **A mandatory migration.** Moving existing `Project Notes/<folder>/*` into repos is an *optional*
  follow-on helper, not part of this spec's required surface.
- **Sharing `config.yml` itself.** Local clone paths are inherently machine-specific; the shared
  artifact is the committed `.work-plan/` content, not the config.
- **Multi-writer conflict resolution beyond git.** Two people editing the same track is resolved by
  ordinary git merge, like any other committed file. No locking, no CRDT.
- **Auto-discovering repos from a workspace root.** Config still registers repos. (Possible future.)

---

## Design

### Two-tier notes model

```
SHARED tier  (committed, travels with code):   <local-clone>/.work-plan/<track>.md
PRIVATE tier (personal, uncommitted):          <notes_root>/<folder>/<track>.md   (unchanged)
```

- A repo's **shared dir** is derived from the existing `repos.<folder>.local` path plus the
  constant subdir `.work-plan/`. **No new required config key.** (Optional override
  `repos.<folder>.notes_dir` and/or a global `notes_subdir` default are allowed but not required;
  default is `.work-plan`.)
- A repo with **no `local` clone** registered contributes no shared tracks — it simply isn't walked
  (no error). You see shared tracks only for repos you've cloned and registered. This is the
  intended access model.
- `notes_root` is unchanged and remains the private tier and the safe default for repos you don't
  want to expose.

### Discovery — union with tier tagging (`lib/tracks.py`)

`discover_tracks(cfg)` becomes a **union of two sources**:

1. **Shared:** for each `repos.<folder>` with a `local` path, walk `<local>/.work-plan/` for
   `*.md` (skipping `archive/`, dotfiles, and `README.md`).
2. **Private:** walk `notes_root` exactly as today.

Each `Track` gains a `tier: "shared" | "private"` field (and keeps `path`, so the source is always
recoverable). Results are **deduped by `(repo, track-name)`**; on a true collision, the **shared**
copy wins and the CLI emits a one-line warning naming both paths (drift the user should resolve).
`brief`, `filter_tracks_by_repo`, `find_track_by_name`, `discover_archived_tracks` all operate on
the merged list and need no signature changes — only the construction of the list changes.

The folder→repo mapping for shared tracks is **direct** (the track came from `repos.<folder>`'s
clone), removing the `notes_root`-relative inference for that tier; frontmatter `github.repo` still
takes precedence where present, matching current `_build_track` behavior.

### Write routing + public heads-up (`commands/*`, `lib/github_state.py`)

- **Default destination for a new track is the repo's shared `.work-plan/`** — sharing is the
  feature's purpose. `--private` routes the write to `notes_root` instead (and skips the heads-up).
- Before the CLI **writes or commits** a track into a repo it detects as **PUBLIC**, it prints a
  one-line heads-up, e.g. `heads-up: <repo> is PUBLIC — this track will be committed publicly
  (use --private to keep it local)`. **Non-blocking** — a heads-up, not a gate. The user stays in
  control; the goal is "never leak by accident," not "forbid."
- Visibility is read via a new `lib/github_state.repo_visibility(repo) -> "PUBLIC"|"PRIVATE"|None`
  (`gh repo view <repo> --json visibility`), one cheap call, result memoizable per invocation.
  `None` (unknown / offline / no access) suppresses the heads-up rather than guessing.

**Documenting `--private` (required, not incidental).** The shared-vs-private distinction is the
single most important thing a user must understand to avoid leaking planning, so `--private` is
documented in three places, kept in lockstep:

1. **Plugin repo user docs** — the toolkit README (the repo spec #1 packages) gains a short
   "Shared vs private tracks" section: where each tier lives, that new tracks default to shared
   `.work-plan/`, and `--private` to keep a track local. `SKILL.md` gets the same in its subcommand
   reference, and the relevant subcommands' `--help` text names `--private`.
2. **Setup flow** — `init-repo` (registering a repo) explains the two tiers in its output and the
   public heads-up behavior, so the model is introduced at the moment a user wires up a repo.
3. **The seeded `.work-plan/README.md`** — already toolkit-facing; it notes that tracks here are the
   *shared* tier and that `--private` keeps a track out of the repo.

### Self-describing folder — auto-seeded `.work-plan/README.md`

The **first time** a repo's `.work-plan/` is created (by `init-repo` or by the first track write),
the CLI drops a `.work-plan/README.md` from a template — **universally, regardless of repo
visibility** (it's onboarding value on private repos, not just leak-prevention on public ones).
The README states, briefly:

- What this folder is: tool-managed *work-plan tracks* — lightweight planning over GitHub issues;
  GitHub remains canonical for issue state.
- That it's safe to leave alone (the toolkit manages it).
- How to get the tool: links to `stylusnexus/work-plan-toolkit` and the `stylusnexus/agent-plugins`
  marketplace (from spec #1), so a curious reader can install `/work-plan` themselves.

Seeding is idempotent: if `README.md` already exists it is left byte-identical.

### Component boundaries (for isolation/testability)

| Unit | Responsibility | Depends on |
|---|---|---|
| `config.py` | resolve a repo's shared dir (`local`+`.work-plan`); unchanged `notes_root` | — |
| `tracks.py` | union discovery, tier tagging, dedupe | `config`, `frontmatter` |
| `github_state.repo_visibility` | one `gh` call → visibility string \| None | `gh` |
| `lib/notes_readme.py` (new, small) | render + idempotently seed `.work-plan/README.md` | — |
| write commands | choose tier (default shared / `--private`), emit public heads-up, ensure README | the above |

Each is independently testable with mocked `gh`/filesystem, consistent with the existing offline
test suite.

---

## Phasing

**Phase 1 — Discovery union (read path).** `tracks.py` union + `tier` field + dedupe; `config.py`
shared-dir resolver. Exit: a hand-placed `<clone>/.work-plan/foo.md` appears in `brief`/`orient`
alongside private tracks, deduped, with no write-path changes yet.

**Phase 2 — Write routing + README seeding.** New-track writes default to shared `.work-plan/`;
`--private` opt-out; `notes_readme.py` seeds the README on folder creation. Exit: `init-repo` /
`slot` create tracks in the repo's `.work-plan/` with a README present.

**Phase 3 — Public heads-up.** `repo_visibility` + the non-blocking warning on writes to public
repos. Exit: writing to a public repo prints the heads-up; `--private` and private repos don't.

**Optional follow-on (own spec/plan):** a `work-plan migrate` that relocates
`notes_root/<folder>/*` into each registered repo's `.work-plan/` and commits.

Each phase is a commit/PR boundary (code → feature branch → PR to `dev`, per repo convention).

---

## Test / verification cases (plain English)

**Discovery**
- A track under a registered, cloned repo's `.work-plan/` shows up in discovery tagged `shared`.
- A track under `notes_root` shows up tagged `private` (unchanged behavior).
- The same (repo, track-name) in both tiers dedupes to one entry; shared wins; a warning names both.
- A registered repo with **no** local clone contributes zero shared tracks and raises no error.
- `archive/`, dotfiles, and `README.md` inside `.work-plan/` are skipped by discovery.

**Write routing**
- A new track defaults to the repo's `.work-plan/`.
- `--private` writes the track under `notes_root` and emits no public heads-up.

**`--private` documentation (presence, not just behavior)**
- The toolkit README and `SKILL.md` both contain a "Shared vs private tracks" section naming
  `--private`; the writing subcommands' `--help` lists the flag.
- `init-repo` output explains the two tiers and the public heads-up.
- The seeded `.work-plan/README.md` mentions `--private` as the way to keep a track local.

**Public heads-up**
- Writing a track into a PUBLIC repo prints the one-line heads-up; the write still proceeds.
- Writing into a PRIVATE repo prints no heads-up.
- `repo_visibility` returning `None` (offline / no access) suppresses the heads-up (no guess).

**README seeding**
- First creation of `.work-plan/` writes `README.md` containing the toolkit + marketplace links.
- Seeding runs for both public and private repos.
- Re-running with an existing `README.md` leaves it byte-identical (idempotent).

**Non-regression**
- Existing single-`notes_root` users see identical results (private tier unchanged).
- GitHub issue state is still derived live; nothing is cached.
- Full offline `unittest` suite stays green.

---

## Risks & open questions

- **Default-to-shared on a fresh public repo.** The first write to a public repo lands in
  `.work-plan/` *with* a heads-up. Acceptable per design (warn, not block), but confirm the heads-up
  copy is loud enough; a future `--private`-by-default-for-public mode is possible if leaks recur.
- **Dedupe collisions.** Shared-wins + warn is a policy choice; a track intentionally forked between
  tiers would warn every run. Mitigation: the warning tells the user to resolve; we don't auto-merge.
- **Visibility call cost/availability.** One `gh` call per write target; memoize per invocation.
  Offline → `None` → no heads-up (and writes still work, since GitHub isn't consulted for state).
- **README as a soft marketing vector.** Linking the toolkit/marketplace from every `.work-plan/`
  README is intentional (discovery), but lives in user repos — keep the copy short, neutral, and
  clearly opt-out-able by editing/removing the file.
- **Interaction with `plan-status` archive paths.** `.work-plan/archive/` vs `plan-status`'s own
  archive conventions should not collide; verify during Phase 1 discovery filtering.

---

## Decisions locked (this session)

1. **Notes home:** per-repo committed **`.work-plan/`** (hidden, top-level, tool-owned).
2. **Model:** **coexist two-tier** — `.work-plan/` shared per-repo + `notes_root` private; union
   discovery, shared-wins dedupe.
3. **Public safety:** **non-blocking heads-up** before writing into a PUBLIC repo (not a hard gate).
4. **Self-describing:** **`.work-plan/README.md` auto-seeded for every `.work-plan/`**, public or
   private, linking back to the toolkit + `stylusnexus/agent-plugins` marketplace.
5. **New-track default:** **shared** (`.work-plan/`), with `--private` as the opt-out.
6. **`--private` is documented**, not hidden: toolkit README + `SKILL.md` + subcommand `--help`,
   the `init-repo` setup flow, and the seeded `.work-plan/README.md`.
7. **Migration:** optional follow-on, **out of scope** here.
