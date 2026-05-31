"""Tests for idempotent status-header stamping."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.status_header import BEGIN, END, render_block, stamp

ROW = {
    "glyph": "✅", "verdict": "shipped",
    "files_present": 9, "files_declared": 9,
    "last_touched": "2026-04-02",
}


class RenderBlockTest(unittest.TestCase):
    def test_block_is_delimited_and_evidence_only(self):
        block = render_block(ROW)
        self.assertTrue(block.startswith(BEGIN))
        self.assertTrue(block.rstrip().endswith(END))
        self.assertIn("shipped", block)
        self.assertIn("9/9 files", block)
        self.assertIn("2026-04-02", block)

    def test_none_last_touched_renders_unknown(self):
        row = dict(ROW, last_touched=None)
        self.assertIn("unknown", render_block(row))


class StampTest(unittest.TestCase):
    DOC = "# My Plan\n\nSome body text.\n"

    def test_inserts_after_h1(self):
        out = stamp(self.DOC, ROW)
        self.assertIn(BEGIN, out)
        self.assertLess(out.index(BEGIN), out.index("Some body text."))
        self.assertGreater(out.index(BEGIN), out.index("# My Plan"))

    def test_idempotent_same_evidence_zero_diff(self):
        once = stamp(self.DOC, ROW)
        twice = stamp(once, ROW)
        self.assertEqual(once, twice)

    def test_rewrites_only_block_on_evidence_change(self):
        once = stamp(self.DOC, ROW)
        changed = stamp(once, dict(ROW, files_present=5, verdict="partial"))
        self.assertNotEqual(once, changed)
        self.assertEqual(changed.count(BEGIN), 1)
        self.assertIn("partial", changed)
        self.assertNotIn("shipped", changed)

    def test_prepends_when_no_h1(self):
        out = stamp("no heading here\n", ROW)
        self.assertTrue(out.startswith(BEGIN))

    def test_duplicate_blocks_collapse_to_one_fresh(self):
        # Two stale blocks (e.g. from a bad merge) -> one fresh, no stale leftover.
        block = render_block(dict(ROW, verdict="partial", files_present=1))
        doc = f"# Plan\n\n{block}\n\nbody\n\n{block}\n"
        out = stamp(doc, ROW)
        self.assertEqual(out.count(BEGIN), 1)
        self.assertEqual(out.count(END), 1)
        self.assertIn("shipped", out)
        self.assertNotIn("partial", out)
        self.assertEqual(out, stamp(out, ROW))   # stable on re-run

    def test_dangling_begin_does_not_duplicate(self):
        # An orphan BEGIN (no END) must not cause a second block to be stacked.
        doc = f"# Plan\n\n{BEGIN}\n> **Status:** truncated\n\nbody\n"
        out = stamp(doc, ROW)
        self.assertEqual(out.count(BEGIN), 1)
        self.assertEqual(out.count(END), 1)
        self.assertEqual(out, stamp(out, ROW))   # idempotent afterward


if __name__ == "__main__":
    unittest.main()
