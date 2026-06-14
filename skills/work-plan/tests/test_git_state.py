"""Tests for git_state pure functions."""
import unittest
import sys
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
    def test_returns_empty_when_repo_missing(self):
        self.assertEqual(hot_issue_numbers(None), set())
        self.assertEqual(hot_issue_numbers(Path("/nonexistent")), set())

    def test_maps_hot_feat_and_fix_branches_to_numbers(self):
        listing = "dev\nmain\nfeat/271-foo\nfix/88-bar\nchore/x\nwork-plan/plan\n"
        enum = mock.Mock(return_value=mock.Mock(returncode=0, stdout=listing))
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", enum), \
             mock.patch("lib.git_state.branch_in_progress",
                        side_effect=lambda b, p: b in ("feat/271-foo", "fix/88-bar")):
            self.assertEqual(hot_issue_numbers(Path("/repo")), {271, 88})

    def test_no_substring_collision_2710_is_not_271(self):
        listing = "feat/2710-y\n"
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git",
                        return_value=mock.Mock(returncode=0, stdout=listing)), \
             mock.patch("lib.git_state.branch_in_progress", return_value=True):
            self.assertEqual(hot_issue_numbers(Path("/repo")), {2710})

    def test_cold_matched_branch_excluded(self):
        listing = "feat/271-foo\n"
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git",
                        return_value=mock.Mock(returncode=0, stdout=listing)), \
             mock.patch("lib.git_state.branch_in_progress", return_value=False):
            self.assertEqual(hot_issue_numbers(Path("/repo")), set())

    def test_enumeration_failure_returns_empty(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=None):
            self.assertEqual(hot_issue_numbers(Path("/repo")), set())


if __name__ == "__main__":
    unittest.main()
