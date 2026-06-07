"""Tests for GitHub state — uses mocks (gh requires auth)."""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.github_state import fetch_issues, extract_priority, fetch_recent_issues, short_milestone, repo_visibility, _VIS_CACHE


class ExtractPriorityTest(unittest.TestCase):
    def test_p0_label(self):
        labels = [{"name": "priority/P0"}, {"name": "bug"}]
        self.assertEqual(extract_priority(labels), "P0")

    def test_no_priority_label_returns_p3(self):
        self.assertEqual(extract_priority([{"name": "bug"}]), "P3")

    def test_p2_label(self):
        self.assertEqual(extract_priority([{"name": "priority/P2"}]), "P2")


class ShortMilestoneTest(unittest.TestCase):
    def test_strips_dash_suffix(self):
        self.assertEqual(short_milestone({"title": "v0.4.0 — MVP Go-Live Gate"}), "v0.4.0")

    def test_returns_full_title_when_single_word(self):
        self.assertEqual(short_milestone({"title": "v1.0.0"}), "v1.0.0")

    def test_returns_empty_for_none(self):
        self.assertEqual(short_milestone(None), "")

    def test_returns_empty_for_missing_title(self):
        self.assertEqual(short_milestone({}), "")
        self.assertEqual(short_milestone({"title": ""}), "")

    def test_returns_empty_for_non_dict(self):
        self.assertEqual(short_milestone("v0.4.0"), "")


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


class RepoVisibilityTest(unittest.TestCase):
    @patch("lib.github_state.subprocess.run")
    def test_returns_public(self, m):
        _VIS_CACHE.clear()
        m.return_value = MagicMock(returncode=0, stdout='{"visibility":"PUBLIC"}')
        self.assertEqual(repo_visibility("o/r"), "PUBLIC")

    @patch("lib.github_state.subprocess.run")
    def test_none_on_failure(self, m):
        _VIS_CACHE.clear()
        m.return_value = MagicMock(returncode=1, stdout="", stderr="x")
        self.assertIsNone(repo_visibility("o/r"))

    def test_none_for_empty_repo(self):
        _VIS_CACHE.clear()
        self.assertIsNone(repo_visibility(""))
        self.assertIsNone(repo_visibility(None))

    @patch("lib.github_state.subprocess.run")
    def test_memoizes_result(self, m):
        _VIS_CACHE.clear()
        m.return_value = MagicMock(returncode=0, stdout='{"visibility":"PRIVATE"}')
        repo_visibility("o/r")
        repo_visibility("o/r")
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
