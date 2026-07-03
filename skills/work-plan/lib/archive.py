"""The archive move primitive: collision-checked move of a doc into
archive/<kind>/. For tracked files the move is a history-preserving `git mv`
(staged rename); for untracked/gitignored files it falls back to a plain
filesystem move. Eligibility (is-this-shipped) is the caller's job — this
only moves files."""
import shutil
from pathlib import Path, PurePosixPath

from lib import git_state
from lib import reconcile_actions


def move_to_archive(rel: str, repo_root, kind: str):
    """Move `rel` into archive/<kind>/. Returns:
      "archived"          tracked file: history-preserving `git mv` (staged rename),
      "archived_local"    untracked/gitignored file: plain filesystem move,
      "skipped_collision" destination already exists (never overwrite),
      None                hard failure (git mv failed on a tracked file, or OSError
                          on an untracked file).
    """
    dest = reconcile_actions.archive_dest(rel, kind)
    if (Path(repo_root) / dest).exists():
        return "skipped_collision"
    if git_state.is_tracked(rel, Path(repo_root)):
        if git_state.git_mv(rel, dest, repo_root):
            return "archived"
        return None
    # Untracked / gitignored — plain filesystem move.
    src_path = Path(repo_root) / rel
    dst_path = Path(repo_root) / dest
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        return "archived_local"
    except OSError:
        return None


def restore_from_archive(rel: str, repo_root):
    """Inverse of move_to_archive: move an archived doc back OUT of
    `.../archive/<kind>/<name>` to its original directory (`.../name`). Returns:
      "restored"          tracked file: history-preserving `git mv` (staged),
      "restored_local"    untracked/gitignored file: plain filesystem move,
      "skipped_collision" a live doc already exists at the destination,
      None                `rel` isn't under archive/<kind>/, or a hard move failure.
    Shared by unarchive-track (#328) and plan-unarchive (#388).
    """
    p = PurePosixPath(rel)
    # Expect .../archive/<kind>/<name>; the grandparent dir must be "archive".
    if p.parent.parent.name != "archive":
        return None
    dest = str(p.parent.parent.parent / p.name)
    if (Path(repo_root) / dest).exists():
        return "skipped_collision"
    if git_state.is_tracked(rel, Path(repo_root)):
        if git_state.git_mv(rel, dest, repo_root):
            return "restored"
        return None
    # Untracked / gitignored — plain filesystem move.
    src_path = Path(repo_root) / rel
    dst_path = Path(repo_root) / dest
    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        return "restored_local"
    except OSError:
        return None
