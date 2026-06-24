"""The archive move primitive: collision-checked move of a doc into
archive/<kind>/. For tracked files the move is a history-preserving `git mv`
(staged rename); for untracked/gitignored files it falls back to a plain
filesystem move. Eligibility (is-this-shipped) is the caller's job — this
only moves files."""
import shutil
from pathlib import Path

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
