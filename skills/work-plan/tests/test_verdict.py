"""Tests for pure verdict classification."""
import unittest
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.manifest import ManifestScore
from lib.verdict import classify, Verdict

TODAY = date(2026, 5, 30)


def _score(sat, tot):
    return ManifestScore(total=tot, satisfied=sat,
                         by_kind={"create": (sat, tot), "modify": (0, 0), "test": (0, 0)})


class ClassifyTest(unittest.TestCase):
    def test_shipped_when_all_files_present(self):
        v = classify(_score(9, 9), checkbox_done=0, checkbox_total=24,
                     last_touched=date(2026, 4, 1), today=TODAY)
        self.assertEqual(v.label, "shipped")
        self.assertEqual(v.glyph, "✅")
        self.assertIn("boxes stale", v.rationale)  # 0/24 boxes -> stale note

    def test_shipped_without_stale_note_when_boxes_checked(self):
        v = classify(_score(9, 9), checkbox_done=20, checkbox_total=24,
                     last_touched=date(2026, 4, 1), today=TODAY)
        self.assertEqual(v.label, "shipped")
        self.assertNotIn("boxes stale", v.rationale)

    def test_partial_when_some_files(self):
        v = classify(_score(3, 9), checkbox_done=0, checkbox_total=9,
                     last_touched=date(2026, 5, 1), today=TODAY)
        self.assertEqual(v.label, "partial")
        self.assertEqual(v.glyph, "\U0001f7e1")

    def test_dead_when_no_files_and_stale(self):
        v = classify(_score(0, 9), checkbox_done=0, checkbox_total=9,
                     last_touched=date(2026, 1, 1), today=TODAY, dead_days=60)
        self.assertEqual(v.label, "dead")
        self.assertEqual(v.glyph, "\U0001f480")

    def test_early_not_dead_when_recent(self):
        v = classify(_score(0, 9), checkbox_done=0, checkbox_total=9,
                     last_touched=date(2026, 5, 20), today=TODAY, dead_days=60)
        self.assertEqual(v.label, "partial")

    def test_manifest_less_routes_to_llm(self):
        v = classify(_score(0, 0), checkbox_done=0, checkbox_total=0,
                     last_touched=None, today=TODAY)
        self.assertEqual(v.label, "manifest-less")
        self.assertEqual(v.glyph, "\U0001f47b")


if __name__ == "__main__":
    unittest.main()
