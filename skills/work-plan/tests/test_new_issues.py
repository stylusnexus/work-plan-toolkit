"""Tests for new-issue matching."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.new_issues import match_issue_to_tracks


class MatchIssueTest(unittest.TestCase):
    def test_label_match_wins(self):
        issue = {"number": 9, "title": "unrelated", "labels": [{"name": "track/tabletop"}]}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(matches, ["tabletop"])

    def test_keyword_in_title(self):
        issue = {"number": 10, "title": "fix tabletop initiative tracker", "labels": []}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(matches, ["tabletop"])

    def test_no_match_returns_empty(self):
        issue = {"number": 11, "title": "boring thing", "labels": []}
        self.assertEqual(match_issue_to_tracks(issue, ["tabletop", "ux-redesign"]), [])

    def test_multiple_matches(self):
        issue = {"number": 12, "title": "tabletop ux redesign for combat", "labels": []}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(set(matches), {"tabletop", "ux-redesign"})


if __name__ == "__main__":
    unittest.main()
