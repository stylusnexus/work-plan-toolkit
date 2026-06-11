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
    """Stable cache dir for this repo's plan worktree (keyed by its local path).

    `resolve()` can touch the filesystem and raise OSError (symlink loop,
    permissions) — fall back to the un-resolved absolute path so this never
    raises and the never-raise contract holds upstream.
    """
    try:
        resolved = str(local_path.resolve())
    except OSError:
        resolved = str(local_path.absolute())
    key = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
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
        # Reuse ONLY if it's still checked out at `branch`. A worktree left on
        # another branch (manual `git checkout`, or the branch was renamed)
        # would otherwise get plan commits on the wrong branch — refuse and
        # degrade to "no shared tier" rather than commit somewhere unexpected.
        head = _git(dest, "rev-parse", "--abbrev-ref", "HEAD")
        if head is not None and head.returncode == 0 and head.stdout.strip() == branch:
            return dest
        return None
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


def dirty_work_plan_paths(worktree: Path) -> list:
    """Repo-relative paths under `.work-plan/` with uncommitted changes in the
    worktree (staged, unstaged, or untracked). Empty list on any failure or a
    clean tree. Never raises.

    Mirrors notes_vcs.dirty_paths: the dispatcher snapshots these BEFORE a
    command and commits only the paths that appear AFTER — so a pre-existing
    dirty `.work-plan/` file from unrelated manual edits is never swept into a
    plan commit triggered by an unrelated subcommand.
    """
    wt = Path(worktree).expanduser()
    proc = _git(wt, "status", "--porcelain", "--", ".work-plan")
    if proc is None or proc.returncode != 0:
        return []
    paths = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        # Porcelain v1: "XY <path>" (or "XY <old> -> <new>" for renames).
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip())
    return paths


def commit_shared_tier(worktree: Path, message: str, paths) -> Optional[str]:
    """Commit exactly `paths` (repo-relative, all under `.work-plan/`) in the
    worktree with `message`; return the new short SHA, or None. Never raises.

    Stages ONLY the explicit `paths` — not a blanket `.work-plan/` add — so a
    `plan_branch` worktree never sweeps in code, other files, or pre-existing
    dirty plan files the triggering command didn't touch. No-op when `paths` is
    empty or nothing stages.

    Commits on whatever branch the worktree is checked out — the caller has
    already verified that's `plan_branch`. Local commit only; pushing the branch
    (to actually share it) is a separate, deliberate step (#260, follow-up).
    """
    wt = Path(worktree).expanduser()
    if not (wt / ".work-plan").is_dir():
        return None
    scoped = [p for p in (paths or []) if p]
    if not scoped:
        return None
    if _git(wt, "add", "--", *scoped) is None:
        return None
    staged = _git(wt, "diff", "--cached", "--quiet", "--", *scoped)
    if staged is None or staged.returncode == 0:
        return None
    proc = _git(wt, "commit", "-m", message, "--", *scoped)
    if proc is None or proc.returncode != 0:
        return None
    head = _git(wt, "rev-parse", "--short", "HEAD")
    if head is None or head.returncode != 0:
        return None
    return head.stdout.strip() or None


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
