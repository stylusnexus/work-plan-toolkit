"""push-track (#306): promote a private track to the shared tier + push.
Real temp files for the move; git-worktree helpers + config mocked (offline)."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import push_track
from lib.frontmatter import parse_file
from lib.write_guard import make_token


class PushTrackTest(unittest.TestCase):
    def _setup(self, d, tier="private", plan_branch="work-plan/plan"):
        root = Path(d)
        notes = root / "notes"; notes.mkdir()
        priv = notes / "my-feature.md"
        priv.write_text("---\ntrack: my-feature\n---\n# My Feature\n\nbody\n")
        shared = root / "repo" / ".work-plan"; shared.mkdir(parents=True)
        entry = {"github": "o/r", "local": str(root / "repo")}
        if plan_branch:
            entry["plan_branch"] = plan_branch
        cfg = {"notes_root": str(notes), "repos": {"demo": entry}}
        track = SimpleNamespace(
            name="my-feature", tier=tier, folder="demo", repo="o/r",
            path=priv, meta={"track": "my-feature"}, body="# My Feature\n\nbody\n",
        )
        return root, cfg, track, shared, priv

    def _drive(self, cfg, track, shared, args, vis="PRIVATE",
               commit_sha="abc123", push_rc=0):
        push_proc = SimpleNamespace(returncode=push_rc, stderr="")
        with mock.patch("commands.push_track.load_config", return_value=cfg), \
             mock.patch("commands.push_track.discover_tracks", return_value=[track]), \
             mock.patch("commands.push_track.find_track_by_name", return_value=track), \
             mock.patch("lib.write_guard.repo_visibility", return_value=vis), \
             mock.patch("commands.push_track.pw.shared_tier_dir", return_value=shared), \
             mock.patch("commands.push_track.pw.commit_shared_tier", return_value=commit_sha), \
             mock.patch("commands.push_track.pw.push_plan_branch", return_value=push_proc) as mpush:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = push_track.run(args)
        return rc, out.getvalue(), err.getvalue(), mpush

    def test_promotes_and_pushes_private_repo(self):
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d)
            rc, out, err, mpush = self._drive(cfg, track, shared, ["my-feature"])
            self.assertEqual(rc, 0)
            dest = shared / "my-feature.md"
            self.assertTrue(dest.is_file())             # written to shared tier
            self.assertFalse(priv.exists())             # private copy removed
            meta, _ = parse_file(dest)
            self.assertEqual(meta["track"], "my-feature")  # frontmatter preserved
            mpush.assert_called_once()                  # pushed

    def test_no_push_keeps_local(self):
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d)
            rc, out, err, mpush = self._drive(cfg, track, shared, ["my-feature", "--no-push"])
            self.assertEqual(rc, 0)
            self.assertTrue((shared / "my-feature.md").is_file())
            mpush.assert_not_called()
            self.assertIn("plan-branch push", out)

    def test_public_repo_no_token_returns_needs_confirm_no_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d)
            rc, out, err, mpush = self._drive(cfg, track, shared, ["my-feature"], vis="PUBLIC")
            self.assertEqual(rc, 0)
            data = json.loads(out)
            self.assertTrue(data["needs_confirm"])
            self.assertEqual(data["token"], make_token("o/r", "my-feature"))
            self.assertFalse((shared / "my-feature.md").exists())  # nothing moved
            self.assertTrue(priv.exists())                          # private intact
            mpush.assert_not_called()

    def test_public_repo_with_valid_token_proceeds(self):
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d)
            tok = make_token("o/r", "my-feature")
            rc, out, err, mpush = self._drive(
                cfg, track, shared, ["my-feature", f"--confirm={tok}"], vis="PUBLIC")
            self.assertEqual(rc, 0)
            self.assertTrue((shared / "my-feature.md").is_file())
            mpush.assert_called_once()

    def test_public_no_push_skips_gate(self):
        # --no-push keeps it local, so no exposure gate even on a public repo.
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d)
            rc, out, err, mpush = self._drive(
                cfg, track, shared, ["my-feature", "--no-push"], vis="PUBLIC")
            self.assertEqual(rc, 0)
            self.assertTrue((shared / "my-feature.md").is_file())
            mpush.assert_not_called()

    def test_already_shared_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d, tier="shared")
            rc, out, err, mpush = self._drive(cfg, track, shared, ["my-feature"])
            self.assertEqual(rc, 1)
            self.assertIn("already in the shared tier", err)

    def test_no_plan_branch_hints_init(self):
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d, plan_branch=None)
            rc, out, err, mpush = self._drive(cfg, track, shared, ["my-feature"])
            self.assertEqual(rc, 1)
            self.assertIn("plan-branch init", err)

    def test_dest_exists_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            _, cfg, track, shared, priv = self._setup(d)
            (shared / "my-feature.md").write_text("# already here\n")
            rc, out, err, mpush = self._drive(cfg, track, shared, ["my-feature"])
            self.assertEqual(rc, 1)
            self.assertIn("already exists", err)
            self.assertTrue(priv.exists())  # private not removed on abort


if __name__ == "__main__":
    unittest.main()
