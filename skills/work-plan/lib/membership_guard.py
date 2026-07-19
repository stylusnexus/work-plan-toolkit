"""Compare-and-swap guard for track-membership writes (#241).

Slotting an issue into a track edits `meta["github"]["issues"]`. Shared-tier
tracks travel via git push/pull, so an assisted or background write can race
another session or a teammate's pull. `lib.frontmatter.write_file` is a blind
overwrite, so without a guard the last writer silently wins.

This module adds two things:

  * `issues_fingerprint(meta)` — a deterministic digest of the membership list
    ONLY. We fingerprint just `github.issues`, not the whole frontmatter or the
    body: those carry fields other commands legitimately rewrite concurrently
    (`refresh-md` stamps `last_touched`, `handoff` rewrites the body table), and
    fingerprinting them would abort on changes that have nothing to do with the
    list we're about to overwrite. The membership list is exactly the CAS surface.

  * `guarded_membership_write(...)` — ALWAYS re-reads the file from disk
    immediately before writing, applies the membership delta to the FRESH
    frontmatter, and writes back the rest of the frontmatter and the body
    unchanged. So a concurrent edit to the body OR to other frontmatter fields
    (status, last_touched, depends_on, …) is preserved — only the issues list is
    replaced. When `expect` is supplied and the on-disk membership no longer
    matches it, the write is ABORTED and a `{"stale": ...}` signal is returned
    instead of overwriting — the caller re-prompts on fresh state. When `expect`
    is None (the manual single-writer path) the abort is skipped, but the
    re-read + merge still happens: strictly safer than a blind overwrite, with
    the same observable result for a lone writer.

Scope of the guarantee (deliberately narrow — don't oversell it):
  - This is a check-then-act, not a locked atomic CAS: `parse_file` then
    `write_file` are separate syscalls with no file lock, so a writer landing in
    the sub-millisecond window between them isn't caught. `expect` narrows the
    window vs. a blind overwrite; it does not eliminate it. Adequate for the real
    usage (interactive single user + occasional same-machine background).
  - `shared_rebase_guard` lands a shared-tier write on top of origin AS OF THE
    LAST FETCH; it is NOT a cross-machine atomic CAS against origin. A teammate
    pushing between the rebase and the eventual (separate) push is reconciled by
    the non-fast-forward push being rejected + rebase-on-next-write, not by this
    write path.
  - `frontmatter.write_file` re-serializes the frontmatter via yq on every
    write, so body-only edits round-trip verbatim but YAML comments / key order
    are normalized (a pre-existing property, not introduced here).
"""
import hashlib
import json
from pathlib import Path

from lib.frontmatter import parse_file, write_file


def _field_set(meta: dict, field: str) -> set:
    """The frontmatter's github.<field> (e.g. "issues" or "references") as a
    set of ints (malformed entries dropped — the file may be hand-edited)."""
    out = set()
    for n in (meta.get("github", {}).get(field) or []):
        try:
            out.add(int(n))
        except (TypeError, ValueError):
            continue
    return out


def _issue_set(meta: dict) -> set:
    return _field_set(meta, "issues")


def _reference_set(meta: dict) -> set:
    return _field_set(meta, "references")


