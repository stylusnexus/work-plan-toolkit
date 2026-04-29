"""Tests for status_table parser/updater."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.status_table import find_status_table, update_row_status, ISSUE_NUM_RE

FIXTURES = Path(__file__).parent / "fixtures"


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


if __name__ == "__main__":
    unittest.main()
