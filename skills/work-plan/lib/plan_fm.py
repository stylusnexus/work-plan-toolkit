"""Shared frontmatter-write helpers for viewer-driven plan writes (#286).

Every viewer-driven write to a plan/spec doc is **frontmatter-only** by hard
constraint. These helpers are the single, security-critical write path so the
escape guard and the public-repo confirm gate aren't copy-pasted (and can't
drift) across `plan-confirm`, `plan-ack`, and any future frontmatter writer.
"""
import json
from pathlib import Path
from typing import Optional

from lib import frontmatter
from lib.write_guard import needs_confirm, make_token, valid_token


def resolve_doc_path(repo_root: Path, rel: str) -> Optional[Path]:
    """Absolute path of `rel` iff it is a real file inside repo_root, else None.

    Guards the write surface: the resolved path must live under the repo root,
    so a `../escape`, an absolute `rel`, or an in-repo symlink pointing outside
    can't steer a frontmatter write at an arbitrary file."""
    root = Path(repo_root).resolve()
    try:
        p = Path(repo_root) / rel
        if not p.is_file():
            return None
        resolved = p.resolve()
    except OSError:
        return None
    if resolved == root or root in resolved.parents:
        return resolved
    return None


def public_repo_gate(slug, rel: str, cfg: dict, confirm, action: str) -> bool:
    """Public-repo confirm-token gate (the viewer surfaces this as a modal).

    Returns True when the write may proceed. When a gate is required and no valid
    token was supplied, prints the `{needs_confirm, reason, token}` JSON the
    viewer's executeWrite flow consumes and returns False — the caller must then
    make NO write. `action` is the verb phrase spliced into the reason."""
    if slug and needs_confirm(slug, cfg) and not (
        isinstance(confirm, str) and valid_token(confirm, slug, rel)
    ):
        print(json.dumps({
            "needs_confirm": True,
            "reason": (f"{slug} is PUBLIC (or visibility unknown); {action} "
                       f"a frontmatter write will be committed there."),
            "token": make_token(slug, rel),
        }))
        return False
    return True


def set_key(doc_path: Path, key: str, value) -> bool:
    """Set (`value` not None) or delete (`value` None) ONE frontmatter key,
    preserving the body byte-for-byte. Returns True iff the file changed
    (idempotent no-op → False), so callers can report "nothing to do"."""
    meta, body = frontmatter.parse_file(doc_path)
    if not isinstance(meta, dict):
        meta = {}
    if value is None:
        if key not in meta:
            return False
        del meta[key]
    else:
        if meta.get(key) == value:
            return False
        meta[key] = value
    frontmatter.write_file(doc_path, meta, body)
    return True
