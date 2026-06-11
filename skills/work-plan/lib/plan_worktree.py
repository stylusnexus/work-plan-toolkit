"""Resolve a repo's shared-tier (.work-plan/) directory, optionally via a
worktree pinned to a dedicated plan branch (#260).

A repo MAY pin its shared planning to its own `plan_branch` so planning churn
never lands on code branches (dev/main/feature) or in PRs. When `plan_branch`
is set, the shared tier is read/written through a git WORKTREE checked out at
that branch, kept in a stable cache dir beside the work-plan config. When it's
unset, the shared tier is simply the working tree's `.work-plan/` — the legacy
behaviour, unchanged.

Never raises — git absence/failure/timeout degrades to "no shared tier" (None),
exactly like notes_vcs. A read must never break discovery.

NOTE (phasing): this resolves the *path*. Committing shared-tier writes on
`plan_branch` (so they actually travel) is a later phase — see #260.
"""
import hashlib
import subprocess
from pathlib import Path
from typing import Optional

from lib.config import DEFAULT_CONFIG_PATH

GIT_TIMEOUT = 20

# Worktrees live beside the config (so Claude ~/.claude and Codex ~/.agents both
# work), keyed by a hash of the repo's local path so two repos never collide.
_WORKTREE_ROOT = DEFAULT_CONFIG_PATH.parent / "plan-worktrees"


def _git(cwd, *args, timeout: int = GIT_TIMEOUT):
    """Run `git -C <cwd> <args>`; return CompletedProcess or None (never raises)."""
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def _worktree_dir(local_path: Path) -> Path:
    """Stable cache dir for this repo's plan worktree (keyed by its local path)."""
    key = hashlib.sha256(str(local_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return _WORKTREE_ROOT / key


def _branch_exists(local_path: Path, branch: str) -> bool:
    """True if `branch` exists locally or as origin/<branch>."""
    for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        proc = _git(local_path, "rev-parse", "--verify", "--quiet", ref)
        if proc is not None and proc.returncode == 0:
            return True
    return False


def ensure_worktree(local_path: Path, branch: str) -> Optional[Path]:
    """Ensure a worktree of `local_path` checked out at `branch` exists in the
    cache; return its path, or None on any failure. Never raises.

    Does NOT create the branch — if `branch` doesn't exist yet (bootstrap not
    run), returns None so callers fall back to "no shared tier". Idempotent: an
    already-present worktree is reused.
    """
    if not branch:
        return None
    local_path = Path(local_path).expanduser()
    dest = _worktree_dir(local_path)
    # A worktree's `.git` is a gitdir-pointer file (exists() catches file + dir).
    if (dest / ".git").exists():
        return dest
    if not _branch_exists(local_path, branch):
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    proc = _git(local_path, "worktree", "add", "--quiet", str(dest), branch)
    if proc is None or proc.returncode != 0:
        return None
    return dest


def shared_tier_dir(entry: dict) -> Optional[Path]:
    """The `.work-plan/` directory to read/write for a repo config `entry`.

    - `plan_branch` set  → the worktree's `.work-plan/` (None when the worktree
      can't be ensured, e.g. the branch isn't bootstrapped yet).
    - `plan_branch` unset → the working tree's `.work-plan/` (legacy, unchanged).

    Returns None when the entry has no `local` path. Never raises.
    """
    if not entry or not entry.get("local"):
        return None
    local_path = Path(entry["local"]).expanduser()
    branch = entry.get("plan_branch")
    if branch:
        worktree = ensure_worktree(local_path, branch)
        return (worktree / ".work-plan") if worktree else None
    return local_path / ".work-plan"
