"""Tests for reconcile action selection + target/body construction + unsatisfied paths."""
import unittest
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.manifest import DeclaredPath, unsatisfied_paths
from lib.reconcile_actions import dead_rows, partial_rows, archive_dest, issue_for


def _row(rel, verdict, present=0, declared=0):
    return {"rel": rel, "verdict": verdict, "files_present": present,
            "files_declared": declared, "glyph": "?", "rationale": ""}


class SelectionTest(unittest.TestCase):
    def test_dead_and_partial_filters(self):
        rows = [_row("a.md", "dead"), _row("b.md", "partial", 3, 9),
                _row("c.md", "shipped", 9, 9)]
        self.assertEqual([r["rel"] for r in dead_rows(rows)], ["a.md"])
        self.assertEqual([r["rel"] for r in partial_rows(rows)], ["b.md"])


class ArchiveDestTest(unittest.TestCase):
    def test_dest_under_archive_abandoned(self):
        self.assertEqual(
            archive_dest("docs/superpowers/plans/2026-01-01-x.md"),
            "docs/superpowers/plans/archive/abandoned/2026-01-01-x.md")


class UnsatisfiedPathsTest(unittest.TestCase):
    def test_returns_only_missing(self):
        decls = [DeclaredPath("create", "src/here.ts"),
                 DeclaredPath("create", "src/gone.ts"),
                 DeclaredPath("modify", "src/old.ts")]
        missing = unsatisfied_paths(
            decls, Path("/repo"), date(2026, 3, 1),
            exists=lambda rel: rel == "src/here.ts",
            committed_since=lambda rel: False)
        self.assertEqual({d.path for d in missing}, {"src/gone.ts", "src/old.ts"})


class IssueForTest(unittest.TestCase):
    def test_title_and_body(self):
        class Doc:
            rel = "docs/superpowers/plans/2026-01-01-feature-x.md"
        row = _row(Doc.rel, "partial", 2, 5)
        missing = [DeclaredPath("create", "src/a.ts"), DeclaredPath("modify", "src/b.ts")]
        title, body = issue_for(Doc(), row, missing)
        self.assertIn("2026-01-01-feature-x", title)
        self.assertIn("2/5", body)
        self.assertIn("`src/a.ts`", body)
        self.assertIn("`src/b.ts`", body)


if __name__ == "__main__":
    unittest.main()
