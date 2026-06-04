"""--issues: previews under --draft; opens gh issues after confirm (offline)."""
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

# 1 of 2 files present -> partial.
PARTIAL_PLAN = "# Partial\n\n- Create: `src/here.ts`\n- Create: `src/gone.ts`\n"


class IssuesTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / "docs/superpowers/plans/2026-05-01-partial.md").write_text(PARTIAL_PLAN)
        (root / "src").mkdir()
        (root / "src/here.ts").write_text("x")   # gone.ts absent -> partial
        return root

    def _run(self, root, args, create_ret="https://github.com/o/r/issues/9"):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status._resolve_repo_root", return_value=root), \
             mock.patch("commands.plan_status._repo_slug", return_value="o/r"), \
             mock.patch("commands.plan_status.github_state.create_issue",
                        return_value=create_ret) as ci, \
             mock.patch("commands.plan_status.prompt_yes_no", return_value=True):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue(), ci

    def test_draft_previews_without_creating(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, ci = self._run(root, ["--issues", "--draft", "--repo=critforge"])
            self.assertEqual(rc, 0)
            self.assertIn("gone.ts", out)       # unsatisfied path shown in preview
            ci.assert_not_called()

    def test_apply_creates_issue_after_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, ci = self._run(root, ["--issues", "--repo=critforge"])
            self.assertEqual(rc, 0)
            ci.assert_called_once()
            title, body = ci.call_args[0][1], ci.call_args[0][2]
            self.assertIn("partial", body.lower())
            self.assertIn("src/gone.ts", body)


if __name__ == "__main__":
    unittest.main()
