"""plan-ack (#286 slice 1): durable, frontmatter-only acknowledgment. Real temp
repo so the write round-trips through real yq; config + visibility are mocked."""
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

from commands import plan_ack
from lib import frontmatter
from lib.write_guard import make_token

REL = "docs/superpowers/plans/p.md"
BODY = "# Plan\n\nbody the writer must never touch\n"


class PlanAckTest(unittest.TestCase):
    def _repo(self, d, doc_text=BODY):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / REL).write_text(doc_text)
        return root

    def _drive(self, root, args, slug=None, vis="PRIVATE"):
        cfg = {"notes_root": str(root), "repos": {}}
        with mock.patch("commands.plan_ack.config_mod.load_config", return_value=cfg), \
             mock.patch("commands.plan_ack.config_mod.resolve_local_path_for_folder",
                        return_value=root), \
             mock.patch("commands.plan_ack.config_mod.resolve_github_for_folder",
                        return_value=slug), \
             mock.patch("lib.write_guard.repo_visibility", return_value=vis):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = plan_ack.run(args)
        return rc, out.getvalue(), err.getvalue()

    def test_writes_acknowledged_preserving_body(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--", REL])
            self.assertEqual(rc, 0)
            meta, body = frontmatter.parse_file(root / REL)
            self.assertIs(meta["acknowledged"], True)
            self.assertEqual(body, BODY)
            self.assertIn("frontmatter only", out)

    def test_clear_removes_acknowledged(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, f"---\nacknowledged: true\n---\n{BODY}")
            rc, out, err = self._drive(root, ["--repo=k", "--clear", "--", REL])
            self.assertEqual(rc, 0)
            meta, body = frontmatter.parse_file(root / REL)
            self.assertNotIn("acknowledged", meta)
            self.assertEqual(body, BODY)

    def test_clear_when_absent_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--clear", "--", REL])
            self.assertEqual(rc, 0)
            self.assertIn("nothing to clear", out)

    def test_public_repo_no_token_returns_needs_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--", REL],
                                       slug="org/pub", vis="PUBLIC")
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertTrue(data["needs_confirm"])
            self.assertEqual(data["token"], make_token("org/pub", REL))
            meta, _ = frontmatter.parse_file(root / REL)
            self.assertNotIn("acknowledged", meta)   # no write happened

    def test_public_repo_with_valid_token_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            token = make_token("org/pub", REL)
            rc, out, err = self._drive(root, ["--repo=k", f"--confirm={token}", "--", REL],
                                       slug="org/pub", vis="PUBLIC")
            self.assertEqual(rc, 0)
            meta, _ = frontmatter.parse_file(root / REL)
            self.assertIs(meta["acknowledged"], True)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--", "../../etc/passwd"])
            self.assertEqual(rc, 1)
            self.assertIn("not a file inside", err)

    def test_missing_repo_flag_rejected(self):
        rc, out, err = self._drive(Path("/tmp"), ["--", REL])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
