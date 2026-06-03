"""--archive: previews under --draft; gated by confirmation otherwise (offline)."""
import io
import unittest
import sys
import tempfile
from datetime import datetime
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

DEAD_PLAN = "# Dead Plan\n\n- Create: `src/never.ts`\n"


class ArchiveTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        self.rel = "docs/superpowers/plans/2026-01-01-dead.md"
        (root / self.rel).write_text(DEAD_PLAN)
        return root

    def _run(self, root, args, mv_ok=True):
        # stale last-commit (well beyond DEAD_DAYS) so the absent-file plan is dead
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=datetime(2026, 1, 1)), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root), \
             mock.patch("commands.plan_status.git_state.git_mv",
                        return_value=mv_ok) as mv, \
             mock.patch("commands.plan_status.prompt_yes_no", return_value=True):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue(), mv

    def test_draft_previews_without_moving(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, mv = self._run(root, ["--archive", "--draft"])
            self.assertEqual(rc, 0)
            self.assertIn("archive", out.lower())
            mv.assert_not_called()

    def test_apply_moves_after_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, mv = self._run(root, ["--archive"])
            self.assertEqual(rc, 0)
            mv.assert_called_once()
            args = mv.call_args[0]
            self.assertEqual(args[0], self.rel)
            self.assertEqual(args[1],
                             "docs/superpowers/plans/archive/abandoned/2026-01-01-dead.md")


if __name__ == "__main__":
    unittest.main()
