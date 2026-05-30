"""Tests for doc discovery + kind classification."""
import unittest
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.doc_discovery import classify_kind, discover_docs, Doc


class ClassifyKindTest(unittest.TestCase):
    def test_superpowers_plan(self):
        self.assertEqual(classify_kind("docs/superpowers/plans/2026-03-16-x.md"), "plan")

    def test_superpowers_spec(self):
        self.assertEqual(classify_kind("docs/superpowers/specs/2026-03-16-x-design.md"), "spec")

    def test_design_suffix_is_spec(self):
        self.assertEqual(classify_kind("docs/plans/2026-02-17-foo-design.md"), "spec")

    def test_plain_docs_plan(self):
        self.assertEqual(classify_kind("docs/plans/2026-02-17-foo.md"), "plan")

    def test_other_is_adhoc(self):
        self.assertEqual(classify_kind("notes/random.md"), "adhoc")


class DiscoverDocsTest(unittest.TestCase):
    def test_finds_default_globs_and_dedupes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs/superpowers/plans").mkdir(parents=True)
            (root / "docs/plans").mkdir(parents=True)
            (root / "docs/superpowers/plans/2026-03-16-a.md").write_text("x")
            (root / "docs/plans/2026-02-17-b-design.md").write_text("x")
            (root / "docs/plans/README.txt").write_text("ignore")  # not .md
            docs = discover_docs(root)
            rels = sorted(x.rel for x in docs)
            self.assertEqual(rels, [
                "docs/plans/2026-02-17-b-design.md",
                "docs/superpowers/plans/2026-03-16-a.md",
            ])
            kinds = {x.rel: x.kind for x in docs}
            self.assertEqual(kinds["docs/superpowers/plans/2026-03-16-a.md"], "plan")
            self.assertEqual(kinds["docs/plans/2026-02-17-b-design.md"], "spec")


if __name__ == "__main__":
    unittest.main()
