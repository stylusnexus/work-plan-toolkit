"""Tests for GitHub state — uses mocks (gh requires auth)."""
import unittest
from unittest.mock import patch, MagicMock, call
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.github_state import (
    fetch_issues, fetch_issue, fetch_issues_concurrent,
    extract_priority, fetch_recent_issues, short_milestone,
    repo_visibility, _VIS_CACHE,
)


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


_ISSUE_JSON = '{"number": 1, "state": "OPEN", "labels": [], "title": "t", "milestone": null, "url": "u", "closedAt": null, "body": "", "updatedAt": "2026-01-01T00:00:00Z", "assignees": []}'
_ISSUE_DICT = {"number": 1, "state": "OPEN", "labels": [], "title": "t", "milestone": None, "url": "u", "closedAt": None, "body": "", "updatedAt": "2026-01-01T00:00:00Z", "assignees": []}


class FetchIssueTest(unittest.TestCase):
    """Unit tests for the single-issue primitive fetch_issue()."""

    @patch("lib.github_state.subprocess.run")
    def test_returns_dict_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_ISSUE_JSON)
        result = fetch_issue("org/repo", 1)
        self.assertIsNotNone(result)
        self.assertEqual(result["number"], 1)

    @patch("lib.github_state.subprocess.run")
    def test_returns_none_on_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = fetch_issue("org/repo", 1)
        self.assertIsNone(result)

    @patch("lib.github_state.subprocess.run")
    def test_returns_none_on_json_decode_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not-json{{{")
        result = fetch_issue("org/repo", 1)
        self.assertIsNone(result)

    @patch("lib.github_state.subprocess.run", side_effect=FileNotFoundError("gh not found"))
    def test_fetch_issue_returns_none_when_gh_missing(self, _):
        self.assertIsNone(fetch_issue("org/repo", 1))

    @patch("lib.github_state.subprocess.run")
    def test_calls_gh_with_correct_args(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_ISSUE_JSON)
        fetch_issue("org/repo", 42)
        args = mock_run.call_args[0][0]
        self.assertIn("gh", args)
        self.assertIn("42", args)
        self.assertIn("--repo", args)
        self.assertIn("org/repo", args)


class FetchIssuesConcurrentTest(unittest.TestCase):
    """Unit tests for the concurrent batch fetch fetch_issues_concurrent()."""

    def _make_fake_fetch(self, missing_num=None):
        """Return a fake fetch_issue that returns a canned dict or None."""
        def _fake(repo, number):
            if number == missing_num:
                return None
            return {"number": number, "state": "OPEN", "labels": [], "title": f"Issue {number}",
                    "milestone": None, "url": f"u/{number}", "closedAt": None, "body": "",
                    "updatedAt": "2026-01-01T00:00:00Z", "assignees": []}
        return _fake

    @patch("lib.github_state.fetch_issue")
    def test_returns_keyed_dict_for_successful_fetches(self, mock_fi):
        mock_fi.side_effect = self._make_fake_fetch()
        jobs = [("org/repo", 1), ("org/repo", 2)]
        result = fetch_issues_concurrent(jobs)
        self.assertIn(("org/repo", 1), result)
        self.assertIn(("org/repo", 2), result)
        self.assertEqual(result[("org/repo", 1)]["number"], 1)
        self.assertEqual(result[("org/repo", 2)]["number"], 2)

    @patch("lib.github_state.fetch_issue")
    def test_omits_none_results(self, mock_fi):
        mock_fi.side_effect = self._make_fake_fetch(missing_num=99)
        jobs = [("org/repo", 1), ("org/repo", 99)]
        result = fetch_issues_concurrent(jobs)
        self.assertIn(("org/repo", 1), result)
        self.assertNotIn(("org/repo", 99), result)

    @patch("lib.github_state.fetch_issue")
    def test_dedupes_duplicate_jobs(self, mock_fi):
        mock_fi.side_effect = self._make_fake_fetch()
        # same (repo, number) appears twice — should only call fetch_issue once
        jobs = [("org/repo", 5), ("org/repo", 5)]
        result = fetch_issues_concurrent(jobs)
        self.assertIn(("org/repo", 5), result)
        self.assertEqual(mock_fi.call_count, 1)

    @patch("lib.github_state.fetch_issue")
    def test_empty_jobs_returns_empty_dict(self, mock_fi):
        result = fetch_issues_concurrent([])
        self.assertEqual(result, {})
        mock_fi.assert_not_called()

    @patch("lib.github_state.fetch_issue")
    def test_different_repos_are_distinct_keys(self, mock_fi):
        mock_fi.side_effect = self._make_fake_fetch()
        jobs = [("org/repoA", 1), ("org/repoB", 1)]
        result = fetch_issues_concurrent(jobs)
        self.assertIn(("org/repoA", 1), result)
        self.assertIn(("org/repoB", 1), result)
        self.assertEqual(mock_fi.call_count, 2)

    @patch("lib.github_state.fetch_issue")
    def test_all_failures_returns_empty_dict(self, mock_fi):
        mock_fi.return_value = None
        jobs = [("org/repo", 10), ("org/repo", 11)]
        result = fetch_issues_concurrent(jobs)
        self.assertEqual(result, {})


class FetchIssuesAfterRefactorTest(unittest.TestCase):
    """Verify fetch_issues still returns the sequential list after refactor."""

    @patch("lib.github_state.subprocess.run")
    def test_returns_list_in_order(self, mock_run):
        responses = [
            MagicMock(returncode=0, stdout='{"number": 10, "state": "OPEN", "labels": [], "title": "a"}'),
            MagicMock(returncode=0, stdout='{"number": 20, "state": "CLOSED", "labels": [], "title": "b"}'),
        ]
        mock_run.side_effect = responses
        result = fetch_issues("org/repo", [10, 20])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["number"], 10)
        self.assertEqual(result[1]["number"], 20)

    @patch("lib.github_state.subprocess.run")
    def test_skips_failed_fetches(self, mock_run):
        responses = [
            MagicMock(returncode=0, stdout='{"number": 10, "state": "OPEN", "labels": []}'),
            MagicMock(returncode=1, stdout="", stderr="not found"),
            MagicMock(returncode=0, stdout='{"number": 30, "state": "OPEN", "labels": []}'),
        ]
        mock_run.side_effect = responses
        result = fetch_issues("org/repo", [10, 20, 30])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["number"], 10)
        self.assertEqual(result[1]["number"], 30)

    def test_empty_returns_empty(self):
        self.assertEqual(fetch_issues("org/repo", []), [])


if __name__ == "__main__":
    unittest.main()
