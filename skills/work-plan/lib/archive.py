"""The archive move primitive: collision-checked, history-preserving `git mv`
of a doc into archive/<kind>/. Eligibility (is-this-shipped) is the caller's
job — this only moves files."""
from pathlib import Path

from lib import git_state
from lib import reconcile_actions


def move_to_archive(rel: str, repo_root, kind: str):
    """git-mv `rel` into archive/<kind>/. Returns:
      "archived"          on a clean move,
      "skipped_collision" if the destination already exists (never overwrite),
      None                if git_mv failed for any other reason (hard error).
    """
    dest = reconcile_actions.archive_dest(rel, kind)
    if (Path(repo_root) / dest).exists():
        return "skipped_collision"
    if git_state.git_mv(rel, dest, repo_root):
        return "archived"
    return None
