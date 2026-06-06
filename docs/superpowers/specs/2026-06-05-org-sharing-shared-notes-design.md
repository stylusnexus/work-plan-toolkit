# Org Sharing — Shared Track Notes (Per-Repo `.work-plan/`)

> **For agentic workers:** This is a design spec (the *why* and *what*), not an implementation
> plan. The *how* gets written next via writing-plans into `docs/superpowers/plans/`. This is the
> **second of two** org-sharing specs — the *data-sharing* half. Sibling (tool-sharing):
> `docs/superpowers/specs/2026-06-05-org-sharing-plugin-packaging-design.md`.

**Date:** 2026-06-05
**Status:** Revised after Codex spec-review (2026-06-05) — awaiting re-review
**Owner:** Eve McGivern (Stylus Nexus)
**Feature home:** `work-plan-toolkit` → `lib/config.py`, `lib/tracks.py`, `lib/github_state.py`, and
every track creator/mutator command.

---

## Revision note (what changed after the second-model review)

A Codex spec-review returned DO NOT SHIP; it was right on the substance. This revision:

- **Visibility now fails *closed*.** Unknown/offline visibility produces a conservative warning (or
  requires `--private`/acknowledgement), never silent shared writing — the original "suppress on
  unknown" contradicted the no-leak goal.
- **Full write-surface inventory.** Not just `init-repo/slot/handoff/close` — `group`, `init`,
  `canonicalize`, `refresh-md`, `reconcile` also create/mutate tracks. Each gets explicit tier +
  warning behavior.
- **Tier-aware archive/close.** `close.py` does `dest.relative_to(notes_root)` (raises for
  `.work-plan/` paths) and `discover_archived_tracks` only scans `notes_root`; both must become
  tier-aware. The "no signature change" claim is withdrawn.
- **Single-owner resolution.** `_build_track` takes `repo` from frontmatter but `local_path` from the
  containing folder — a shared file in repo A with `github.repo: B` would query B's issues while
  reading A's git. Shared tracks must resolve both from one canonical owner (and require
  frontmatter/folder agreement).
- **Repo-qualified track resolution.** `find_track_by_name` is global single-match; identical slugs
  across repos break `slot/handoff/close`. Add a repo qualifier.
- **Commit responsibility made explicit.** Verified: `plan-status`/track writes do **not** commit
  (`write_text`/`git mv` only). Shared tracks travel only after a commit — assigned to the user (with
  an optional `--commit` convenience), not claimed as automatic.
- **3.9-safe annotation.** `repo_visibility(...) -> Optional[str]`, not a `str | None` union.

---

## Plain-English summary (read this even if you never read code)

Spec #1 makes everyone run the same `/work-plan`. This spec makes everyone see the same *plans*.

Today your planning "tracks" — small YAML-headed markdown files pointing at GitHub issues — live in
**one private folder on your machine** (`Project Notes/`). Nobody else sees them; they don't travel
with the code. The change: let a track live **inside the repo it's about**, in a hidden, committed
`.work-plan/` folder. Clone the repo (new laptop, or a future teammate) and the tracks are there,
synced by ordinary `git pull` — *once they've been committed*. Your existing private folder keeps
working unchanged for anything you don't want to commit (the "private tier").

Two guardrails: because some repos are **public**, the tool warns before writing a track into a
public repo (and, to be safe, warns even when it *can't tell* the repo's visibility). And every
`.work-plan/` gets a short **README** explaining the folder and linking to the toolkit, so a stranger
(or future-you) isn't baffled.

Solo-first by design — today there's effectively one user. The two-tier model is a **privacy switch**
(which tracks ride along in the repo vs. stay on my machine) that also unlocks the future
multi-developer story with no rewrite.

---

## Problem statement

`config.notes_root` is one per-user directory; `discover_tracks` walks it and treats the first path
component as a repo key. Tracks are therefore **per-user**, **detached from the code**, and **don't
travel**. `plan-status` solved the *verdict* half (derives liveness live from git; its stamps/archives
are written into the repo). The gap is the **tracks themselves** — and, as the review surfaced, even
plan-status only *writes files*; it does not commit. So nothing travels until someone commits.

### Current visibility reality (verified 2026-06-05 via `gh repo view --json visibility`)

| Repo | Visibility |
|---|---|
| `stylusnexus/work-plan-toolkit` | PUBLIC |
| `stylusnexus/CritForge` | PRIVATE |
| `stylusnexus/discogorama-recs` | PRIVATE |

