"""Tests for the list-open-issues subcommand (#282).

Mocks fetch_open_issues — runs offline, never touches the network.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import list_open_issues


def _row(number, title="t", state="OPEN", logins=(), milestone=None):
    """A raw gh issue row as fetch_open_issues returns."""
    d = {"number": number, "title": title, "state": state,
         "assignees": [{"login": l} for l in logins]}
    if milestone:
        d["milestone"] = {"title": milestone}
    return d


def _run(args, rows):
    with patch("commands.list_open_issues.fetch_open_issues", return_value=rows):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = list_open_issues.run(args)
    out = buf.getvalue()
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        parsed = None
    return rc, parsed


class ListOpenIssuesTest(unittest.TestCase):
    def test_emits_repo_and_normalized_issues(self):
        rows = [_row(91, "Rate-limit login", "OPEN", ["eve"], "v0.6"),
                _row(87, "Fix auth", "OPEN")]
        rc, out = _run(["--repo=o/r"], rows)
        self.assertEqual(rc, 0)
        self.assertEqual(out["repo"], "o/r")
        # Same Issue shape as the export (number/title/state/assignee/milestone,
        # plus the always-present in_progress flag — #271 keeps the two surfaces
        # identical, so list-open-issues carries it too, default False here since
        # this command has no track/branch context).
        self.assertEqual(
            out["issues"][0],
            {"number": 91, "title": "Rate-limit login", "state": "open",
             "assignee": "@eve", "milestone": "v0.6", "in_progress": False},
        )
        self.assertEqual(out["issues"][1],
                         {"number": 87, "title": "Fix auth", "state": "open",
                          "assignee": "—", "milestone": None, "in_progress": False})

    def test_exclude_filters_given_numbers(self):
        rows = [_row(1), _row(2), _row(3)]
        rc, out = _run(["--repo=o/r", "--exclude=1,3"], rows)
        self.assertEqual(rc, 0)
        self.assertEqual([i["number"] for i in out["issues"]], [2])

    def test_exclude_tolerates_blanks_and_nonnumeric(self):
        rows = [_row(1), _row(2)]
        rc, out = _run(["--repo=o/r", "--exclude=1, ,x,"], rows)
        self.assertEqual(rc, 0)
        self.assertEqual([i["number"] for i in out["issues"]], [2])

    def test_missing_repo_is_usage_error(self):
        rc, out = _run([], [])
        self.assertEqual(rc, 2)
        self.assertIn("error", out)

    def test_empty_fetch_yields_empty_issue_list(self):
        # fetch_open_issues returns [] on a bad/unreachable repo — not an error.
        rc, out = _run(["--repo=o/r"], [])
        self.assertEqual(rc, 0)
        self.assertEqual(out, {"repo": "o/r", "issues": []})


if __name__ == "__main__":
    unittest.main()
