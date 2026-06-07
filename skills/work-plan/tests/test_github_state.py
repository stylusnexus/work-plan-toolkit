"""Tests for GitHub state — uses mocks (gh requires auth)."""
import json
import unittest
from unittest.mock import patch, MagicMock, call
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.github_state import (
    fetch_issues, fetch_issue, fetch_issues_concurrent,
    fetch_repo_issues_graphql, fetch_export_issues, _normalize_gql_node,
    extract_priority, fetch_recent_issues, short_milestone,
    repo_visibility, _VIS_CACHE, fetch_open_issues,
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


def _gql_response(nodes: dict) -> str:
    """Build a GraphQL JSON response string from a {alias: node|None} dict."""
    return json.dumps({"data": {"repository": nodes}})


# A canned mixed response: an Issue, a MERGED PullRequest, and a null node.
_GQL_NODES = {
    "i487": {"number": 487, "title": "An issue", "state": "OPEN",
             "assignees": {"nodes": [{"login": "x"}]},
             "milestone": {"title": "v1.0 — gate"}},
    "i99": {"number": 99, "title": "A PR", "state": "MERGED",
            "assignees": {"nodes": []}, "milestone": None},
    "i1556": None,
}


class NormalizeGqlNodeTest(unittest.TestCase):
    """Unit tests for _normalize_gql_node()."""

    def test_none_node_returns_none(self):
        self.assertIsNone(_normalize_gql_node(None))

    def test_issue_node_normalized(self):
        out = _normalize_gql_node(_GQL_NODES["i487"])
        self.assertEqual(out["number"], 487)
        self.assertEqual(out["title"], "An issue")
        self.assertEqual(out["state"], "OPEN")
        self.assertEqual(out["assignees"], [{"login": "x"}])
        self.assertEqual(out["milestone"], {"title": "v1.0 — gate"})

    def test_pr_state_preserved(self):
        out = _normalize_gql_node(_GQL_NODES["i99"])
        self.assertEqual(out["state"], "MERGED")
        self.assertEqual(out["assignees"], [])
        self.assertIsNone(out["milestone"])

    def test_missing_milestone_is_none(self):
        out = _normalize_gql_node({"number": 1, "title": "t", "state": "OPEN"})
        self.assertIsNone(out["milestone"])


class FetchRepoIssuesGraphqlTest(unittest.TestCase):
    """Unit tests for the batched GraphQL primitive fetch_repo_issues_graphql()."""

    @patch("lib.github_state.subprocess.run")
    def test_returns_normalized_keyed_dict_null_omitted(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_gql_response(_GQL_NODES))
        result = fetch_repo_issues_graphql("org/repo", [487, 99, 1556])
        # null i1556 omitted
        self.assertEqual(set(result.keys()), {487, 99})
        # normalized shapes
        self.assertEqual(result[487]["assignees"], [{"login": "x"}])
        self.assertEqual(result[487]["milestone"], {"title": "v1.0 — gate"})
        # PR state preserved
        self.assertEqual(result[99]["state"], "MERGED")
        self.assertIsNone(result[99]["milestone"])

    @patch("lib.github_state.subprocess.run")
    def test_uses_gh_api_graphql(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_gql_response({}))
        fetch_repo_issues_graphql("org/repo", [1])
        args = mock_run.call_args[0][0]
        self.assertEqual(args[:3], ["gh", "api", "graphql"])

    @patch("lib.github_state.subprocess.run")
    def test_chunks_into_multiple_calls(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_gql_response({}))
        # 5 numbers, chunk=2 → 3 chunks → 3 subprocess calls
        fetch_repo_issues_graphql("org/repo", [1, 2, 3, 4, 5], chunk=2)
        self.assertEqual(mock_run.call_count, 3)

    @patch("lib.github_state.subprocess.run")
    def test_nonzero_returncode_chunk_yields_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="err")
        self.assertEqual(fetch_repo_issues_graphql("org/repo", [1, 2]), {})

    @patch("lib.github_state.subprocess.run")
    def test_empty_stdout_chunk_yields_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="   ")
        self.assertEqual(fetch_repo_issues_graphql("org/repo", [1, 2]), {})

    @patch("lib.github_state.subprocess.run")
    def test_non_json_chunk_yields_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not-json{{{")
        self.assertEqual(fetch_repo_issues_graphql("org/repo", [1, 2]), {})

    @patch("lib.github_state.subprocess.run", side_effect=FileNotFoundError("gh not found"))
    def test_subprocess_exception_yields_empty(self, _):
        self.assertEqual(fetch_repo_issues_graphql("org/repo", [1, 2]), {})

    @patch("lib.github_state.subprocess.run")
    def test_invalid_repo_no_gh_call(self, mock_run):
        result = fetch_repo_issues_graphql("not-a-repo", [1, 2])
        self.assertEqual(result, {})
        mock_run.assert_not_called()

    @patch("lib.github_state.subprocess.run")
    def test_empty_numbers_no_gh_call(self, mock_run):
        result = fetch_repo_issues_graphql("org/repo", [])
        self.assertEqual(result, {})
        mock_run.assert_not_called()

    @patch("lib.github_state.subprocess.run")
    def test_non_int_numbers_yields_empty(self, mock_run):
        self.assertEqual(fetch_repo_issues_graphql("org/repo", ["not-a-number"]), {})
        mock_run.assert_not_called()


class FetchExportIssuesTest(unittest.TestCase):
    """Unit tests for the GraphQL-primary + per-issue fallback fetch_export_issues()."""

    def _make_map(self, *issues):
        """Build a {number: issue} map from a list of issue dicts."""
        return {i["number"]: i for i in issues}

    _ISSUE_1 = {"number": 1, "title": "First", "state": "OPEN", "assignees": [], "milestone": None}
    _ISSUE_2 = {"number": 2, "title": "Second", "state": "CLOSED", "assignees": [], "milestone": None}

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_graphql_called_once_per_repo(self, mock_gql, mock_fic):
        """fetch_repo_issues_graphql must be called ONCE per repo, not once per issue."""
        mock_gql.return_value = self._make_map(self._ISSUE_1, self._ISSUE_2)
        mock_fic.return_value = {}
        fetch_export_issues({"org/repo": [1, 2]})
        self.assertEqual(mock_gql.call_count, 1)

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_result_keyed_by_repo_number_tuple(self, mock_gql, mock_fic):
        mock_gql.return_value = self._make_map(self._ISSUE_1, self._ISSUE_2)
        mock_fic.return_value = {}
        result = fetch_export_issues({"org/repo": [1, 2]})
        self.assertIn(("org/repo", 1), result)
        self.assertIn(("org/repo", 2), result)
        self.assertEqual(result[("org/repo", 1)]["title"], "First")

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_missing_number_triggers_fallback(self, mock_gql, mock_fic):
        """A number absent from the GraphQL result goes to fetch_issues_concurrent."""
        mock_gql.return_value = self._make_map(self._ISSUE_1)  # only issue 1
        mock_fic.return_value = {("org/repo", 99): {"number": 99, "title": "Issue99",
                                                     "state": "CLOSED", "assignees": [],
                                                     "milestone": None}}
        result = fetch_export_issues({"org/repo": [1, 99]})
        self.assertIn(("org/repo", 1), result)        # from GraphQL
        self.assertIn(("org/repo", 99), result)       # from fallback
        self.assertEqual(result[("org/repo", 99)]["title"], "Issue99")
        mock_fic.assert_called_once()
        fallback_jobs = list(mock_fic.call_args[0][0])
        self.assertEqual(fallback_jobs, [("org/repo", 99)])

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_no_fallback_when_graphql_covers_all(self, mock_gql, mock_fic):
        mock_gql.return_value = self._make_map(self._ISSUE_1, self._ISSUE_2)
        mock_fic.return_value = {}
        fetch_export_issues({"org/repo": [1, 2]})
        mock_fic.assert_not_called()

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_multiple_repos_graphql_called_once_each(self, mock_gql, mock_fic):
        def _side(repo, numbers, max_workers=8):
            if repo == "org/repoA":
                return self._make_map(self._ISSUE_1)
            return self._make_map(self._ISSUE_2)
        mock_gql.side_effect = _side
        mock_fic.return_value = {}
        result = fetch_export_issues({"org/repoA": [1], "org/repoB": [2]})
        self.assertEqual(mock_gql.call_count, 2)
        self.assertIn(("org/repoA", 1), result)
        self.assertIn(("org/repoB", 2), result)

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_empty_input_returns_empty(self, mock_gql, mock_fic):
        result = fetch_export_issues({})
        self.assertEqual(result, {})
        mock_gql.assert_not_called()
        mock_fic.assert_not_called()

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_repo_with_empty_numbers_skipped(self, mock_gql, mock_fic):
        result = fetch_export_issues({"org/repo": []})
        self.assertEqual(result, {})
        mock_gql.assert_not_called()
        mock_fic.assert_not_called()

    @patch("lib.github_state.fetch_issues_concurrent")
    @patch("lib.github_state.fetch_repo_issues_graphql")
    def test_none_repo_skipped(self, mock_gql, mock_fic):
        result = fetch_export_issues({None: [1, 2]})
        self.assertEqual(result, {})
        mock_gql.assert_not_called()


class FetchOpenIssuesTest(unittest.TestCase):
    """Unit tests for fetch_open_issues() — all gh calls mocked."""

    _OPEN_ROWS = [
        {"number": 5, "title": "Open one", "state": "OPEN", "assignees": [], "milestone": None},
        {"number": 7, "title": "Open two", "state": "OPEN", "assignees": [{"login": "eve"}], "milestone": {"title": "v1.0"}},
    ]

    @patch("lib.github_state.subprocess.run")
    def test_returns_rows_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(self._OPEN_ROWS))
        result = fetch_open_issues("o/r")
        self.assertEqual(result, self._OPEN_ROWS)

    @patch("lib.github_state.subprocess.run")
    def test_calls_gh_issue_list_open(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        fetch_open_issues("o/r")
        args = mock_run.call_args[0][0]
        self.assertIn("gh", args)
        self.assertIn("issue", args)
        self.assertIn("list", args)
        self.assertIn("--repo", args)
        self.assertIn("o/r", args)
        # must request open issues (flag + value, space-separated) and the JSON fields
        self.assertIn("--state", args)
        self.assertEqual(args[args.index("--state") + 1], "open")
        self.assertIn("number,title,state,assignees,milestone", " ".join(args))

    @patch("lib.github_state.subprocess.run")
    def test_nonzero_returncode_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        self.assertEqual(fetch_open_issues("o/r"), [])

    @patch("lib.github_state.subprocess.run")
    def test_empty_stdout_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="   ")
        self.assertEqual(fetch_open_issues("o/r"), [])

    @patch("lib.github_state.subprocess.run")
    def test_bad_json_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="not-json{{")
        self.assertEqual(fetch_open_issues("o/r"), [])

    @patch("lib.github_state.subprocess.run", side_effect=Exception("gh missing"))
    def test_exception_returns_empty(self, _):
        self.assertEqual(fetch_open_issues("o/r"), [])

    @patch("lib.github_state.subprocess.run")
    def test_bad_repo_returns_empty_without_calling_gh(self, mock_run):
        self.assertEqual(fetch_open_issues("notarepo"), [])
        mock_run.assert_not_called()

    @patch("lib.github_state.subprocess.run")
    def test_custom_limit_passed(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        fetch_open_issues("o/r", limit=500)
        args = mock_run.call_args[0][0]
        self.assertIn("500", args)

    @patch("lib.github_state.subprocess.run")
    def test_returns_list_type(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(self._OPEN_ROWS))
        result = fetch_open_issues("o/r")
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
