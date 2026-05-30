"""Stamp / draft behaviour for plan-status (offline)."""
import io
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status
from lib.status_header import BEGIN

PLAN = (
    "# Idea Mode Implementation Plan\n\n"
    "**Files:**\n"
    "- Create: `src/new.ts`\n"
    "- Create: `src/missing.ts`\n"
    "- [ ] Step 1\n"
)


class StampBehaviourTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        self.plan_path = root / "docs/superpowers/plans/2026-03-16-idea-mode-ui.md"
        self.plan_path.write_text(PLAN)
        (root / "src").mkdir()
        (root / "src/new.ts").write_text("x")
        return root

    def _run(self, root, args):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue()

    def test_draft_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out = self._run(root, ["--stamp", "--draft"])
            self.assertEqual(rc, 0)
            self.assertIn("would stamp", out)
            self.assertNotIn(BEGIN, self.plan_path.read_text())

    def test_stamp_writes_block(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out = self._run(root, ["--stamp"])
            self.assertEqual(rc, 0)
            self.assertIn("stamped", out)
            self.assertIn(BEGIN, self.plan_path.read_text())

    def test_stamp_is_idempotent_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            self._run(root, ["--stamp"])
            first = self.plan_path.read_text()
            self._run(root, ["--stamp"])
            self.assertEqual(first, self.plan_path.read_text())


if __name__ == "__main__":
    unittest.main()
