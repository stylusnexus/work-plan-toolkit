"""plan-status --include-archived emits archived docs (tagged) in --json and
keeps them out of the live human render; --archive-shipped batch-archives."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

SHIPPED = "# P\n\n**Files:**\n- Create: `src/a.ts`\n- [x] Step 1\n"


def _repo(d):
    root = Path(d)
    (root / "docs/plans").mkdir(parents=True)
    (root / "docs/plans/live.md").write_text(SHIPPED)
    (root / "src").mkdir()
    (root / "src/a.ts").write_text("export const a = 1")
    (root / "docs/plans/archive/shipped").mkdir(parents=True)
    (root / "docs/plans/archive/shipped/old.md").write_text(SHIPPED)
    return root


def _run(root, args):
    with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                    return_value=None), \
         mock.patch("commands.plan_status.Path.cwd", return_value=root):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan_status.run(args)
    return rc, buf.getvalue()


class IncludeArchivedTest(unittest.TestCase):
    def test_json_without_flag_omits_archived(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = _run(_repo(d), ["--json"])
            rels = [r["rel"] for r in json.loads(out)["docs"]]
            self.assertEqual(rels, ["docs/plans/live.md"])

    def test_json_with_flag_includes_tagged_archived(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = _run(_repo(d), ["--json", "--include-archived"])
            by_rel = {r["rel"]: r for r in json.loads(out)["docs"]}
            self.assertIn("docs/plans/archive/shipped/old.md", by_rel)
            arch = by_rel["docs/plans/archive/shipped/old.md"]
            self.assertTrue(arch["archived"])
            self.assertEqual(arch["archive_kind"], "shipped")
            self.assertFalse(by_rel["docs/plans/live.md"]["archived"])


LIEGAP = "# L\n\n**Files:**\n- Create: `src/b.ts`\n- [ ] Step 1\n- [ ] Step 2\n"


def _repo_batch(d):
    root = Path(d)
    (root / "docs/plans").mkdir(parents=True)
    (root / "docs/plans/clean.md").write_text(SHIPPED)
    (root / "docs/plans/liegap.md").write_text(LIEGAP)
    (root / "src").mkdir()
    (root / "src/a.ts").write_text("export const a = 1")  # clean shipped
    (root / "src/b.ts").write_text("export const b = 1")  # liegap shipped (0/2 boxes)
    return root


class ArchiveShippedBatchTest(unittest.TestCase):
    def test_batch_json_archives_clean_excludes_liegap(self):
        with tempfile.TemporaryDirectory() as d:
            root = _repo_batch(d)
            with mock.patch("commands.plan_status.archive_lib.git_state.git_mv",
                            return_value=True):
                rc, out = _run(root, ["--archive-shipped", "--yes", "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(out)
            self.assertEqual(payload["action"], "archive_shipped")
            self.assertEqual([a["rel"] for a in payload["archived"]],
                             ["docs/plans/clean.md"])
            self.assertEqual([x["rel"] for x in payload["lie_gap_excluded"]],
                             ["docs/plans/liegap.md"])

    def test_batch_include_lie_gap_archives_both(self):
        with tempfile.TemporaryDirectory() as d:
            root = _repo_batch(d)
            with mock.patch("commands.plan_status.archive_lib.git_state.git_mv",
                            return_value=True):
                rc, out = _run(root, ["--archive-shipped", "--include-lie-gap",
                                      "--yes", "--json"])
            archived = sorted(a["rel"] for a in json.loads(out)["archived"])
            self.assertEqual(archived,
                             ["docs/plans/clean.md", "docs/plans/liegap.md"])

    def test_footer_hint_lists_shipped_count(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = _run(_repo(d), [])   # human render
            self.assertIn("1 shipped", out)
            self.assertIn("plan-archive", out)


if __name__ == "__main__":
    unittest.main()
