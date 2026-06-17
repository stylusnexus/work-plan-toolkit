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
