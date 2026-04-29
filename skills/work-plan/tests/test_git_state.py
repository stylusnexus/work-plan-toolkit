"""Tests for git_state pure functions."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.git_state import (
    gap_seconds_to_label, parse_iso_timestamp,
    branch_in_progress,
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


if __name__ == "__main__":
    unittest.main()
