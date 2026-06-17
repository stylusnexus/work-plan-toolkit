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
    frontmatter, and writes back the fresh body unchanged. So a concurrent
    body-only edit is preserved rather than clobbered. When `expect` is supplied
    and the on-disk membership no longer matches it, the write is ABORTED and a
    `{"stale": ...}` signal is returned instead of overwriting — the caller
    re-prompts on fresh state. When `expect` is None (the manual single-writer
    path) the abort is skipped, but the re-read + merge still happens: strictly
    safer than a blind overwrite, with the same observable result for a lone
    writer.
"""
import hashlib
import json
from pathlib import Path

from lib.frontmatter import parse_file, write_file


def _issue_set(meta: dict) -> set:
    """The frontmatter's github.issues as a set of ints (malformed entries
    dropped — the file may be hand-edited)."""
    out = set()
    for n in (meta.get("github", {}).get("issues") or []):
        try:
            out.add(int(n))
        except (TypeError, ValueError):
            continue
    return out


def issues_fingerprint(meta: dict) -> str:
    """Deterministic sha256[:16] of the sorted github.issues list.

    Order-independent (sorted) and stable across runs (no randomness — 3.9
    stdlib). Two metas with the same membership produce the same fingerprint
    regardless of list order or unrelated frontmatter differences.
    """
    payload = json.dumps(sorted(_issue_set(meta)), separators=(",", ":"))
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


def shared_rebase_guard(target, cfg):
    """Before writing a SHARED-tier track pinned to a `plan_branch`, fetch +
    rebase its worktree onto origin so a teammate's pushed plan change isn't
    clobbered (#241). The fingerprint CAS guards a same-machine race; this guards
    the cross-machine (git push/pull) race.

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