The mix is why "commit tracks into every repo" is wrong: committing into work-plan-toolkit publishes
planning into a public history. Visibility, not team-merge semantics, is the dominant design force.

---

## Goals

1. A track can live at `<repo>/.work-plan/<track>.md`, committed, travelling via `git pull` once committed.
2. Cloning a repo surfaces that repo's tracks with no setup beyond registering the clone.
3. `notes_root` keeps working unchanged as the private tier.
4. The tool **never silently writes planning into a public repo** — and warns even when visibility is
   unknown (fail closed).
5. Every `.work-plan/` is self-describing (README) and links to the toolkit.
6. **Every** track creator/mutator has defined tier + warning behavior (full inventory).
7. Shared-track identity, ownership, archive, and resolution are unambiguous across repos.
8. Commit/push responsibility is explicit (no false "auto-travel").
9. No new required config key; no caching of GitHub state; pure-stdlib (3.9, no `match`).

## Non-goals

- **Removing `notes_root`** (it's the private tier).
- **A mandatory migration** (an optional `migrate` helper is a follow-on).
- **Sharing `config.yml`** (local clone paths are machine-specific; the shared artifact is committed `.work-plan/`).
- **Conflict resolution beyond git** (two editors → ordinary git merge).
- **Auto-discovering repos from a workspace root.**

---

## Design

### Two-tier notes model

```
SHARED  (committed, travels once committed):  <local-clone>/.work-plan/<track>.md
PRIVATE (personal, uncommitted):              <notes_root>/<folder>/<track>.md   (unchanged)
```

- A repo's shared dir derives from `repos.<folder>.local` + `.work-plan/` — **no new required key**
  (optional `repos.<folder>.notes_dir` override allowed; default `.work-plan`).
- A repo with no/invalid `local` clone contributes **no** shared tracks and is a hard rule for
  *writes*: **shared write requires a validated git-repo `local` path** (see "default destination").
- `notes_root` unchanged: private tier and safe default.

### Discovery — union with tier tagging + single-owner resolution (`lib/tracks.py`)

`discover_tracks(cfg)` unions two sources:
1. **Shared:** for each `repos.<folder>` with a valid `local`, walk `<local>/.work-plan/` (skip
   `archive/`, dotfiles, `README.md`).
2. **Private:** walk `notes_root` as today.

Each `Track` gains `tier: Optional[str]` (`"shared"`/`"private"`). Dedupe by `(owner-repo, track-name)`;
on a true collision, **shared wins + one warning** naming both paths.

**Single-owner rule (review fix):** for a **shared** track, `repo` *and* `local_path` resolve from the
**same** owner — the configured folder whose clone physically contains the file. If the file's
frontmatter `github.repo` disagrees with that folder's configured repo, the CLI **warns and treats the
containing folder as canonical** (or skips, configurable) — never the split "repo from frontmatter,
git from folder" that lets a file query a different repo than it reads.

### Repo-qualified resolution (`lib/tracks.py`)

`find_track_by_name` is global single-match, so identical slugs in two repos are unresolvable. Add an
optional `repo`/`folder` qualifier: `find_track_by_name(name, tracks, *, repo=None, …)`. `slot`,
`handoff`, `close` accept an optional `--repo=<key>` (or positional `<track>@<repo>`) to disambiguate;
without it, an ambiguous name errors with the candidates listed (today's behavior) rather than guessing.

### Write surface — full inventory (review fix)

Every command that creates or mutates a track file declares tier behavior:

| Command | Creates/mutates | Tier behavior |
|---|---|---|
| `init-repo` | creates `<repo>/.work-plan/` + README | shared by construction; seeds README |
| `slot` | writes a track (frontmatter) | default **shared** if repo has a valid clone, else **private**; public heads-up |
| `handoff` | session log + status table in a track | writes in the track's existing tier (no move) |
| `close` | moves track to `archive/` | **tier-aware** archive root (see below) |
| `group` | creates tracks under `notes_root` today | route new tracks to the repo's `.work-plan/` when a clone exists; else `notes_root`; public heads-up; `--private` forces private |
| `init` | scaffolds a track, can't infer repo outside `notes_root` | private tier unless given a repo; never write `github.repo: TBD` into a shared file |
| `canonicalize` / `refresh-md` / `reconcile` | mutate an existing track in place | operate in the track's existing tier; no tier change, no new public write without the same heads-up |

`--private` is available on every **creating** command and routes to `notes_root` (and skips the
heads-up). New-track default is **shared** only when a validated clone exists.

### Public (and unknown) heads-up — fail closed (`lib/github_state.py`)

Before the CLI **writes** a track into a repo, it checks visibility:
`repo_visibility(repo) -> Optional[str]` (`"PUBLIC"`/`"PRIVATE"`/`None`) via
`gh repo view <repo> --json visibility`, memoized per invocation.

- `PUBLIC` → one-line heads-up: *"`<repo>` is PUBLIC — this track will be committed publicly; use
  `--private` to keep it local."* Non-blocking.
- `None` (offline / no access / malformed) → **also warn** (fail closed): *"couldn't confirm
  `<repo>` visibility; if it's public this will be committed publicly — `--private` to be safe."*
- `PRIVATE` → no heads-up.

The existing `gh` wrappers turn failures into missing data, so `None` is common; treating it as "safe"
would defeat the guarantee. Acceptance includes offline and malformed-response cases.

### Tier-aware archive / close (review fix)

- `close` computes the archive destination **relative to the track's own tier root** — for a shared
  track, under `<repo>/.work-plan/archive/…`; for private, under `<notes_root>/<folder>/archive/…`.
  It must **not** call `dest.relative_to(notes_root)` for a `.work-plan/` path (raises today).
- `discover_archived_tracks` becomes tier-aware too: scan each repo's `<local>/.work-plan/archive/`
  **and** `notes_root` archives. (This is the withdrawn "no signature change" claim.)
- Confirm no collision with `plan-status`'s own archive path (`docs/.../archive/abandoned`) — verified
  distinct; `.work-plan/archive/` is separate.

### Commit responsibility — explicit (review fix)

Track writes (and `plan-status` stamps/archives) are **working-tree changes only**; the toolkit does
not commit or push. A shared track therefore travels **after the user commits it**. The spec assigns:
- **Default:** the user commits (the README and command output remind them: *"committed `.work-plan/`
  changes travel via `git pull`"*).
- **Optional convenience:** a `--commit` flag on creating commands that `git add` + `git commit` the
  written track (never auto-push). Off by default; explicitly out of the no-leak path (a `--commit`
  on a public repo still shows the heads-up first).

No language anywhere claims tracks travel *without* a commit.

### Self-describing `.work-plan/README.md`

Seeded the **first time** a `.work-plan/` is created (any visibility). Idempotent: if present, left
byte-identical. **Reseed rule (review fix):** creating commands ensure the README exists *only when
the folder itself is created*; they do **not** resurrect a README the user deliberately deleted within
an existing folder (deletion is a respected opt-out). Content: what the folder is (tool-managed
work-plan tracks; GitHub canonical for issue state), that tracks here are the **shared** tier and
`--private` keeps a track local, and links to `stylusnexus/work-plan-toolkit` + the
`stylusnexus/agent-plugins` marketplace.

### Component boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `config.py` | resolve+validate a repo's shared dir (`local` is a git repo); unchanged `notes_root` | — |
| `tracks.py` | union discovery, tier tagging, single-owner resolution, dedupe, repo-qualified lookup | `config`, `frontmatter` |
| `github_state.repo_visibility` | one `gh` call → `Optional[str]`; memoized | `gh` |
| `lib/notes_readme.py` (new) | render + first-creation-only seed of `.work-plan/README.md` | — |
| write commands | tier choice (default shared iff valid clone / `--private`), fail-closed heads-up, README on folder creation, optional `--commit` | the above |

All independently testable with mocked `gh`/filesystem (offline).

---

## Phasing

**Phase 1 — Discovery (read path).** Union discovery + `tier` + single-owner resolution + dedupe +
repo-qualified `find_track_by_name`; `config` shared-dir resolver with git-repo validation. Exit: a
hand-placed `<clone>/.work-plan/foo.md` appears in `brief`/`orient` tagged `shared`, deduped, with the
correct owner; ambiguous cross-repo slugs resolve only with a qualifier.

**Phase 2 — Write routing + README + tier-aware close.** Full write-surface inventory implemented;
`--private`; first-creation README seeding; tier-aware `close` + `discover_archived_tracks`. Exit:
`init-repo`/`slot`/`group` create shared tracks with a README; `close` archives a shared track without
crashing; archived shared tracks are discoverable and reopenable.

**Phase 3 — Visibility heads-up (fail closed) + commit responsibility.** `repo_visibility`; PUBLIC and
unknown both warn; optional `--commit`. Exit: writing to a public *or* unknown-visibility repo warns;
`--private` and private repos don't; `--commit` commits (never pushes) after any heads-up.

**Optional follow-on (own plan):** `work-plan migrate` relocating `notes_root/<folder>/*` into each
repo's `.work-plan/` (with per-file public heads-up).

Each phase: code → feature branch → PR to `dev` (squash-merge).

---

## Test / verification cases (plain English)

**Discovery & resolution**
- A track under a registered, **validated-clone** repo's `.work-plan/` shows up tagged `shared`, with
  `repo` and `local_path` from the **same** owner.
- A shared file whose frontmatter `github.repo` disagrees with its folder triggers a warning and uses
  the folder as canonical (no cross-repo query/read split).
- `notes_root` tracks show up tagged `private` (unchanged).
- Same `(owner-repo, name)` in both tiers → one entry, shared wins, warning names both.
- Identical slug in two repos: bare name errors with candidates; `--repo=<key>` resolves it.
- A registered repo with no/invalid clone contributes zero shared tracks, no error on read.
- `archive/`, dotfiles, `README.md` inside `.work-plan/` are skipped by discovery.

**Write routing (every creator/mutator)**
- New track defaults to `.work-plan/` only when a valid clone exists; otherwise `notes_root`.
- `--private` writes to `notes_root` and emits no heads-up.
- `group` routes new tracks per the same rule; `init` never writes `github.repo: TBD` into a shared file.
- `canonicalize`/`refresh-md`/`reconcile` mutate in place without changing tier.

**Heads-up (fail closed)**
- PUBLIC repo write → heads-up; write proceeds.
- Unknown visibility (`repo_visibility` returns `None`, incl. offline/malformed) → heads-up (not silent).
- PRIVATE repo write → no heads-up.

**Archive / close**
- `close` on a shared track archives under `<repo>/.work-plan/archive/…` without raising.
- `discover_archived_tracks` finds shared archives and `notes_root` archives.
- Reopen of a shared archived track works.

**README**
- First creation of `.work-plan/` writes `README.md` (public and private) with toolkit + marketplace links and the `--private` note.
- Re-running with an existing README is byte-identical; a user-deleted README is **not** resurrected by a later write.

**Commit responsibility**
- Default write does not commit/push (working-tree change only).
- `--commit` `git add`+`git commit`s the track (no push), and still shows the heads-up first on a public/unknown repo.

**Non-regression**
- Single-`notes_root` users see identical results; GitHub state still derived live (no cache); 3.9-safe annotations; full offline suite green.

---

## Risks & open questions

- **Frontmatter/folder disagreement policy** — warn-and-use-folder vs skip is configurable; default
  warn-and-use-folder. Confirm in review.
- **`--commit` scope creep** — kept off by default and push-free to avoid surprising network/history
  effects; revisit if users want push.
- **Unknown-visibility noise** — failing closed means offline users see a heads-up on every shared
  write; acceptable for a leak guarantee, but make the message quiet and one-line.
- **Repo-qualifier ergonomics** — `<track>@<repo>` vs `--repo=` syntax; pick one and apply uniformly.
- **Migration of existing `Project Notes/`** — deferred; some private tracks may never want a repo home.

---

## Decisions locked (this session)

1. **Notes home:** per-repo committed **`.work-plan/`** (hidden, tool-owned).
2. **Model:** coexist two-tier — `.work-plan/` shared + `notes_root` private; union discovery,
   single-owner resolution, shared-wins dedupe.
3. **Public safety: fail closed** — non-blocking heads-up before writing into a **public _or_
   unknown-visibility** repo.
4. **Self-describing:** `.work-plan/README.md` auto-seeded for every `.work-plan/` (public and
   private) on first creation; deletion respected; links back to the toolkit + marketplace.
5. **New-track default:** **shared** only when a validated clone exists, with `--private` opt-out.
6. **`--private` documented** in toolkit README + `SKILL.md` + `--help`, the `init-repo` setup flow,
   and the seeded README.
7. **Commit responsibility:** user commits (optional push-free `--commit`); no auto-travel claim.
8. **Migration:** optional follow-on, out of scope.
