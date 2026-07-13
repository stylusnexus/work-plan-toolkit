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
from lib.doc_discovery import Doc
from lib.status_header import BEGIN

PLAN = (
    "# Idea Mode Implementation Plan\n\n"
    "**Files:**\n"
    "- Create: `src/new.ts`\n"
    "- Create: `src/missing.ts`\n"
    "- [ ] Step 1\n"
)

ROW = {
    "glyph": "✅",
    "verdict": "shipped",
    "files_present": 1,
    "files_declared": 1,
    "last_touched": "2026-07-12",
}


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

    def test_stamp_rechecks_symlink_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            plans = root / "docs/plans"
            plans.mkdir(parents=True)
            victim = Path(d) / "victim.md"
            victim.write_text("# outside\n")
            link = plans / "evil.md"
            link.symlink_to(victim)
            doc = Doc(path=link, rel="docs/plans/evil.md", kind="plan")

            buf = io.StringIO()
            with redirect_stdout(buf):
                plan_status._stamp_docs([doc], [ROW], repo_root=root, draft=False)

            self.assertEqual(victim.read_text(), "# outside\n")
            self.assertIn("refusing to stamp unsafe path", buf.getvalue())

    def test_stamp_cli_does_not_modify_outside_symlink_target(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "repo"
            plans = root / "docs/superpowers/plans"
            plans.mkdir(parents=True)
            victim = Path(d) / "victim.md"
            victim.write_text(PLAN)
            before = victim.read_bytes()
            (plans / "evil.md").symlink_to(victim)

            rc, out = self._run(root, ["--stamp"])

            self.assertEqual(rc, 0)
            self.assertEqual(victim.read_bytes(), before)
            self.assertNotIn(BEGIN, victim.read_text())
            self.assertIn("stamped 0 doc(s)", out)


if __name__ == "__main__":
    unittest.main()
