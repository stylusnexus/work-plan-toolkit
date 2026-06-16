"""Resolve a directory to a configured repo (config key + GitHub slug).

Shared substrate for two sibling features: `brief` cwd auto-scope (#358) and the
VS Code viewer auto-focus (#357). Both need the same "which configured repo is
this directory?" answer, so it lives here once — exposed to the viewer through
the `which-repo` command and called directly by `brief`.

Resolution order: the local clone path is the primary signal (it's the most
explicit thing the user configured); the git `origin` remote is the fallback for
repos registered with `local: null`. If both resolve but to different keys (which
shouldn't happen in practice), the local-path key wins.

Read-only and never raises — every git call goes through the bounded `_git`
wrapper, which returns None on failure, and a no-match returns None so callers
fall back to their current all-repos behavior unchanged.
"""
import re
from pathlib import Path
from typing import Optional

from lib.git_state import _git


def _normalize_remote_url(url: str) -> Optional[str]:
    """Normalize a git remote URL to a lowercased `org/repo` slug, or None.

    Handles the forms git emits for GitHub remotes:
      git@github.com:org/repo.git        -> org/repo   (scp-like)
      ssh://git@github.com/org/repo.git  -> org/repo
      https://github.com/org/repo.git    -> org/repo
      https://github.com/org/repo        -> org/repo

    A trailing `.git`, surrounding whitespace, and trailing slashes are stripped.
    Returns None for anything it can't parse into a host-path.
    """
    if not url:
        return None
    u = url.strip()

    # scp-like syntax: [user@]host:path  (no scheme, single colon before path)
    m = re.match(r"^[\w.+-]+@[\w.-]+:(.+)$", u)
    if m:
        path = m.group(1)
    else:
        # url syntax: scheme://[user@]host[:port]/path
        m = re.match(r"^[\w.+-]+://(?:[^/@]+@)?[^/]+/(.+)$", u)
        if not m:
            return None
        path = m.group(1)

    path = path.strip().strip("/")
    if path.endswith(".git"):
        path = path[:-len(".git")]
    path = path.strip("/")
    return path.lower() or None


def _toplevel(start_dir) -> Optional[Path]:
    """The git work-tree root containing `start_dir`, resolved absolute, or None.

    Uses `rev-parse --show-toplevel` (not the raw dir) so resolution works from
    any nested subdirectory and a configured `local` that merely *contains* the
    cwd can't false-match.
    """
    proc = _git(start_dir, "rev-parse", "--show-toplevel")
    if proc is None or proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return Path(out).resolve()
    except OSError:
        return None


def _origin_slug(start_dir) -> Optional[str]:
    """The `org/repo` slug of `start_dir`'s `origin` remote, or None."""
    proc = _git(start_dir, "remote", "get-url", "origin")
    if proc is None or proc.returncode != 0:
        return None
    return _normalize_remote_url(proc.stdout.strip())


def resolve_repo_for_dir(cfg: dict, start_dir) -> Optional[dict]:
    """Resolve `start_dir` to a single configured repo.

    Returns `{"key", "github", "matched_by"}` (matched_by is "local" or
    "remote") when exactly one repo matches, else None. None covers: no repos
    configured, dir isn't a git repo, no match, or an ambiguous (>1) match —
    callers treat all of these as "don't auto-scope."
    """
    repos = cfg.get("repos") or {}
    if not repos:
        return None

    # --- local clone path (primary) ---
    top = _toplevel(start_dir)
    if top is not None:
        local_keys = []
        for key, entry in repos.items():
            local_raw = (entry or {}).get("local")
            if not local_raw:
                continue
            try:
                cfg_root = Path(local_raw).expanduser().resolve()
            except OSError:
                continue
            if cfg_root == top:
                local_keys.append(key)
        if len(local_keys) == 1:
            key = local_keys[0]
            return {"key": key,
                    "github": (repos[key] or {}).get("github"),
                    "matched_by": "local"}
        if len(local_keys) > 1:
            # Ambiguous local config — refuse to guess.
            return None

    # --- git origin remote (fallback) ---
    slug = _origin_slug(start_dir)
    if slug:
        remote_keys = [
            key for key, entry in repos.items()
            if entry and entry.get("github") and entry["github"].lower() == slug
        ]
        if len(remote_keys) == 1:
            key = remote_keys[0]
            return {"key": key,
                    "github": repos[key].get("github"),
                    "matched_by": "remote"}

    return None
