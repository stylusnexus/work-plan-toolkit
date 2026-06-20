"""Pure archive helpers: destination path + shipped-row selection (offline)."""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import reconcile_actions as ra


class ArchiveDestTest(unittest.TestCase):
    def test_default_kind_is_abandoned(self):
        self.assertEqual(
            ra.archive_dest("docs/plans/x.md"),
            "docs/plans/archive/abandoned/x.md",
        )

    def test_shipped_kind(self):
        self.assertEqual(
            ra.archive_dest("docs/plans/x.md", kind="shipped"),
            "docs/plans/archive/shipped/x.md",
        )

    def test_nested_dir_preserved(self):
        self.assertEqual(
            ra.archive_dest("docs/superpowers/specs/y-design.md", kind="shipped"),
            "docs/superpowers/specs/archive/shipped/y-design.md",
        )


class ShippedRowsTest(unittest.TestCase):
    ROWS = [
        {"rel": "a.md", "verdict": "shipped", "lie_gap": False},
        {"rel": "b.md", "verdict": "shipped", "lie_gap": True},   # lie-gap
        {"rel": "c.md", "verdict": "partial", "lie_gap": False},
        {"rel": "d.md", "verdict": "dead", "lie_gap": False},
    ]

    def test_excludes_lie_gap_by_default(self):
        rels = [r["rel"] for r in ra.shipped_rows(self.ROWS)]
        self.assertEqual(rels, ["a.md"])

    def test_includes_lie_gap_when_opted_in(self):
        rels = [r["rel"] for r in ra.shipped_rows(self.ROWS, include_lie_gap=True)]
        self.assertEqual(rels, ["a.md", "b.md"])


if __name__ == "__main__":
    unittest.main()
