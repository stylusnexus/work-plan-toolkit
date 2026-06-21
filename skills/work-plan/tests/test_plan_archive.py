"""plan-archive: per-doc archive of a shipped plan. Offline — git_mv mocked,
repo resolution via Path.cwd patch (no config file)."""
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

from commands import plan_archive

SHIPPED_BODY = "# P\n\n**Files:**\n- Create: `src/new.ts`\n- [x] Step 1\n"
PARTIAL_BODY = "# P\n\n**Files:**\n- Create: `src/missing.ts`\n- [ ] Step 1\n"


def _repo(d, body, present=True):
    root = Path(d)
    (root / "docs/plans").mkdir(parents=True)
    (root / "docs/plans/p.md").write_text(body)
    if present:
        (root / "src").mkdir()
        (root / "src/new.ts").write_text("export const x = 1")
    return root


def _run(root, args):
    with mock.patch("commands.plan_archive.plan_status.git_state.path_last_commit_date",
                    return_value=None), \
         mock.patch("commands.plan_archive.plan_status._resolve_repo_root",
                    return_value=root):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan_archive.run(args)
    return rc, buf.getvalue()


class PlanArchiveTest(unittest.TestCase):
    def test_archives_shipped_with_yes_json(self):
        with tempfile.TemporaryDirectory() as d:
            root = _repo(d, SHIPPED_BODY)
            with mock.patch("commands.plan_archive.archive_lib.git_state.git_mv",
                            return_value=True) as mv:
                rc, out = _run(root, ["--repo=x", "--yes", "--json",
                                      "--", "docs/plans/p.md"])
            self.assertEqual(rc, 0)
            payload = json.loads(out)
            self.assertEqual(payload["outcome"], "archived")
            self.assertEqual(payload["dest"], "docs/plans/archive/shipped/p.md")
            mv.assert_called_once()

    def test_refuses_non_shipped(self):
        with tempfile.TemporaryDirectory() as d:
            root = _repo(d, PARTIAL_BODY, present=False)
            with mock.patch("commands.plan_archive.archive_lib.git_state.git_mv") as mv:
                rc, out = _run(root, ["--repo=x", "--yes", "--json",
                                      "--", "docs/plans/p.md"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out)["outcome"], "refused_not_shipped")
            mv.assert_not_called()

    def test_collision_skips(self):
        with tempfile.TemporaryDirectory() as d:
            root = _repo(d, SHIPPED_BODY)
            dest = root / "docs/plans/archive/shipped"
            dest.mkdir(parents=True)
            (dest / "p.md").write_text("# existing")
            with mock.patch("commands.plan_archive.archive_lib.git_state.git_mv") as mv:
                rc, out = _run(root, ["--repo=x", "--yes", "--json",
                                      "--", "docs/plans/p.md"])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out)["outcome"], "skipped_collision")
            mv.assert_not_called()

    def test_non_tty_without_yes_declines(self):
        with tempfile.TemporaryDirectory() as d:
            root = _repo(d, SHIPPED_BODY)
            with mock.patch("commands.plan_archive.archive_lib.git_state.git_mv") as mv:
                rc, out = _run(root, ["--repo=x", "--", "docs/plans/p.md"])
            self.assertEqual(rc, 0)
            mv.assert_not_called()   # prompt defaults to "no" on non-TTY

    def test_missing_rel_errors(self):
        with tempfile.TemporaryDirectory() as d:
            root = _repo(d, SHIPPED_BODY)
            rc, _ = _run(root, ["--repo=x", "--yes", "--json",
                                "--", "docs/plans/nope.md"])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
