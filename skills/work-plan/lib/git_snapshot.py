"""Per-invocation git snapshot: each fact about a repo or branch is read once (#421).

`brief` asks the same questions of the same branch for every track that
references it — does it exist, when was its last commit, is it ahead of dev, is
the working tree dirty. Run per track, ten tracks sharing one repo and one
branch launched 112 git subprocesses. Here every answer is computed lazily, by
the SAME helpers in `lib.git_state` (so ref safety and fail-soft behaviour are
unchanged), and remembered, so the count scales with distinct repos and
branches instead of track references.

A snapshot lives for one command invocation: build a `GitSnapshots`, pass it
down, drop it. It is deliberately not a module-level cache, so a long-lived
process (tests, the VS Code host) never serves stale git state.
"""
from pathlib import Path
from typing import Dict, Optional

from lib import git_state

_UNSET = object()


class RepoSnapshot:
    """Memoized answers for one repo. `repo_path` may be None/missing: every
    method then returns the same fallback the underlying helper would."""

    def __init__(self, repo_path):
        self.repo_path = repo_path
        self._ok = bool(repo_path) and Path(repo_path).exists()
        self._current = _UNSET
        self._dirty_count = _UNSET
        self._exists: Dict[str, bool] = {}
        self._last: Dict[str, object] = {}
        self._recent: Dict[tuple, bool] = {}
        self._ahead: Dict[tuple, int] = {}

    def current_branch(self) -> Optional[str]:
        if self._current is _UNSET:
            self._current = git_state.current_branch(self.repo_path)
        return self._current

    def uncommitted_file_count(self) -> int:
        if self._dirty_count is _UNSET:
            self._dirty_count = git_state.uncommitted_file_count(self.repo_path)
        return self._dirty_count

    def has_uncommitted(self) -> bool:
        return self.uncommitted_file_count() > 0

    def branch_exists(self, branch_name: str) -> bool:
        if branch_name not in self._exists:
            self._exists[branch_name] = git_state.branch_exists(branch_name, self.repo_path)
        return self._exists[branch_name]

    def last_commit_date(self, branch_name: str):
        if branch_name not in self._last:
            self._last[branch_name] = (
                git_state._last_commit_date_unchecked(branch_name, self.repo_path)
                if self.branch_exists(branch_name) else None
            )
        return self._last[branch_name]

    def commits_ahead(self, branch_name: str, base: str) -> int:
        key = (branch_name, base)
        if key not in self._ahead:
            self._ahead[key] = git_state.commits_ahead(branch_name, base, self.repo_path)
        return self._ahead[key]

    def has_recent_commits(self, branch_name: str, hours: int = 24) -> bool:
        key = (branch_name, hours)
        if key not in self._recent:
            self._recent[key] = (
                git_state._recent_commits_unchecked(branch_name, self.repo_path, hours)
                if self.branch_exists(branch_name) else False
            )
        return self._recent[key]

    def branch_in_progress(self, branch_name: str) -> bool:
        """Same rule as git_state.branch_in_progress, off the memoized facts."""
        if not self._ok or not self.branch_exists(branch_name):
            return False
        if self.current_branch() == branch_name and self.has_uncommitted():
            return True
        return self.has_recent_commits(branch_name, hours=24)


class GitSnapshots:
    """One RepoSnapshot per resolved repo path, for one command invocation."""

    def __init__(self):
        self._by_repo: Dict[str, RepoSnapshot] = {}

    def for_repo(self, repo_path) -> RepoSnapshot:
        if not repo_path:
            return RepoSnapshot(repo_path)
        try:
            key = str(Path(repo_path).resolve())
        except OSError:
            key = str(repo_path)
        if key not in self._by_repo:
            self._by_repo[key] = RepoSnapshot(repo_path)
        return self._by_repo[key]
