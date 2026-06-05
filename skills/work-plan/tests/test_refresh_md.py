"""Tests for refresh-md row-append behavior (issue #77).

Before #77, refresh-md only rewrote the *status cell* of rows already in the
canonical table — it never appended rows for issues present in frontmatter but
missing from the table, yet still printed "All tracks in sync." These tests
pin the membership-aware behavior: missing frontmatter issues get appended in
frontmatter order, and the "in sync" message only prints when nothing changed.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import refresh_md
from lib.status_table import find_canonical_status_tables, ISSUE_NUM_RE

CANON_HEADER = (
    "## Issues (canonical)\n\n"
    "<!-- canonical-issue-table — auto-managed. -->\n\n"
    "| # | Title | Assignee | Status |\n"
    "|---|---|---|---|\n"
)


def _track(*, name, repo, issues, rows):
    body = CANON_HEADER + "\n".join(rows) + "\n\n---\n\n## Notes\n\nnarrative\n"
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake/{name}.md"),
        body=body,
        meta={"track": name, "status": "active",
              "github": {"repo": repo, "issues": list(issues)}},
        has_frontmatter=True,
        repo=repo,
    )


def _issue(num, title, state="OPEN", logins=()):
    return {"number": num, "title": title, "state": state,
            "assignees": [{"login": l} for l in logins]}


class RefreshAppendTest(unittest.TestCase):
    def _drive(self, track, issues, args):
        cfg = {"notes_root": "/tmp/fake"}
        with patch("commands.refresh_md.load_config", return_value=cfg), \
             patch("commands.refresh_md.discover_tracks", return_value=[track]), \
             patch("commands.refresh_md.fetch_issues", return_value=issues), \
             patch("commands.refresh_md.write_file") as mw:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = refresh_md.run(args)
        return rc, mw, buf.getvalue()

    def test_appends_missing_rows_in_frontmatter_order(self):
        track = _track(
            name="platform-health", repo="o/r",
            issues=[1, 2, 30, 40],  # 30, 40 newly slotted, not yet in table
            rows=["| #1 | first | — | 🔲 Open |",
                  "| #2 | second | — | ✅ Shipped |"],
        )
        issues = [_issue(1, "first"), _issue(2, "second", "CLOSED"),
                  _issue(30, "third", "OPEN", ["bob"]), _issue(40, "fourth", "CLOSED")]
        rc, mw, out = self._drive(track, issues, ["platform-health", "--yes"])

        self.assertEqual(rc, 0)
        mw.assert_called_once()
        new_body = mw.call_args[0][2]
        table = find_canonical_status_tables(new_body)[0]
        nums = [int(ISSUE_NUM_RE.search(r["cells"][0]).group(1)) for r in table["rows"]]
        self.assertEqual(nums, [1, 2, 30, 40])
        self.assertIn("| #30 | third | @bob | 🔲 Open |", new_body)
        self.assertIn("| #40 | fourth | — | ✅ Shipped |", new_body)
        self.assertNotIn("All tracks in sync.", out)
        self.assertIn("row", out.lower())

    def test_no_drift_reports_in_sync(self):
        track = _track(
            name="steady", repo="o/r", issues=[1, 2],
            rows=["| #1 | first | — | 🔲 Open |",
                  "| #2 | second | — | ✅ Shipped |"],
        )
        issues = [_issue(1, "first"), _issue(2, "second", "CLOSED")]
        rc, mw, out = self._drive(track, issues, ["steady", "--yes"])

        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("All tracks in sync.", out)


if __name__ == "__main__":
    unittest.main()
