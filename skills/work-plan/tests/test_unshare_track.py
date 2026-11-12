"""unshare-track (#349): demote shared tracks back to the private tier.
Real temp files for the move; config + discovery mocked; one real-git test
proves the removal commit lands (commit_shared_tier on a deleted file)."""
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import unshare_track
from lib import plan_worktree as pw
from lib.frontmatter import parse_file


def _track(shared, name, tier="shared", folder="demo", sub=None):
    base = shared / sub if sub else shared
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{name}.md"
    p.write_text(f"---\n# keep me\ntrack: {name}\n---\n# {name}\n\nbody\n")
    return SimpleNamespace(name=name, tier=tier, folder=folder, repo="o/r",
                           path=p, meta={"track": name}, body=f"# {name}\n\nbody\n")


class UnshareTrackTest(unittest.TestCase):
    def _setup(self, d, plan_branch="work-plan/plan"):
        root = Path(d)
        notes = root / "notes"; notes.mkdir()
        shared = root / "repo" / ".work-plan"; shared.mkdir(parents=True)
        entry = {"github": "o/r", "local": str(root / "repo")}
        if plan_branch:
            entry["plan_branch"] = plan_branch
        cfg = {"notes_root": str(notes), "repos": {"demo": entry}}
        return notes, shared, cfg

    def _drive(self, cfg, tracks, shared, args, commit_sha="abc123", push_rc=0):
        proc = SimpleNamespace(returncode=push_rc, stderr="")
        with mock.patch("commands.unshare_track.load_config", return_value=cfg), \
             mock.patch("commands.unshare_track.discover_tracks", return_value=tracks), \
             mock.patch("commands.unshare_track.find_track_by_name",
                        side_effect=lambda n, ts, repo=None: next(
                            (t for t in ts if t.name == n), None)), \
             mock.patch("commands.unshare_track.pw.shared_tier_dir", return_value=shared), \
             mock.patch("commands.unshare_track.pw.commit_shared_tier",
                        return_value=commit_sha) as mcommit, \
             mock.patch("commands.unshare_track.pw.push_plan_branch",
                        return_value=proc) as mpush:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = unshare_track.run(args)
        return rc, out.getvalue(), err.getvalue(), mcommit, mpush

    def test_demotes_single_track_and_pushes(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            t = _track(shared, "feat")
            rc, out, err, mcommit, mpush = self._drive(cfg, [t], shared, ["feat"])
            self.assertEqual(rc, 0)
            dest = notes / "demo" / "feat.md"
            self.assertTrue(dest.is_file())
            self.assertFalse((shared / "feat.md").exists())
            meta, body = parse_file(dest)
            self.assertEqual(meta["track"], "feat")     # frontmatter preserved
            self.assertIn("body", body)                  # content preserved
            self.assertIn("# keep me", dest.read_text())  # YAML comment kept
            self.assertEqual(mcommit.call_args[0][2], [".work-plan/feat.md"])
            mpush.assert_called_once()

    def test_no_push_keeps_local(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            t = _track(shared, "feat")
            rc, out, err, mcommit, mpush = self._drive(cfg, [t], shared, ["feat", "--no-push"])
            self.assertEqual(rc, 0)
            self.assertTrue((notes / "demo" / "feat.md").is_file())
            mpush.assert_not_called()
            self.assertIn("plan-branch push", out)

    def test_already_private_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            t = _track(shared, "feat", tier="private")
            rc, out, err, mcommit, mpush = self._drive(cfg, [t], shared, ["feat"])
            self.assertEqual(rc, 1)
            self.assertIn("already private", err)
            mcommit.assert_not_called()
            mpush.assert_not_called()

    def test_private_name_collision_aborts_without_loss(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            (notes / "demo").mkdir()
            (notes / "demo" / "feat.md").write_text("# existing private\n")
            t = _track(shared, "feat")
            rc, out, err, mcommit, mpush = self._drive(cfg, [t], shared, ["feat"])
            self.assertEqual(rc, 1)
            self.assertIn("already exists", err)
            self.assertTrue((shared / "feat.md").exists())   # shared untouched
            self.assertEqual((notes / "demo" / "feat.md").read_text(),
                             "# existing private\n")         # private untouched
            mpush.assert_not_called()

    def test_all_demotes_every_shared_track_in_one_commit(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            a, b = _track(shared, "a"), _track(shared, "b")
            other = _track(shared, "c", folder="other")   # different repo: untouched
            rc, out, err, mcommit, mpush = self._drive(
                cfg, [a, b, other], shared, ["--all", "--repo=demo"])
            self.assertEqual(rc, 0)
            self.assertTrue((notes / "demo" / "a.md").is_file())
            self.assertTrue((notes / "demo" / "b.md").is_file())
            self.assertTrue((shared / "c.md").exists())
            mcommit.assert_called_once()
            self.assertEqual(sorted(mcommit.call_args[0][2]),
                             [".work-plan/a.md", ".work-plan/b.md"])
            mpush.assert_called_once()

    def test_all_rejects_track_name_or_extra_flag(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            t = _track(shared, "feat")
            for extra in (["feat"], ["--dry-run"]):
                rc, out, err, mcommit, mpush = self._drive(
                    cfg, [t], shared, ["--all", "--repo=demo", *extra])
                self.assertEqual(rc, 2)
                mcommit.assert_not_called()
            self.assertTrue((shared / "feat.md").exists())

    def test_subfolder_track_commits_real_path(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            t = _track(shared, "foo", sub="team")
            rc, out, err, mcommit, mpush = self._drive(cfg, [t], shared, ["foo"])
            self.assertEqual(rc, 0)
            self.assertEqual(mcommit.call_args[0][2], [".work-plan/team/foo.md"])

    def test_failed_removal_commit_errors_and_skips_push(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            t = _track(shared, "feat")
            rc, out, err, mcommit, mpush = self._drive(
                cfg, [t], shared, ["feat"], commit_sha=None)
            self.assertEqual(rc, 1)
            self.assertIn("did not land", err)
            mpush.assert_not_called()
            self.assertNotIn("Pushed", out)

    def test_all_requires_repo(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            rc, out, err, mcommit, mpush = self._drive(cfg, [], shared, ["--all"])
            self.assertEqual(rc, 2)

    def test_all_partial_failure_reports_and_still_commits_moved(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            (notes / "demo").mkdir()
            (notes / "demo" / "b.md").write_text("# existing\n")
            a, b = _track(shared, "a"), _track(shared, "b")
            rc, out, err, mcommit, mpush = self._drive(
                cfg, [a, b], shared, ["--all", "--repo=demo"])
            self.assertEqual(rc, 1)
            self.assertEqual(mcommit.call_args[0][2], [".work-plan/a.md"])
            self.assertTrue((shared / "b.md").exists())

    def test_no_plan_branch_errors(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d, plan_branch=None)
            t = _track(shared, "feat")
            rc, out, err, mcommit, mpush = self._drive(cfg, [t], shared, ["feat"])
            self.assertEqual(rc, 1)
            self.assertIn("no shared plan branch", err)
            self.assertTrue((shared / "feat.md").exists())

    def test_push_failure_keeps_local_state_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            notes, shared, cfg = self._setup(d)
            t = _track(shared, "feat")
            rc, out, err, mcommit, mpush = self._drive(cfg, [t], shared, ["feat"], push_rc=1)
            self.assertEqual(rc, 1)
            self.assertIn("push failed", err)
            self.assertTrue((notes / "demo" / "feat.md").is_file())


class RemovalCommitRealGitTest(unittest.TestCase):
    """commit_shared_tier must stage + commit a DELETED file (real git)."""

    def test_removal_is_committed(self):
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d)
            def git(*a):
                return subprocess.run(["git", "-C", d, "-c", "user.email=t@t",
                                       "-c", "user.name=t", *a],
                                      capture_output=True, text=True, check=True)
            git("init", "-q")
            # commit_shared_tier commits without -c identity flags, so give the
            # repo one (CI runners have no global git identity).
            git("config", "user.email", "t@t"); git("config", "user.name", "t")
            git("config", "commit.gpgsign", "false")
            (wt / ".work-plan").mkdir()
            f = wt / ".work-plan" / "feat.md"
            f.write_text("# feat\n")
            git("add", "."); git("commit", "-q", "-m", "seed")
            f.unlink()
            sha = pw.commit_shared_tier(wt, "remove feat", [".work-plan/feat.md"])
            self.assertIsNotNone(sha)
            self.assertEqual(git("status", "--porcelain").stdout.strip(), "")
            self.assertNotIn("feat.md", git("ls-files").stdout)


if __name__ == "__main__":
    unittest.main()
