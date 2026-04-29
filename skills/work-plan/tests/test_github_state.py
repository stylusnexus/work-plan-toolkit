"""Tests for GitHub state — uses mocks (gh requires auth)."""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.github_state import fetch_issues, extract_priority, fetch_recent_issues


class ExtractPriorityTest(unittest.TestCase):
    def test_p0_label(self):
        labels = [{"name": "priority/P0"}, {"name": "bug"}]
        self.assertEqual(extract_priority(labels), "P0")

    def test_no_priority_label_returns_p3(self):
        self.assertEqual(extract_priority([{"name": "bug"}]), "P3")

    def test_p2_label(self):
        self.assertEqual(extract_priority([{"name": "priority/P2"}]), "P2")


class FetchIssuesTest(unittest.TestCase):
    @patch("lib.github_state.subprocess.run")
    def test_returns_list(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"number": 4254, "state": "OPEN", "labels": [{"name": "priority/P0"}], "title": "polls"}',
            returncode=0,
        )
        result = fetch_issues("stylusnexus/CritForge", [4254])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["number"], 4254)

    def test_empty_returns_empty(self):
        self.assertEqual(fetch_issues("stylusnexus/CritForge", []), [])


class FetchRecentIssuesTest(unittest.TestCase):
    @patch("lib.github_state.subprocess.run")
    def test_calls_gh_with_search(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='[{"number": 9999, "title": "new", "labels": [], "createdAt": "2026-04-28T10:00:00Z"}]',
            returncode=0,
        )
        result = fetch_recent_issues("stylusnexus/CritForge", since_iso="2026-04-27")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["number"], 9999)
        called_args = mock_run.call_args[0][0]
        self.assertIn("created:>=2026-04-27", " ".join(called_args))


if __name__ == "__main__":
    unittest.main()
