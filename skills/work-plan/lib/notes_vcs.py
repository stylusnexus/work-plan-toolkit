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

# Local git-config marker stamped on the repos work-plan creates for local
# history. We only ever auto-commit a repo carrying this marker, so we never
# adopt (and commit into) an arbitrary pre-existing repo the user pointed
# notes_root at.
_OWNED_KEY = "workplan.localhistory"


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


def has_remotes(notes_root: Path) -> bool:
    """True if the repo has ANY configured remote.

    A personal local-history repo must have none — otherwise private notes
    could be pushed off the machine. Used to refuse enabling/committing history
    on a remote-backed repo.
    """
    proc = _git(notes_root, "remote")
    return proc is not None and proc.returncode == 0 and bool(proc.stdout.strip())


def is_owned(notes_root: Path) -> bool:
    """True only if work-plan created this repo for local history.

    `init_repo` stamps a local git-config marker; auto-commit requires it, so we
    never commit into a repo we don't control (e.g. an existing clone the user
    pointed notes_root at).
    """
    proc = _git(notes_root, "config", "--local", "--get", _OWNED_KEY)
    return proc is not None and proc.returncode == 0 and proc.stdout.strip() == "true"


def mark_owned(notes_root: Path) -> bool:
    """Stamp the ownership marker into the repo's local config. Returns success."""
    proc = _git(notes_root, "config", "--local", _OWNED_KEY, "true")
    return proc is not None and proc.returncode == 0


def head_parent_sha(notes_root: Path) -> Optional[str]:
    """Short sha of HEAD's first parent, or None (root commit / no commits / not
    a repo). The viewer compares this to the previously-seen HEAD to confirm a
    post-write commit sits directly on top before offering Undo (#224 safety)."""
    proc = _git(notes_root, "rev-parse", "--short", "--verify", "HEAD^")
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def dirty_paths_checked(notes_root: Path) -> tuple:
    """Like `dirty_paths`, but distinguishes "clean tree" from "the git status
    call itself failed" (timeout, spawn error, not a repo) — both of which
    `dirty_paths` alone reports as an empty set. Returns (call_succeeded, paths).

    Callers that need to know WHETHER they can trust an empty result (e.g.
    doctor's dirty-file safety check, which must not treat "couldn't check" as
    "definitely clean") should call this instead of `dirty_paths`.
    """
    proc = _git(notes_root, "-c", "core.quotepath=false", "status", "--porcelain")
    if proc is None or proc.returncode != 0:
        return (False, set())
    paths = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.add(path)
    return (True, paths)


def dirty_paths(notes_root: Path) -> set:
    """Set of work-tree paths with staged/unstaged changes (raw, quotepath off).

    Empty set on any failure. Renames collapse to the destination path. Used by
    the dispatcher to commit ONLY what a command changed, leaving pre-existing
    dirty files untouched.
    """
    return dirty_paths_checked(notes_root)[1]


def last_commit_summary(notes_root: Path) -> Optional[str]:
    """'<short-sha> <subject>' of HEAD, or None (no commits / not a repo)."""
    proc = _git(notes_root, "log", "-1", "--pretty=format:%h %s")
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def last_commit_sha(notes_root: Path) -> Optional[str]:
    """Short sha of HEAD, or None (no commits / not a repo). The undo handle the
    VS Code viewer diffs across a write to decide whether to offer Undo (#224)."""
    proc = _git(notes_root, "log", "-1", "--pretty=format:%h")
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def revert(notes_root: Path, sha: Optional[str] = None) -> Optional[str]:
    """Revert `sha` (default HEAD) in notes_root; return the new commit's sha.

    Keeps git inside the engine so callers (the CLI `undo` verb, the viewer's
    Undo button) never shell out to git themselves. No-op (None) when notes_root
    isn't a git root we OWN with no remote (same boundary as auto_commit — we
    must never rewrite an unrelated project clone's history), when there's no
    commit to revert, or when `sha` is unsafe (empty / dash-led — git would read
    a dash-led value as an option). Never raises. Uses --no-edit (non-interactive).
    """
    root = Path(notes_root).expanduser()
    if not is_git_root(root) or not is_owned(root) or has_remotes(root):
        return None
    target = sha if sha is not None else "HEAD"
    # A dash-led ref would be parsed by git as an option, not a revision.
    if not target or target.startswith("-"):
        return None
    proc = _git(root, "revert", "--no-edit", target)
    if proc is None or proc.returncode != 0:
        return None
    return last_commit_sha(root)


def init_repo(notes_root: Path) -> bool:
    """git-init notes_root as a personal repo and make an initial commit.

    Writes a small `.gitignore` (OS cruft only), stages everything, and commits
    existing tracks so there's a baseline to diff against. Deliberately adds NO
    remote — the private tier is never pushed. Returns True on a clean init +
    initial commit, False on any failure (never raises).

    Idempotent-ish: re-running on a repo WE own re-commits only if there's
    something new. Refuses (returns False) to adopt a repo we did not create or
    one that has a remote — private notes must never be pushable, and we won't
    sweep an unrelated existing repo's files into history.
    """
    root = Path(notes_root).expanduser()
    if not root.is_dir():
        return False
    if is_git_root(root):
        # An existing repo: only proceed if it's one we own AND has no remote.
        if has_remotes(root) or not is_owned(root):
            return False
    else:
        if _git(root, "init") is None:
            return False
        # Stamp ownership immediately, before any commit, so this repo can never
        # later be mistaken for a foreign one (and a remote added after init is
        # still caught by auto_commit's per-commit no-remote check).
        if not mark_owned(root):
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


def auto_commit(notes_root: Path, message: str,
                paths: Optional[list] = None) -> Optional[str]:
    """Commit notes_root changes with `message`; return the new short SHA.

    Safety gates (all must hold, else no-op None):
      - notes_root is the git toplevel,
      - it carries the ownership marker (work-plan created it), and
      - it has NO remote (a personal, never-pushed history).

    When `paths` is given, stages ONLY those paths so unrelated pre-existing
    dirty files stay out of the commit; otherwise stages everything. Commits
    only if something is actually staged. Never raises — a git failure here must
    not change the calling command's exit code.
    """
    root = Path(notes_root).expanduser()
    if not is_git_root(root) or not is_owned(root) or has_remotes(root):
        return None
    if paths is None:
        if _git(root, "add", "-A") is None:
            return None
    else:
        if not paths:
            return None
        if _git(root, "add", "--", *paths) is None:
            return None
    # Commit only what's staged — scoped `add` above keeps unrelated dirty files
    # unstaged, so they're preserved rather than folded into this commit.
    staged = _git(root, "diff", "--cached", "--quiet")
    if staged is None or staged.returncode == 0:
        return None
    proc = _git(root, "commit", "-m", message)
    if proc is None or proc.returncode != 0:
        return None
    head = _git(root, "rev-parse", "--short", "HEAD")
    if head is None or head.returncode != 0:
        return None
    return head.stdout.strip() or None
