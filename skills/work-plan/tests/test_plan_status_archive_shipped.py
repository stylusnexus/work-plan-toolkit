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


if __name__ == "__main__":
    unittest.main()
