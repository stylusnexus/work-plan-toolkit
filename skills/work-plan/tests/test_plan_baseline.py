"""plan-baseline (#286 slice 2): stamp the computed verdict to frontmatter as a
drift baseline. Real temp repo (real yq); config + git date mocked."""
import io
import json
import unittest
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_baseline
from lib import frontmatter
from lib.write_guard import make_token

REL = "docs/superpowers/plans/p.md"
# A plan whose one declared file exists → mechanical verdict "shipped".
BODY = "# Plan\n\n**Files:**\n- Create: `src/new.ts`\n- [ ] Step 1\n"


class PlanBaselineTest(unittest.TestCase):
    def _repo(self, d, with_file=True, doc_text=BODY):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / REL).write_text(doc_text)
        if with_file:
            (root / "src").mkdir()
            (root / "src/new.ts").write_text("export const x = 1")
        return root

    def _drive(self, root, args, slug=None, vis="PRIVATE"):
        cfg = {"notes_root": str(root), "repos": {}}
        with mock.patch("commands.plan_baseline.config_mod.load_config", return_value=cfg), \
             mock.patch("commands.plan_baseline.config_mod.resolve_local_path_for_folder",
                        return_value=root), \
             mock.patch("commands.plan_baseline.config_mod.resolve_github_for_folder",
                        return_value=slug), \
             mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("lib.write_guard.repo_visibility", return_value=vis):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = plan_baseline.run(args)
        return rc, out.getvalue(), err.getvalue()

    def test_stamps_computed_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)               # file present → shipped
            rc, out, err = self._drive(root, ["--repo=k", "--", REL])
            self.assertEqual(rc, 0)
            meta, body = frontmatter.parse_file(root / REL)
            self.assertEqual(meta["verdict_baseline"], "shipped")
            self.assertIn("shipped", out)

    def test_clear_removes_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, doc_text=f"---\nverdict_baseline: shipped\n---\n{BODY}")
            rc, out, err = self._drive(root, ["--repo=k", "--clear", "--", REL])
            self.assertEqual(rc, 0)
            meta, _ = frontmatter.parse_file(root / REL)
            self.assertNotIn("verdict_baseline", meta)

    def test_public_repo_no_token_returns_needs_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--", REL],
                                       slug="org/pub", vis="PUBLIC")
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertEqual(data["token"], make_token("org/pub", REL))
            meta, _ = frontmatter.parse_file(root / REL)
            self.assertNotIn("verdict_baseline", meta)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--", "../../etc/passwd"])
            self.assertEqual(rc, 1)
            self.assertIn("not a file inside", err)


if __name__ == "__main__":
    unittest.main()
