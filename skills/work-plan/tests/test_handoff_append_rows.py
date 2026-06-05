"""Tests that handoff self-heals canonical-table drift (issue #77).

handoff updates existing rows' status via update_row_status but, before #77,
never appended rows for frontmatter issues missing from the table. These tests
drive the derived handoff path (git skipped via local_path=None + no prior
handoff) and assert the missing rows are appended.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import handoff
from lib.status_table import find_canonical_status_tables, ISSUE_NUM_RE

CANON_HEADER = (
    "## Issues (canonical)\n\n"
    "<!-- canonical-issue-table — auto-managed. -->\n\n"
    "| # | Title | Assignee | Status |\n"
    "|---|---|---|---|\n"
)


def _track():
    body = (CANON_HEADER
            + "| #1 | first | — | 🔲 Open |\n"
            + "| #2 | second | — | ✅ Shipped |\n"
            + "\n---\n\n## Notes\n\nnarrative\n")
    return SimpleNamespace(
        name="platform-health",
        path=Path("/tmp/fake/platform-health.md"),
        body=body,
        meta={"track": "platform-health", "status": "active",
              "github": {"repo": "o/r", "issues": [1, 2, 30, 40]}},
        has_frontmatter=True,
        repo="o/r",
        local_path=None,  # skips all git attribution paths
    )


def _issue(num, title, state="OPEN"):
    return {"number": num, "title": title, "state": state, "assignees": []}


class HandoffAppendTest(unittest.TestCase):
    def test_derived_handoff_appends_missing_rows(self):
        track = _track()
        issues = [_issue(1, "first"), _issue(2, "second", "CLOSED"),
                  _issue(30, "third"), _issue(40, "fourth", "CLOSED")]
        with patch("commands.handoff.fetch_issues", return_value=issues), \
             patch("commands.handoff.write_file") as mw:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = handoff._derived_handoff(track)

        self.assertEqual(rc, 0)
        mw.assert_called_once()
        new_body = mw.call_args[0][2]
        table = find_canonical_status_tables(new_body)[0]
        nums = [int(ISSUE_NUM_RE.search(r["cells"][0]).group(1)) for r in table["rows"]]
        self.assertEqual(nums, [1, 2, 30, 40])
        self.assertIn("| #30 | third | — | 🔲 Open |", new_body)
        self.assertIn("| #40 | fourth | — | ✅ Shipped |", new_body)


if __name__ == "__main__":
    unittest.main()
