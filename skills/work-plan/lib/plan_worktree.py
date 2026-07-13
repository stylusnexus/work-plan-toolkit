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


def _ref_exists(local_path: Path, ref: str) -> bool:
    proc = _git(local_path, "rev-parse", "--verify", "--quiet", ref)
    return proc is not None and proc.returncode == 0


def local_branch_exists(local_path: Path, branch: str) -> bool:
    """True if `branch` exists as a local head. Never raises."""
    return _ref_exists(Path(local_path).expanduser(), f"refs/heads/{branch}")


def remote_branch_exists(local_path: Path, branch: str) -> bool:
    """True if `origin/<branch>` exists in the local remote-tracking refs (may be
    stale — fetch first for an authoritative answer). Never raises."""
    return _ref_exists(Path(local_path).expanduser(),
                       f"refs/remotes/origin/{branch}")


def _branch_exists(local_path: Path, branch: str) -> bool:
    """True if `branch` exists locally or as origin/<branch>."""
    return (local_branch_exists(local_path, branch)
            or remote_branch_exists(local_path, branch))


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

    The dispatcher snapshots these BEFORE a command and commits only the paths
    that appear AFTER — so a pre-existing dirty `.work-plan/` file from unrelated
    manual edits is never swept into a plan commit triggered by an unrelated
    subcommand.

    Uses NUL-delimited porcelain (`-z`): unlike the line format, `-z` never
    quote-wraps or octal-escapes paths, so filenames with spaces or non-ASCII
    round-trip verbatim back into `git add` (the line format would wrap them in
    quotes and break the commit). `-uall` enumerates untracked files
    individually instead of collapsing a new dir to one `dir/` entry, so the
    before/after delta is per-file. A staged rename's source path is captured
    too, so the rename commits as a unit (dest add + source delete).
    """
    wt = Path(worktree).expanduser()
    proc = _git(wt, "-c", "core.quotepath=false", "status", "--porcelain", "-z",
                "--untracked-files=all", "--", ".work-plan")
    if proc is None or proc.returncode != 0:
        return []
    fields = proc.stdout.split("\0")
    paths = []
    i, n = 0, len(fields)
    while i < n:
        entry = fields[i]
        if len(entry) < 4:  # trailing empty field / malformed line
            i += 1
            continue
        status, path = entry[:2], entry[3:]
        if path:
            paths.append(path)
        # Rename/copy: porcelain -z follows the entry with the source path in
        # the NEXT NUL field ("R  <dest>\0<source>"). Commit both so the rename
        # lands atomically.
        if "R" in status or "C" in status:
            i += 1
            if i < n and fields[i]:
                paths.append(fields[i])
        i += 1
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
        # Unstage what we just staged so a later, unrelated command doesn't
        # commit this residue under its own message (the worktree index is
        # durable across invocations). Working-tree content is preserved.
        _git(wt, "reset", "--quiet", "--", *scoped)
        return None
    head = _git(wt, "rev-parse", "--short", "HEAD")
    if head is None or head.returncode != 0:
        return None
    return head.stdout.strip() or None


def _contained_shared_tier(root: Path) -> tuple:
    """Return ``(<root>/.work-plan, None)`` when the tier is safely contained.

    The shared-tier directory itself is never allowed to be a symlink, even if
    it currently points back inside ``root``.  Refusing the indirection keeps a
    later retarget from changing the write destination after validation.
    ``resolve(strict=False)`` also catches symlinked ancestors and proves that
    the resulting directory remains below the resolved repository/worktree.
    """
    candidate = root / ".work-plan"
    try:
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            return None, f"shared track root is not a directory: {root}"
        if candidate.is_symlink():
            return None, f"unsafe shared track directory is a symlink: {candidate}"
        if candidate.exists() and not candidate.is_dir():
            return None, f"unsafe shared track path is not a directory: {candidate}"
        resolved_candidate = candidate.resolve(strict=False)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return None, f"unsafe shared track directory escapes its root: {candidate}"
    return candidate, None


def resolve_shared_tier(entry: dict) -> tuple:
    """Resolve a repo's shared tier as ``(path, unsafe_reason)``.

    ``unsafe_reason`` is populated only when a candidate root exists but fails
    containment validation.  Operational absence (no local path, unavailable
    plan branch) remains ``(None, None)`` so read-only callers retain the
    existing graceful-degradation behaviour.
    """
    if not entry or not entry.get("local"):
        return None, None
    local_path = Path(entry["local"]).expanduser()
    branch = entry.get("plan_branch")
    if branch:
        worktree = ensure_worktree(local_path, branch)
        if worktree is None:
            return None, None
        return _contained_shared_tier(worktree)
    return _contained_shared_tier(local_path)


def shared_tier_dir(entry: dict) -> Optional[Path]:
    """The `.work-plan/` directory to read/write for a repo config `entry`.

    - `plan_branch` set  → the worktree's `.work-plan/` (None when the worktree
      can't be ensured, e.g. the branch isn't bootstrapped yet).
    - `plan_branch` unset → the working tree's `.work-plan/` (legacy, unchanged).

    Returns None when the entry has no `local` path. Never raises.
    """
    path, _unsafe_reason = resolve_shared_tier(entry)
    return path


# ---------------------------------------------------------------------------
# Phase 3 (#260): bootstrap + push. Creating an orphan plan branch, fetching a
# teammate's, pushing local plan commits to share them. All never-raise.
# ---------------------------------------------------------------------------

def create_orphan_worktree(local_path: Path, branch: str) -> Optional[Path]:
    """Create a worktree at the stable cache path holding a fresh ORPHAN
    `branch` whose tree is an empty `.work-plan/` (no shared history with the
    repo's code — like gh-pages). Returns the worktree path with `.work-plan/`
    created but NOT yet committed (the caller seeds it and commits via
    commit_shared_tier), or None on any failure. Never raises.

    Caller must have verified `branch` does not already exist (local or remote);
    this is the create path, not the connect path (use ensure_worktree to
    connect to an existing branch).
    """
    local_path = Path(local_path).expanduser()
    dest = _worktree_dir(local_path)
    if (dest / ".git").exists():
        return None  # a worktree is already cached here — caller should connect
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    # Detached worktree at HEAD, then orphan-checkout the plan branch and clear
    # the code out of it so only .work-plan/ remains.
    add = _git(local_path, "worktree", "add", "--detach", "--quiet", str(dest), "HEAD")
    if add is None or add.returncode != 0:
        return None
    orphan = _git(dest, "checkout", "--orphan", branch)
    if orphan is None or orphan.returncode != 0:
        _git(local_path, "worktree", "remove", "--force", str(dest))
        return None
    # Drop every code file from the orphan's index + working tree.
    if _git(dest, "rm", "-rf", "--quiet", ".") is None:
        _git(local_path, "worktree", "remove", "--force", str(dest))
        return None
    try:
        (dest / ".work-plan").mkdir(parents=True, exist_ok=True)
    except OSError:
        _git(local_path, "worktree", "remove", "--force", str(dest))
        return None
    return dest


def fetch_branch(local_path: Path, branch: str) -> bool:
    """Best-effort `git fetch origin <branch>` so remote_branch_exists is
    authoritative (a teammate may have published the plan branch). True on
    success, False on any failure/offline. Never raises — a read-only op."""
    proc = _git(Path(local_path).expanduser(), "fetch", "--quiet", "origin", branch)
    return proc is not None and proc.returncode == 0


def is_published(local_path: Path, branch: str) -> bool:
    """True if `branch` exists on origin (it's been shared). Never raises."""
    return remote_branch_exists(local_path, branch)


def rebase_onto_origin(worktree: Path, branch: str) -> bool:
    """Fetch origin/<branch> and rebase the worktree (checked out at <branch>)
    onto it, so a shared-tier write lands on top of any teammate's pushed plan
    changes instead of diverging (#241).

    Returns:
      True  — the worktree is now at-or-ahead of origin: rebase succeeded,
              there was nothing to replay, or the branch isn't published yet
              (local is authoritative — nothing to rebase onto).
      False — the rebase hit a conflict (it is ABORTED so the worktree is left
              clean, never half-rebased) or git couldn't run. The caller must
              NOT write — it surfaces {needs_rebase} and bails.

    Never raises.
    """
    wt = Path(worktree).expanduser()
    # Fetch so origin/<branch> is authoritative before we compare.
    fetch_branch(wt, branch)
    if not remote_branch_exists(wt, branch):
        return True  # unpublished — no upstream to rebase onto; local wins
    # --autostash: the normal flow is write-file-then-commit, so the worktree's
    # .work-plan/ is routinely dirty when we rebase. Without autostash git would
    # refuse the rebase on the dirty precondition and we'd report a spurious
    # {needs_rebase}; autostash shelves the local edits, rebases, and reapplies
    # them on top — so a clean rebase succeeds even with pending plan edits.
    proc = _git(wt, "rebase", "--autostash", f"origin/{branch}")
    if proc is None:
        return False
    if proc.returncode == 0:
        return True
    # True conflict (autostash reapply or replayed commits): abort so the
    # worktree is never left in a partially-rebased state. A blind write over a
    # diverged shared branch is exactly what this guard exists to prevent.
    _git(wt, "rebase", "--abort")
    return False


def unpushed_oneline(local_path: Path, branch: str) -> list:
    """One-line summaries of commits on local `branch` not yet on origin
    (`origin/<branch>..<branch>`). If origin/<branch> doesn't exist, every commit
    on `branch` is unpushed. Empty list on any failure. Never raises."""
    local_path = Path(local_path).expanduser()
    rng = (f"origin/{branch}..{branch}"
           if remote_branch_exists(local_path, branch) else branch)
    proc = _git(local_path, "log", "--oneline", "--no-color", rng)
    if proc is None or proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def push_plan_branch(local_path: Path, branch: str):
    """Push `branch` to origin, setting upstream. Returns the CompletedProcess
    (inspect .returncode / .stderr — the caller surfaces protected-branch and
    other failures) or None if git couldn't run. Never raises."""
    return _git(Path(local_path).expanduser(), "push", "--set-upstream",
                "origin", branch, timeout=120)
