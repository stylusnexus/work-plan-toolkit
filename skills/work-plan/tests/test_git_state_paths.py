"""Tests for path-level git helpers (mock subprocess; offline)."""
import unittest
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import git_state


class PathLastCommitDateTest(unittest.TestCase):
    def test_returns_none_when_path_missing(self):
        self.assertIsNone(git_state.path_last_commit_date("x", None))

    def test_parses_iso(self):
        fake = SimpleNamespace(returncode=0, stdout="2026-04-02T13:05:11-05:00\n")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            dt = git_state.path_last_commit_date("docs/x.md", Path("/repo"))
        self.assertIsInstance(dt, datetime)
        self.assertEqual(dt.date(), date(2026, 4, 2))

    def test_empty_output_is_none(self):
        fake = SimpleNamespace(returncode=0, stdout="")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            self.assertIsNone(git_state.path_last_commit_date("docs/x.md", Path("/repo")))


class PathCommittedSinceTest(unittest.TestCase):
    def test_true_when_log_nonempty(self):
        fake = SimpleNamespace(returncode=0, stdout="abc123\n")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            self.assertTrue(
                git_state.path_committed_since("src/a.ts", date(2026, 3, 1), Path("/repo")))

    def test_false_when_empty(self):
        fake = SimpleNamespace(returncode=0, stdout="")
        with mock.patch("lib.git_state.subprocess.run", return_value=fake), \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            self.assertFalse(
                git_state.path_committed_since("src/a.ts", date(2026, 3, 1), Path("/repo")))


if __name__ == "__main__":
    unittest.main()
