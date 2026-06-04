"""Tests for LLM candidate selection + evidence gathering."""
import unittest
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.llm_evidence import select_candidates, gather_evidence, EXCERPT_CHARS


def _row(rel, verdict, present, declared):
    return {"rel": rel, "verdict": verdict, "files_present": present,
            "files_declared": declared, "glyph": "?", "rationale": ""}


class SelectCandidatesTest(unittest.TestCase):
    def test_picks_manifest_less(self):
        rows = [_row("a.md", "manifest-less", 0, 0)]
        self.assertEqual([r["rel"] for r in select_candidates(rows)], ["a.md"])

    def test_picks_ambiguous_low_completion(self):
        rows = [_row("b.md", "partial", 0, 38), _row("c.md", "partial", 1, 11)]
        picked = {r["rel"] for r in select_candidates(rows)}
        self.assertEqual(picked, {"b.md", "c.md"})

    def test_skips_confident_shipped_and_healthy_partial(self):
        rows = [_row("d.md", "shipped", 9, 9), _row("e.md", "partial", 8, 12)]
        self.assertEqual(select_candidates(rows), [])


class GatherEvidenceTest(unittest.TestCase):
    def test_builds_evidence_dict(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs").mkdir()
            doc_path = root / "docs/x-design.md"
            doc_path.write_text("# Design X\n\nLong prose. " + "z" * 5000)

            class Doc:
                path = doc_path
                rel = "docs/x-design.md"
                kind = "spec"

            fake_dt = datetime(2026, 4, 2, 10, 0, 0)
            with mock.patch("lib.llm_evidence.git_state.path_last_commit_date",
                            return_value=fake_dt):
                ev = gather_evidence(Doc(), root)
            self.assertEqual(ev["rel"], "docs/x-design.md")
            self.assertEqual(ev["kind"], "spec")
            self.assertEqual(ev["last_touched"], "2026-04-02")
            self.assertEqual(ev["title"], "Design X")
            self.assertLessEqual(len(ev["excerpt"]), EXCERPT_CHARS)

    def test_none_last_touched(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            doc_path = root / "y.md"
            doc_path.write_text("no heading\n")

            class Doc:
                path = doc_path
                rel = "y.md"
                kind = "adhoc"

            with mock.patch("lib.llm_evidence.git_state.path_last_commit_date",
                            return_value=None):
                ev = gather_evidence(Doc(), root)
            self.assertIsNone(ev["last_touched"])
            self.assertEqual(ev["title"], "(no title)")


if __name__ == "__main__":
    unittest.main()
