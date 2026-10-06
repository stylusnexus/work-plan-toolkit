"""brief reads each branch and repo once, not once per track reference (#421).

git is faked at the `lib.git_state._git` seam, so nothing here touches a real
repo or the network. The fake records every command, which is what lets these
tests assert subprocess COUNTS and that the snapshot answers exactly what the
direct helpers answer.
"""
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import brief
from lib import git_state
from lib.closure import compute_signals
from lib.git_snapshot import GitSnapshots, RepoSnapshot
from lib.tracks import Track

BRANCHES = {"dev", "feat/1-a", "feat/2-b"}


def _proc(out="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr="")


class FakeGit:
    """Canned answers keyed by the git subcommand; records every call."""

    def __init__(self, current="feat/1-a", dirty=2, branches=BRANCHES):
        self.calls = []
        self.current, self.dirty, self.branches = current, dirty, set(branches)

    def __call__(self, repo_path, *args, timeout=20):
        self.calls.append(args)
        if args[:2] == ("rev-parse", "--verify"):
            return _proc(rc=0 if args[2] in self.branches else 1)
        if args[:2] == ("branch", "--show-current"):
            return _proc(self.current + "\n")
        if args[:2] == ("status", "--short"):
            return _proc(" M f\n" * self.dirty)
        if args[0] == "log" and args[1] == "-1":
            # Always 30 days old, so the closure scan visits every branch.
            return _proc((datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S") + "+00:00")
        if args[0] == "log":
            return _proc("abc123")           # `log <branch> --since=...`
        if args[0] == "rev-list":
            return _proc("3\n")
        raise AssertionError(f"unexpected git call: {args}")


def _track(i, repo_path, branches):
    return Track(
        path=Path(f"/notes/r/t{i}.md"), name=f"t{i}", has_frontmatter=True,
        needs_init=False, needs_filing=False, repo="org/r", folder="r",
        local_path=repo_path,
        meta={"status": "active", "track": f"t{i}",
              "github": {"issues": [], "branches": list(branches)}, "next_up": []},
        body="",
    )


class SnapshotMatchesDirectHelpersTest(unittest.TestCase):
    def test_every_answer_equals_the_unsnapshotted_helper(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            for current, dirty in (("feat/1-a", 2), ("feat/1-a", 0), ("dev", 3)):
                fake = FakeGit(current=current, dirty=dirty)
                with mock.patch.object(git_state, "_git", fake):
                    snap = RepoSnapshot(repo)
                    for b in ("feat/1-a", "feat/2-b", "gone", "--output=/x"):
                        with self.subTest(current=current, dirty=dirty, branch=b):
                            self.assertEqual(snap.branch_exists(b), git_state.branch_exists(b, repo))
                            self.assertEqual(snap.last_commit_date(b), git_state.last_commit_date(b, repo))
                            self.assertEqual(snap.commits_ahead(b, "dev"), git_state.commits_ahead(b, "dev", repo))
                            self.assertEqual(snap.branch_in_progress(b), git_state.branch_in_progress(b, repo))
                    self.assertEqual(snap.current_branch(), git_state.current_branch(repo))
                    self.assertEqual(snap.uncommitted_file_count(), git_state.uncommitted_file_count(repo))
                    self.assertEqual(snap.has_uncommitted(), git_state.has_uncommitted(repo))

    def test_missing_repo_path_answers_like_the_helpers_without_calling_git(self):
        fake = FakeGit()
        with mock.patch.object(git_state, "_git", fake):
            for path in (None, Path("/nonexistent/nope")):
                snap = GitSnapshots().for_repo(path)
                self.assertFalse(snap.branch_exists("dev"))
                self.assertFalse(snap.branch_in_progress("dev"))
                self.assertIsNone(snap.last_commit_date("dev"))
                self.assertEqual(snap.commits_ahead("dev", "main"), 0)
                self.assertEqual(snap.uncommitted_file_count(), 0)
        self.assertEqual(fake.calls, [])

    def test_unsafe_ref_never_reaches_git(self):
        with tempfile.TemporaryDirectory() as d:
            fake = FakeGit()
            with mock.patch.object(git_state, "_git", fake):
                snap = RepoSnapshot(Path(d))
                self.assertFalse(snap.branch_exists("--output=/tmp/poc"))
                self.assertIsNone(snap.last_commit_date("--output=/tmp/poc"))
                self.assertEqual(snap.commits_ahead("--output=/tmp/poc", "dev"), 0)
                self.assertEqual(snap.commits_ahead("dev", "--all"), 0)
                self.assertFalse(snap.branch_in_progress("--output=/tmp/poc"))
            self.assertEqual(fake.calls, [])

    def test_git_failure_is_fail_soft(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(git_state, "_git", return_value=None):
                snap = RepoSnapshot(Path(d))
                self.assertFalse(snap.branch_in_progress("dev"))
                self.assertEqual(snap.commits_ahead("dev", "main"), 0)
                self.assertIsNone(snap.last_commit_date("dev"))
                self.assertIsNone(snap.current_branch())
                self.assertEqual(snap.uncommitted_file_count(), 0)


class SnapshotCountsTest(unittest.TestCase):
    def _blocks(self, tracks, snapshots):
        with mock.patch.object(brief, "hot_issue_numbers", return_value=set()):
            return [brief._build_track_block(t, {}, datetime.now(), snapshots=snapshots)
                    for t in tracks]

    def test_ten_tracks_sharing_one_branch_cost_one_read_per_fact(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            tracks = [_track(i, repo, ["feat/1-a"]) for i in range(10)]
            fake = FakeGit()
            with mock.patch.object(git_state, "_git", fake):
                blocks = self._blocks(tracks, GitSnapshots())
            kinds = sorted(c[0] for c in fake.calls)
            # current branch, status, then for the ONE branch: rev-parse, rev-list,
            # log -1. (It is the current, dirty branch, so "in progress" is
            # decided without a `log --since` query.)
            self.assertEqual(kinds, ["branch", "log", "rev-list", "rev-parse", "status"])
            self.assertEqual(len(fake.calls), 5)
            # ...and every track still got the same display data.
            first = blocks[0]["active_branches"]
            self.assertEqual(first, [{"name": "feat/1-a", "ahead": 3, "uncommitted_files": 2}])
            self.assertTrue(all(b["active_branches"] == first for b in blocks))
            self.assertTrue(all(b["operational_status"] == "in-progress" for b in blocks))

    def test_without_sharing_the_count_scales_with_tracks(self):
        # The contrast case: a snapshot per track (no sharing) repeats the reads.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            fake = FakeGit()
            with mock.patch.object(git_state, "_git", fake):
                for i in range(10):
                    self._blocks([_track(i, repo, ["feat/1-a"])], GitSnapshots())
            self.assertEqual(len(fake.calls), 50)

    def test_count_scales_with_distinct_branches_not_references(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            tracks = [_track(i, repo, ["feat/1-a", "feat/2-b"]) for i in range(10)]
            fake = FakeGit()
            with mock.patch.object(git_state, "_git", fake):
                self._blocks(tracks, GitSnapshots())
            # 2 per repo (branch, status); 3 for the current dirty branch
            # (rev-parse, rev-list, log -1) and 4 for the other (adds log --since).
            self.assertEqual(len(fake.calls), 2 + 3 + 4)

    def test_dirty_state_is_read_once_per_repo(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            fake = FakeGit()
            with mock.patch.object(git_state, "_git", fake):
                self._blocks([_track(i, repo, ["feat/1-a"]) for i in range(10)], GitSnapshots())
            self.assertEqual(sum(1 for c in fake.calls if c[0] == "status"), 1)

    def test_two_spellings_of_one_path_share_a_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            snaps = GitSnapshots()
            self.assertIs(snaps.for_repo(Path(d)), snaps.for_repo(Path(d) / "." / ""))
            with tempfile.TemporaryDirectory() as other:
                self.assertIsNot(snaps.for_repo(Path(d)), snaps.for_repo(Path(other)))


class ClosureSharesTheSnapshotTest(unittest.TestCase):
    def test_closure_signals_are_identical_with_and_without_a_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            meta = {"github": {"issues": [], "branches": ["feat/1-a", "gone"]}, "next_up": []}
            with mock.patch.object(git_state, "_git", FakeGit()):
                direct = compute_signals(meta, [], repo, 0)
                shared = compute_signals(meta, [], repo, 0, snapshot=RepoSnapshot(repo))
            self.assertEqual(direct, shared)

    def test_display_and_closure_use_one_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            meta = {"github": {"issues": [], "branches": ["feat/1-a"]}, "next_up": []}
            fake = FakeGit()
            with mock.patch.object(git_state, "_git", fake):
                snap = RepoSnapshot(repo)
                snap.branch_in_progress("feat/1-a")          # display side
                before = list(fake.calls)
                compute_signals(meta, [], repo, 0, snapshot=snap)   # closure side
            # Closure reuses the existence check display already made; the only
            # new read is the commit date display never needed.
            self.assertEqual([c[0] for c in fake.calls[len(before):]], ["log"])
            self.assertEqual(sum(1 for c in fake.calls if c[0] == "rev-parse"), 1)


if __name__ == "__main__":
    unittest.main()