def issues_fingerprint(meta: dict) -> str:
    """Deterministic sha256[:16] of the sorted github.issues list.

    Order-independent (sorted) and stable across runs (no randomness — 3.9
    stdlib). Two metas with the same membership produce the same fingerprint
    regardless of list order or unrelated frontmatter differences.
    """
    payload = json.dumps(sorted(_issue_set(meta)), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def references_fingerprint(meta: dict) -> str:
    """Deterministic sha256[:16] of the sorted github.references list.

    Mirrors `issues_fingerprint` but over the references list ONLY — kept
    separate so an owned-issue add/remove can't stale-out a pending reference
    write (and vice versa); the two lists are independent CAS surfaces.
    """
    payload = json.dumps(sorted(_reference_set(meta)), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def guarded_membership_write(path, *, add_nums=(), remove_nums=(), expect=None):
    """Re-read `path`, apply the membership delta to the fresh frontmatter, and
    write back the fresh body unchanged.

    Returns one of:
      {"stale": True, "reason": str, "current": [int]}
          — `expect` was supplied and the on-disk membership no longer matches
            it; NO write happened. `current` is the fresh on-disk list so the
            caller can re-offer against it.
      {"written": [int]}
          — wrote successfully; the value is the final sorted membership list.

    `expect` is the `issues_fingerprint` the caller captured when it built the
    operation (e.g. when the viewer rendered the offer). Pass None for the
    unguarded manual path.
    """
    fresh_meta, fresh_body = parse_file(Path(path))

    if expect is not None and issues_fingerprint(fresh_meta) != expect:
        return {
            "stale": True,
            "reason": "track membership changed since the operation was prepared",
            "current": sorted(_issue_set(fresh_meta)),
        }

    issues = _issue_set(fresh_meta)
    issues |= {int(n) for n in add_nums}
    issues -= {int(n) for n in remove_nums}
    final = sorted(issues)
    fresh_meta.setdefault("github", {})["issues"] = final
    write_file(Path(path), fresh_meta, fresh_body)
    return {"written": final}


def guarded_reference_write(path, *, add_nums=(), expect=None):
    """Add cross-track references without changing github.issues ownership.

    Same CAS contract as `guarded_membership_write`, checked against
    `references_fingerprint` instead of `issues_fingerprint`: when `expect` is
    supplied and the on-disk references list no longer matches it, the write is
    ABORTED and a `{"stale": ...}` signal is returned instead of overwriting.
    """
    fresh_meta, fresh_body = parse_file(Path(path))

    if expect is not None and references_fingerprint(fresh_meta) != expect:
        return {
            "stale": True,
            "reason": "track references changed since the operation was prepared",
            "current": sorted(_reference_set(fresh_meta)),
        }

    references = _reference_set(fresh_meta)
    references |= {int(n) for n in add_nums}
    final = sorted(references)
    fresh_meta.setdefault("github", {})["references"] = final
    write_file(Path(path), fresh_meta, fresh_body)
    return {"written": final}


def demote_fingerprint(meta: dict) -> str:
    """Deterministic sha256[:16] over BOTH the sorted issues and references
    lists — the combined CAS surface for `guarded_demote_write`, which moves
    numbers between the two lists in a single write. Order-independent and
    stable across runs (no randomness — 3.9 stdlib)."""
    payload = json.dumps(
        {"issues": sorted(_issue_set(meta)), "references": sorted(_reference_set(meta))},
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def guarded_demote_write(path, *, nums=(), expect=None):
    """Re-read `path`, move `nums` from `github.issues` to `github.references`
    in ONE write, and write back the fresh body unchanged.

    Single-file, single-write migration primitive for `demote-to-reference`:
    unlike `guarded_membership_write`/`guarded_reference_write` (which each
    touch one list), this moves numbers between both lists atomically so a
    reader never observes a state where a number is in neither (or both).

    Returns one of:
      {"stale": True, "reason": str, "current_issues": [int], "current_references": [int]}
          — `expect` was supplied and the on-disk (issues, references) pair no
            longer matches it; NO write happened.
      {"written": {"issues": [int], "references": [int]}}
          — wrote successfully; final sorted lists for both fields.

    `nums` not currently present in `github.issues` are added to
    `github.references` anyway (idempotent from THIS primitive's point of
    view) — the caller (`demote_to_reference.py`) is responsible for the
    ownership/orphan preflight; this is the write mechanics only.
    """
    fresh_meta, fresh_body = parse_file(Path(path))

    if expect is not None and demote_fingerprint(fresh_meta) != expect:
        return {
            "stale": True,
            "reason": "track issues/references changed since the operation was prepared",
            "current_issues": sorted(_issue_set(fresh_meta)),
            "current_references": sorted(_reference_set(fresh_meta)),
        }

    move_nums = {int(n) for n in nums}
    issues = _issue_set(fresh_meta) - move_nums
    references = _reference_set(fresh_meta) | move_nums
    final_issues = sorted(issues)
    final_references = sorted(references)
    github = fresh_meta.setdefault("github", {})
    github["issues"] = final_issues
    github["references"] = final_references
    write_file(Path(path), fresh_meta, fresh_body)
    return {"written": {"issues": final_issues, "references": final_references}}


def shared_rebase_guard(target, cfg):
    """Before writing a SHARED-tier track pinned to a `plan_branch`, fetch +
    rebase its worktree onto origin so the write lands on top of a teammate's
    pushed plan changes (#241). Best-effort: this reduces the cross-machine
    (git push/pull) race, it does not make the write atomic against origin — a
    teammate pushing after the rebase is reconciled by the non-fast-forward push
    rejection + rebase-on-next-write, not here. The fingerprint CAS covers the
    same-machine race.

    Returns (ok: bool, reason: str | None):
      (True, None)        — safe to proceed: the track is private, a legacy
                            shared track (no plan_branch → working-tree tier), or
                            the worktree rebased cleanly / had no upstream.
      (False, reason)     — the shared branch diverged and could NOT auto-rebase;
                            the caller MUST abort and surface {needs_rebase}
                            rather than blind-write over a diverged branch.

    Never raises — an unexpected guard error degrades to "proceed" (consistent
    with the toolkit's never-break-the-command VCS philosophy; the underlying
    plan_worktree ops are themselves never-raise).
    """
    try:
        if getattr(target, "tier", None) != "shared":
            return (True, None)
        repos = (cfg or {}).get("repos", {}) or {}
        entry = repos.get(getattr(target, "folder", None))
        if entry is None:
            for e in repos.values():
                if e and e.get("github") == getattr(target, "repo", None):
                    entry = e
                    break
        branch = entry.get("plan_branch") if entry else None
        local = entry.get("local") if entry else None
        if not branch or not local:
            return (True, None)  # legacy shared tier (working tree) — no rebase
        from lib import plan_worktree
        worktree = plan_worktree.ensure_worktree(Path(local).expanduser(), branch)
        if worktree is None:
            return (True, None)  # can't ensure the worktree — degrade, proceed
        if not plan_worktree.rebase_onto_origin(worktree, branch):
            return (False, f"shared plan branch '{branch}' diverged and could not "
                           f"auto-rebase; resolve manually")
        return (True, None)
    except Exception:
        return (True, None)
