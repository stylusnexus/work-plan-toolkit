"""Tests for the plan-status staleness clock (#164).

The clock keys off a plan's DECLARED manifest files (which get committed) — not
the plan doc's own git date, which is null because plan docs are gitignored.
All git is mocked; these run offline.
"""
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from lib import git_state
from lib import manifest
from lib import verdict as verdict_mod
from commands import plan_status


class TestPathsLastCommitDate(unittest.TestCase):
    def test_returns_max_date_over_paths(self):
        proc = mock.Mock(returncode=0, stdout="2026-06-10T12:00:00+00:00")
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git", return_value=proc):
            got = git_state.paths_last_commit_date(
                ["a.py", "b.py"], Path("/repo"))
        self.assertEqual(got, datetime(2026, 6, 10, 12, 0, 0))

    def test_empty_paths_is_none(self):
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git") as g:
            self.assertIsNone(git_state.paths_last_commit_date([], Path("/repo")))
            g.assert_not_called()

    def test_empty_stdout_is_none(self):
        proc = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git", return_value=proc):
            self.assertIsNone(
                git_state.paths_last_commit_date(["a.py"], Path("/repo")))


if __name__ == "__main__":
    unittest.main()
