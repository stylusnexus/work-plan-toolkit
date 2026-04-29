"""Tests for drift detection."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.drift import detect_drift


class DetectDriftTest(unittest.TestCase):
    def test_no_drift_when_table_matches(self):
        body = (
            "| # | Title | Status |\n"
            "|---|---|---|\n"
            "| #1 | foo | ✅ Shipped |\n"
        )
        github_issues = [{"number": 1, "state": "CLOSED"}]
        self.assertEqual(detect_drift(body, github_issues), [])

    def test_drift_when_open_in_md_closed_in_github(self):
        body = (
            "| # | Title | Status |\n"
            "|---|---|---|\n"
            "| #1 | foo | 🔲 Open |\n"
        )
        github_issues = [{"number": 1, "state": "CLOSED"}]
        drift = detect_drift(body, github_issues)
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["issue"], 1)

    def test_no_table_returns_empty(self):
        self.assertEqual(detect_drift("# No table\n", [{"number": 1, "state": "CLOSED"}]), [])


if __name__ == "__main__":
    unittest.main()
