"""discover_docs include_archived pass: archived docs are excluded by default
and included + tagged when opted in (offline, filesystem only)."""
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import doc_discovery


def _repo(d):
    root = Path(d)
    (root / "docs/plans").mkdir(parents=True)
    (root / "docs/plans/live.md").write_text("# live")
    (root / "docs/plans/archive/shipped").mkdir(parents=True)
    (root / "docs/plans/archive/shipped/done.md").write_text("# done")
    (root / "docs/plans/archive/abandoned").mkdir(parents=True)
    (root / "docs/plans/archive/abandoned/dead.md").write_text("# dead")
    return root


class DiscoverArchivedTest(unittest.TestCase):
    def test_default_excludes_archived(self):
        with tempfile.TemporaryDirectory() as d:
            docs = doc_discovery.discover_docs(_repo(d))
            rels = sorted(x.rel for x in docs)
            self.assertEqual(rels, ["docs/plans/live.md"])

    def test_include_archived_tags_shipped_and_abandoned(self):
        with tempfile.TemporaryDirectory() as d:
            docs = doc_discovery.discover_docs(_repo(d), include_archived=True)
            by_rel = {x.rel: x for x in docs}
            self.assertIn("docs/plans/archive/shipped/done.md", by_rel)
            self.assertIn("docs/plans/archive/abandoned/dead.md", by_rel)
            self.assertTrue(by_rel["docs/plans/archive/shipped/done.md"].archived)
            self.assertEqual(
                by_rel["docs/plans/archive/shipped/done.md"].archive_kind, "shipped")
            self.assertEqual(
                by_rel["docs/plans/archive/abandoned/dead.md"].archive_kind, "abandoned")
            self.assertFalse(by_rel["docs/plans/live.md"].archived)


if __name__ == "__main__":
    unittest.main()
