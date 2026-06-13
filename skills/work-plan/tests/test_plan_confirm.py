"""plan-confirm (#286): frontmatter-only verdict_override writes, with the
public-repo confirm-token gate. Uses a real temp repo so the frontmatter write
round-trips through real yq; config + visibility are mocked (offline)."""
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

from commands import plan_confirm
from lib import frontmatter
from lib.write_guard import make_token

REL = "docs/superpowers/plans/p.md"
BODY = "# Idea Mode UI\n\nbody text the writer must never touch\n"


class PlanConfirmTest(unittest.TestCase):
    def _repo(self, d, doc_text=BODY):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / REL).write_text(doc_text)
        return root

    def _drive(self, root, args, slug=None, vis="PRIVATE"):
        cfg = {"notes_root": str(root), "repos": {}}
        with mock.patch("commands.plan_confirm.config_mod.load_config", return_value=cfg), \
             mock.patch("commands.plan_confirm.config_mod.resolve_local_path_for_folder",
                        return_value=root), \
             mock.patch("commands.plan_confirm.config_mod.resolve_github_for_folder",
                        return_value=slug), \
             mock.patch("lib.write_guard.repo_visibility", return_value=vis):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = plan_confirm.run(args)
        # stdout carries the machine surfaces (needs_confirm JSON, success line);
        # stderr carries usage/validation errors. Tests assert on either.
        return rc, out.getvalue(), err.getvalue()

    def test_writes_override_to_frontmatter_preserving_body(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--verdict=shipped", "--", REL])
            self.assertEqual(rc, 0)
            meta, body = frontmatter.parse_file(root / REL)
            self.assertEqual(meta["verdict_override"], "shipped")
            self.assertEqual(body, BODY)        # body byte-preserved
            self.assertIn("frontmatter only", out)

    def test_clear_removes_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d, f"---\nverdict_override: shipped\n---\n{BODY}")
            rc, out, err = self._drive(root, ["--repo=k", "--clear", "--", REL])
            self.assertEqual(rc, 0)
            meta, body = frontmatter.parse_file(root / REL)
            self.assertNotIn("verdict_override", meta)
            self.assertEqual(body, BODY)

    def test_public_repo_no_token_returns_needs_confirm(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--verdict=shipped", "--", REL],
                                  slug="org/pub", vis="PUBLIC")
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertTrue(data["needs_confirm"])
            self.assertEqual(data["token"], make_token("org/pub", REL))
            # NO write happened.
            meta, _ = frontmatter.parse_file(root / REL)
            self.assertNotIn("verdict_override", meta)

    def test_public_repo_with_valid_token_writes(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            token = make_token("org/pub", REL)
            rc, out, err = self._drive(
                root, ["--repo=k", "--verdict=shipped", f"--confirm={token}", "--", REL],
                slug="org/pub", vis="PUBLIC")
            self.assertEqual(rc, 0)
            meta, _ = frontmatter.parse_file(root / REL)
            self.assertEqual(meta["verdict_override"], "shipped")

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--verdict=shipped", "--",
                                         "../../etc/passwd"])
            self.assertEqual(rc, 1)
            self.assertIn("not a file inside", err)

    def test_invalid_verdict_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            rc, out, err = self._drive(root, ["--repo=k", "--verdict=done", "--", REL])
            self.assertEqual(rc, 2)

    def test_missing_repo_flag_rejected(self):
        rc, out, err = self._drive(Path("/tmp"), ["--verdict=shipped", "--", REL])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
