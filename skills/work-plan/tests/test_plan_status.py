"""Smoke + behavior test for the plan-status command (offline)."""
import io
import json
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

PLAN_BODY = (
    "# Idea Mode Implementation Plan\n\n"
    "**Files:**\n"
    "- Create: `src/new.ts`\n"
    "- Create: `src/missing.ts`\n"
    "- [ ] Step 1: do the thing\n"
    "- [ ] Step 2: do the other thing\n"
)


class PlanStatusRunTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / "docs/superpowers/plans/2026-03-16-idea-mode-ui.md").write_text(PLAN_BODY)
        (root / "src").mkdir()
        (root / "src/new.ts").write_text("export const x = 1")  # 1 of 2 created
        return root

    def test_json_report_classifies_partial(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run(["--json"])
            self.assertEqual(rc, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data["docs"]), 1)
            row = data["docs"][0]
            self.assertEqual(row["files_present"], 1)
            self.assertEqual(row["files_declared"], 2)
            self.assertEqual(row["verdict"], "partial")  # 50% -> partial

    def test_human_report_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run([])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("plan-status", out)
            self.assertIn("partial", out)


if __name__ == "__main__":
    unittest.main()
