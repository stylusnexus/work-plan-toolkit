"""Opt-in local version control for the private notes_root tier (#103).

The shared tier (`<repo>/.work-plan/`) is version-controlled by the repo it
lives in. The private tier (`notes_root`, e.g. `Project Notes/`) is not — so a
track edit (slot/group/handoff/close/set) has no history or undo. This module
adds an opt-in, *personal, never-pushed* git repo at notes_root: every
track-mutating command becomes an undoable commit + diff.

Every helper here NEVER raises — git absence, a stuck lock, a slow filesystem,
or a non-repo all resolve to "do nothing". A VCS failure must never change a
command's exit code (the dispatcher relies on this).

Safety rule: we only ever operate when notes_root is the git TOPLEVEL. If
notes_root sits inside someone else's repo (the workspace, a clone), we refuse
to `git add -A` there — that would sweep unrelated files into a foreign repo.
`notes-vcs init` makes notes_root its own root, satisfying this.
"""
import subprocess
from pathlib import Path
from typing import Optional

# Bound every git subprocess so a stuck lock or slow FS can't stall the CLI
# (mirrors git_state.GIT_TIMEOUT; kept local to avoid a cross-module coupling).
GIT_TIMEOUT = 20

_GITIGNORE = ".DS_Store\nThumbs.db\n"
_INIT_COMMIT_MSG = "work-plan: initialize notes_root local history"


def _git(notes_root, *args, timeout: int = GIT_TIMEOUT):
    """Run `git -C <notes_root> <args>`; return CompletedProcess or None.

    None means git is missing, timed out, or the spawn failed — callers treat
    it as "no data / could not act", preserving the never-raise contract.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(notes_root), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def is_git_root(notes_root: Path) -> bool:
    """True only if notes_root is itself the toplevel of a git work tree.

    A bare `.git` existence check would also pass for a subdirectory of a larger
    repo, where `git add -A` would stage unrelated files. We compare the
    resolved toplevel to the resolved notes_root so auto-commit only ever fires
    on a repo we own.
    """
    if not notes_root:
        return False
    root = Path(notes_root).expanduser()
    if not root.is_dir():
        return False
    proc = _git(root, "rev-parse", "--show-toplevel")
    if proc is None or proc.returncode != 0:
        return False
    top = proc.stdout.strip()
    if not top:
        return False
    try:
        return Path(top).resolve() == root.resolve()
    except OSError:
        return False


def is_under_git(notes_root: Path) -> bool:
    """True if notes_root is inside ANY git work tree (root or subdir).

    Used by status/nudge messaging to distinguish "not a repo at all" from
    "inside a repo but not its root" (the latter we deliberately won't touch).
    """
    if not notes_root:
        return False
    root = Path(notes_root).expanduser()
    if not root.is_dir():
        return False
    proc = _git(root, "rev-parse", "--is-inside-work-tree")
    return proc is not None and proc.returncode == 0 and proc.stdout.strip() == "true"


def has_changes(notes_root: Path) -> bool:
    """True if the notes_root work tree has staged or unstaged changes."""
    proc = _git(notes_root, "status", "--short")
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def last_commit_summary(notes_root: Path) -> Optional[str]:
    """'<short-sha> <subject>' of HEAD, or None (no commits / not a repo)."""
    proc = _git(notes_root, "log", "-1", "--pretty=format:%h %s")
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def init_repo(notes_root: Path) -> bool:
    """git-init notes_root as a personal repo and make an initial commit.

    Writes a small `.gitignore` (OS cruft only), stages everything, and commits
    existing tracks so there's a baseline to diff against. Deliberately adds NO
    remote — the private tier is never pushed. Returns True on a clean init +
    initial commit, False on any failure (never raises).

    Idempotent-ish: re-running on an already-inited root re-runs `git init`
    (a no-op for git) and commits only if there's something new.
    """
    root = Path(notes_root).expanduser()
    if not root.is_dir():
        return False
    if _git(root, "init") is None:
        return False
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        try:
            gitignore.write_text(_GITIGNORE, encoding="utf-8")
        except OSError:
            return False
    if _git(root, "add", "-A") is None:
        return False
    # Nothing to commit (e.g. re-init of an unchanged repo) is success, not error.
    if not has_changes(root) and last_commit_summary(root) is not None:
        return True
    proc = _git(root, "commit", "-m", _INIT_COMMIT_MSG)
    return proc is not None and proc.returncode == 0


def auto_commit(notes_root: Path, message: str) -> Optional[str]:
    """Stage all of notes_root and commit with `message`; return the new SHA.

    No-op (returns None) when notes_root is not a git root, or when the work
    tree is clean. Never raises — a git failure here must not change the calling
    command's exit code.
    """
    root = Path(notes_root).expanduser()
    if not is_git_root(root):
        return None
    if _git(root, "add", "-A") is None:
        return None
    if not has_changes(root):
        return None
    proc = _git(root, "commit", "-m", message)
    if proc is None or proc.returncode != 0:
        return None
    head = _git(root, "rev-parse", "--short", "HEAD")
    if head is None or head.returncode != 0:
        return None
    return head.stdout.strip() or None
