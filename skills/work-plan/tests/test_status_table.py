"""Tests for status_table parser/updater."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.status_table import (
    find_status_table, update_row_status, ISSUE_NUM_RE,
    render_issue_row, append_rows, sync_missing_rows,
    find_canonical_status_tables, CANONICAL_MARKER,
    render_canonical_table, strip_canonical_block, insert_canonical_block,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _canonical_body(rows):
    """Build a body with a canonical issue table containing the given rows.

    `rows` is a list of pre-rendered row strings (without leading/trailing
    newline). A trailing narrative section is included to prove appends land
    before it, not at end-of-body.
    """
    lines = [
        "## Issues (canonical)",
        "",
        f"{CANONICAL_MARKER} — auto-managed. -->",
        "",
        "| # | Title | Assignee | Status |",
        "|---|---|---|---|",
    ]
    lines.extend(rows)
    lines.extend(["", "---", "", "## Notes", "", "Some narrative here."])
    return "\n".join(lines)


class FindStatusTableTest(unittest.TestCase):
    def test_finds_table_with_status_col(self):
        body = (FIXTURES / "with_status_table.md").read_text()
        table = find_status_table(body)
        self.assertIsNotNone(table)
        self.assertEqual(table["status_col_index"], 2)
        self.assertEqual(len(table["rows"]), 3)

    def test_returns_none_when_no_status_table(self):
        self.assertIsNone(find_status_table("# Just text"))


class UpdateRowStatusTest(unittest.TestCase):
    def test_updates_one_row(self):
        body = (FIXTURES / "with_status_table.md").read_text()
        new = update_row_status(body, 4254, "✅ Shipped (PR #9999)")
        self.assertIn("✅ Shipped (PR #9999)", new)
        self.assertIn("✅ Shipped ", new)


class RenderIssueRowTest(unittest.TestCase):
    def test_renders_canonical_row_shape(self):
        row = render_issue_row(487, "fix the thing", "@alice", "🔲 Open")
        self.assertEqual(row, "| #487 | fix the thing | @alice | 🔲 Open |")

    def test_milestone_arg_adds_fifth_column(self):
        row = render_issue_row(487, "fix", "@alice", "🔲 Open", milestone="v0.4.0")
        self.assertEqual(row, "| #487 | fix | v0.4.0 | @alice | 🔲 Open |")

    def test_empty_milestone_still_renders_column(self):
        # "" is distinct from None: the column is present but blank.
        row = render_issue_row(487, "fix", "@alice", "🔲 Open", milestone="")
        self.assertEqual(row, "| #487 | fix |  | @alice | 🔲 Open |")


class RenderCanonicalTableTest(unittest.TestCase):
    def _gh(self, num, title, state="OPEN", milestone=None):
        d = {"number": num, "title": title, "state": state, "assignees": []}
        if milestone:
            d["milestone"] = {"title": milestone}
        return d

    def test_single_milestone_renders_one_table_no_divider(self):
        by = {1: self._gh(1, "a"), 2: self._gh(2, "b")}
        md = render_canonical_table([1, 2], by)
        self.assertIn("| # | Title | Milestone | Assignee | Status |", md)
        self.assertNotIn("| | | | | |", md)  # no divider when one group

    def test_active_milestone_first_with_divider(self):
        by = {
            10: self._gh(10, "near", milestone="v0.4.0 — MVP"),
            20: self._gh(20, "far", milestone="v2.0.0 — Post-Launch"),
            30: self._gh(30, "none"),
        }
        md = render_canonical_table([10, 20, 30], by, milestone_alignment="v2.0.0")
        # Active milestone (v2.0.0 → #20) precedes v0.4.0 (#10) precedes none (#30).
        self.assertLess(md.index("#20"), md.index("#10"))
        self.assertLess(md.index("#10"), md.index("#30"))
        # Divider rows separate the three groups (2 dividers).
        self.assertEqual(md.count("| | | | | |"), 2)
        self.assertIn("| #20 | far | v2.0.0 |", md)

    def test_strip_and_insert_round_trip(self):
        by = {1: self._gh(1, "a")}
        table = render_canonical_table([1], by)
        body = insert_canonical_block("## Notes\n\nkeep\n", table)
        self.assertTrue(body.startswith("## Issues (canonical)"))
        self.assertIn("## Notes\n\nkeep", body)
        # Stripping removes the canonical block, leaving the narrative.
        stripped = strip_canonical_block(body)
        self.assertNotIn(CANONICAL_MARKER, stripped)
        self.assertIn("## Notes", stripped)

    def test_insert_replace_swaps_existing_block(self):
        by1 = {1: self._gh(1, "a")}
        body = insert_canonical_block("## Notes\n", render_canonical_table([1], by1))
        by2 = {2: self._gh(2, "b")}
        body2 = insert_canonical_block(body, render_canonical_table([2], by2),
                                       replace=True)
        # Old table gone, new table present, narrative preserved, exactly one block.
        self.assertNotIn("#1", body2)
        self.assertIn("#2", body2)
        self.assertEqual(body2.count(CANONICAL_MARKER), 1)
        self.assertIn("## Notes", body2)


class AppendRowsTest(unittest.TestCase):
    def test_inserts_after_last_row_before_narrative(self):
        body = _canonical_body(["| #678 | a | — | 🔲 Open |"])
        table = find_canonical_status_tables(body)[0]
        new = append_rows(body, table, ["| #999 | b | — | 🔲 Open |"])
        lines = new.split("\n")
        # New row sits directly after the existing data row...
        self.assertEqual(lines[7], "| #999 | b | — | 🔲 Open |")
        # ...and the narrative section survives below it.
        self.assertIn("## Notes", new)
        self.assertLess(new.index("#999"), new.index("## Notes"))

    def test_no_rows_is_noop(self):
        body = _canonical_body(["| #678 | a | — | 🔲 Open |"])
        table = find_canonical_status_tables(body)[0]
        self.assertEqual(append_rows(body, table, []), body)


class SyncMissingRowsTest(unittest.TestCase):
    def test_appends_missing_in_frontmatter_order(self):
        body = _canonical_body([
            "| #678 | first | — | 🔲 Open |",
            "| #925 | second | — | ✅ Shipped |",
        ])
        # Frontmatter lists three more than the table, deliberately out of
        # numeric order to prove frontmatter order (not sort) is honored.
        frontmatter_nums = [678, 925, 5195, 487, 2196]
        issues_by_num = {
            5195: {"number": 5195, "title": "newer", "state": "OPEN",
                   "assignees": [{"login": "bob"}]},
            487: {"number": 487, "title": "older", "state": "CLOSED", "assignees": []},
            2196: {"number": 2196, "title": "mid", "state": "OPEN", "assignees": []},
        }
        new, added = sync_missing_rows(body, frontmatter_nums, issues_by_num)
        self.assertEqual(added, 3)
        table = find_canonical_status_tables(new)[0]
        nums = [int(ISSUE_NUM_RE.search(r["cells"][0]).group(1)) for r in table["rows"]]
        self.assertEqual(nums, [678, 925, 5195, 487, 2196])
        self.assertIn("| #5195 | newer | @bob | 🔲 Open |", new)
        self.assertIn("| #487 | older | — | ✅ Shipped |", new)

    def test_slots_low_rank_row_above_existing(self):
        # The #79 case: frontmatter lists #487 first, but it's missing from a
        # table whose existing rows start at #678. Option A slots #487 to the
        # top instead of tacking it onto the end.
        body = _canonical_body([
            "| #678 | first | — | 🔲 Open |",
            "| #2528 | last | — | ✅ Shipped |",
        ])
        frontmatter_nums = [487, 678, 1556, 2528, 5195]
        issues_by_num = {
            487: {"number": 487, "title": "earliest", "state": "OPEN", "assignees": []},
            1556: {"number": 1556, "title": "middle", "state": "OPEN", "assignees": []},
            5195: {"number": 5195, "title": "newest", "state": "OPEN", "assignees": []},
        }
        new, added = sync_missing_rows(body, frontmatter_nums, issues_by_num)
        self.assertEqual(added, 3)
        table = find_canonical_status_tables(new)[0]
        nums = [int(ISSUE_NUM_RE.search(r["cells"][0]).group(1)) for r in table["rows"]]
        # Full table order now mirrors frontmatter: #487 at top, #1556 between
        # #678 and #2528, #5195 at the end.
        self.assertEqual(nums, frontmatter_nums)
        # Existing rows are re-emitted verbatim (minimal diff).
        self.assertIn("| #678 | first | — | 🔲 Open |", new)
        self.assertIn("| #2528 | last | — | ✅ Shipped |", new)

    def test_unranked_existing_row_imposes_no_constraint(self):
        # A row whose issue isn't in frontmatter (manual addition) shouldn't
        # block a missing row from slotting past it.
        body = _canonical_body([
            "| #9001 | manual | — | 🔲 Open |",
            "| #678 | tracked | — | 🔲 Open |",
        ])
        new, added = sync_missing_rows(
            body, [487, 678],
            {487: {"number": 487, "title": "early", "state": "OPEN", "assignees": []}},
        )
        self.assertEqual(added, 1)
        table = find_canonical_status_tables(new)[0]
        nums = [int(ISSUE_NUM_RE.search(r["cells"][0]).group(1)) for r in table["rows"]]
        # #487 slots immediately before #678 (its frontmatter successor),
        # leaving the unranked #9001 put.
        self.assertEqual(nums, [9001, 487, 678])

    def test_no_drift_is_noop(self):
        body = _canonical_body(["| #678 | first | — | 🔲 Open |"])
        new, added = sync_missing_rows(body, [678], {678: {"number": 678}})
        self.assertEqual(added, 0)
        self.assertEqual(new, body)

    def test_missing_issue_without_fetched_data_still_appends(self):
        body = _canonical_body(["| #678 | first | — | 🔲 Open |"])
        new, added = sync_missing_rows(body, [678, 999], {})
        self.assertEqual(added, 1)
        self.assertIn("#999", new)


if __name__ == "__main__":
    unittest.main()
