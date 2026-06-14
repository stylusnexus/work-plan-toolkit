"""Tests for git_state pure functions."""
import unittest
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.git_state import (
    gap_seconds_to_label, parse_iso_timestamp,
    branch_in_progress, hot_issue_numbers,
)


class GapLabelTest(unittest.TestCase):
    def test_minutes(self):
        self.assertEqual(gap_seconds_to_label(30 * 60), "30m ago")

    def test_one_hour(self):
        self.assertEqual(gap_seconds_to_label(3600), "1h ago")

    def test_six_hours(self):
        self.assertEqual(gap_seconds_to_label(6 * 3600), "6h ago")

    def test_one_day(self):
        self.assertEqual(gap_seconds_to_label(86400), "1d ago")

    def test_multi_days(self):
        self.assertEqual(gap_seconds_to_label(5 * 86400 + 3600), "5d ago")


class ParseTimestampTest(unittest.TestCase):
    def test_iso_with_hour(self):
        dt = parse_iso_timestamp("2026-04-23T22:14")
        self.assertEqual(dt.hour, 22)

    def test_iso_date_only(self):
        dt = parse_iso_timestamp("2026-04-23")
        self.assertEqual(dt.year, 2026)


class BranchInProgressTest(unittest.TestCase):
    def test_returns_false_when_repo_path_missing(self):
        self.assertFalse(branch_in_progress("any-branch", None))

    def test_returns_false_when_path_doesnt_exist(self):
        self.assertFalse(branch_in_progress("any-branch", Path("/nonexistent")))


class HotIssueNumbersTest(unittest.TestCase):
    def setUp(self):
        # hot_issue_numbers memoizes per resolved path; reset between cases so a
        # prior test's "/repo" result doesn't leak into the next.
        from lib import git_state
        git_state._reset_hot_cache()

    def _ref_line(self, branch, age_hours):
        ts = int((datetime.now() - timedelta(hours=age_hours)).timestamp())
        return f"{branch}\t{ts}"

    def _enum(self, *lines):
        return mock.Mock(return_value=mock.Mock(returncode=0,
                                                stdout="\n".join(lines) + "\n"))

    def test_returns_empty_when_repo_missing(self):
        self.assertEqual(hot_issue_numbers(None), set())
        self.assertEqual(hot_issue_numbers(Path("/nonexistent")), set())

    def test_recent_feat_and_fix_branches_are_hot(self):
        # Two recently-committed feat/fix branches + cold/non-matching ones.
        lines = ["dev\t0", "main\t0",
                 self._ref_line("feat/271-foo", 1),    # 1h ago -> hot
                 self._ref_line("fix/88-bar", 5),       # 5h ago -> hot
                 self._ref_line("feat/9-old", 100),     # 100h ago -> cold
                 "chore/x\t0", "work-plan/plan\t0"]
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", self._enum(*lines)), \
             mock.patch("lib.git_state.current_branch", return_value=None):
            self.assertEqual(hot_issue_numbers(Path("/repo")), {271, 88})

    def test_no_substring_collision_2710_is_not_271(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git",
                        self._enum(self._ref_line("feat/2710-y", 1))), \
             mock.patch("lib.git_state.current_branch", return_value=None):
            self.assertEqual(hot_issue_numbers(Path("/repo")), {2710})

    def test_cold_matched_branch_excluded(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git",
                        self._enum(self._ref_line("feat/271-foo", 48))), \
             mock.patch("lib.git_state.current_branch", return_value=None):
            self.assertEqual(hot_issue_numbers(Path("/repo")), set())

    def test_uncommitted_on_current_branch_is_hot_even_if_cold(self):
        # A cold (old-tip) feat branch that's checked out with uncommitted work.
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git",
                        self._enum(self._ref_line("feat/271-foo", 200))), \
             mock.patch("lib.git_state.current_branch", return_value="feat/271-foo"), \
             mock.patch("lib.git_state.has_uncommitted", return_value=True):
            self.assertEqual(hot_issue_numbers(Path("/repo")), {271})

    def test_enumeration_failure_returns_empty(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=None):
            self.assertEqual(hot_issue_numbers(Path("/repo")), set())

    def test_memoizes_per_resolved_path(self):
        # Second call with the same path must NOT re-invoke git.
        enum = self._enum(self._ref_line("feat/271-foo", 1))
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", enum), \
             mock.patch("lib.git_state.current_branch", return_value=None):
            self.assertEqual(hot_issue_numbers(Path("/repo")), {271})
            self.assertEqual(hot_issue_numbers(Path("/repo")), {271})
            self.assertEqual(enum.call_count, 1)


if __name__ == "__main__":
    unittest.main()
