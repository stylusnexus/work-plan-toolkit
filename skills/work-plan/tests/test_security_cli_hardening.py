"""Security hardening regression tests for the CLI (#191, #192, #194, #195, #196).

Covers the guards added in the security-hardening pass:
- parse_flags honours a `--` end-of-options separator (#194)
- git_state.is_safe_ref rejects dash-led revs; commits_ahead/branch_exists
  refuse to pass them to git (#192)
- write_file refuses to write through a symlink (#195)
- init refuses to write outside notes_root; new_track rejects an unsafe folder
  segment (#195)
- discover_tracks skips dash-led track filenames (#194)

The yq-injection fix (#191) and its env-passing are covered in
test_set_notes_root / test_init_repo.
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.prompts import parse_flags
from lib import git_state, frontmatter, tracks
from commands import init as init_cmd
from commands import new_track as new_track_cmd


class ParseFlagsEndOfOptionsTest(unittest.TestCase):
    def test_double_dash_makes_following_args_positional(self):
        flags, positional = parse_flags(["--repo=x", "--", "--repo", "foo"], {"--repo"})
        self.assertEqual(flags, {"--repo": "x"})
        # Everything after `--` is positional, even the flag-looking `--repo`.
        self.assertEqual(positional, ["--repo", "foo"])

    def test_double_dash_itself_is_consumed(self):
        flags, positional = parse_flags(["set", "--", "mytrack"], {"--all"})
        self.assertEqual(positional, ["set", "mytrack"])

    def test_no_double_dash_unchanged(self):
        flags, positional = parse_flags(["track", "--all"], {"--all"})
        self.assertEqual(flags, {"--all": True})
        self.assertEqual(positional, ["track"])


class IsSafeRefTest(unittest.TestCase):
    def test_rejects_dash_led_and_empty(self):
        for bad in ["--output=/tmp/x", "-rf", "--upload-pack=evil", ""]:
            self.assertFalse(git_state.is_safe_ref(bad), bad)

    def test_accepts_normal_refs(self):
        for ok in ["main", "origin/main", "feat/123-x", "v1.2.3", "HEAD"]:
            self.assertTrue(git_state.is_safe_ref(ok), ok)


class GitRefGuardTest(unittest.TestCase):
    def test_commits_ahead_refuses_dash_led_branch_without_calling_git(self):
        with mock.patch("lib.git_state.subprocess.run") as msub, \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            out = git_state.commits_ahead("--output=/tmp/poc", "main", Path("/repo"))
        self.assertEqual(out, 0)
        msub.assert_not_called()  # never reached git

    def test_commits_ahead_refuses_dash_led_base(self):
        with mock.patch("lib.git_state.subprocess.run") as msub, \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            out = git_state.commits_ahead("main", "--all", Path("/repo"))
        self.assertEqual(out, 0)
        msub.assert_not_called()

    def test_branch_exists_refuses_dash_led(self):
        with mock.patch("lib.git_state.subprocess.run") as msub, \
             mock.patch("lib.git_state.Path.exists", return_value=True):
            self.assertFalse(git_state.branch_exists("--verbose", Path("/repo")))
        msub.assert_not_called()


class WriteFileSymlinkGuardTest(unittest.TestCase):
    def test_refuses_to_write_through_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "outside.md"
            target.write_text("original\n", encoding="utf-8")
            link = Path(d) / "track.md"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                frontmatter.write_file(link, {"track": "x"}, "body")
            # Target must be untouched.
            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")

    def test_normal_write_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "track.md"
            frontmatter.write_file(p, {}, "hello\n")
            self.assertEqual(p.read_text(encoding="utf-8"), "hello\n")


class InitContainmentTest(unittest.TestCase):
    def test_refuses_path_outside_notes_root(self):
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "victim.md"
            target.write_text("do not clobber\n", encoding="utf-8")
            cfg = {"notes_root": notes, "repos": {}}
            with mock.patch("commands.init.load_config", return_value=cfg):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = init_cmd.run([str(target)])
            self.assertEqual(rc, 1)
            self.assertIn("not inside notes_root", buf.getvalue())
            # File left untouched (no frontmatter prepended).
            self.assertEqual(target.read_text(encoding="utf-8"), "do not clobber\n")


class NewTrackFolderGuardTest(unittest.TestCase):
    def test_rejects_dotdot_folder_segment(self):
        cfg = {"notes_root": "/tmp/does-not-matter", "repos": {}}
        # new-track <repo> <slug>; repo arg "x/.." derives folder ".." → reject.
        with mock.patch("commands.new_track.load_config", return_value=cfg):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = new_track_cmd.run(["x/..", "myslug"])
        self.assertEqual(rc, 2)
        self.assertIn("safe notes folder", buf.getvalue())


class DiscoverTracksDashLedTest(unittest.TestCase):
    def test_dash_led_md_file_is_not_a_track(self):
        with tempfile.TemporaryDirectory() as notes:
            root = Path(notes)
            (root / "good.md").write_text("---\ntrack: good\nstatus: active\n---\nbody\n", encoding="utf-8")
            (root / "--repo.md").write_text("---\ntrack: x\nstatus: active\n---\nbody\n", encoding="utf-8")
            cfg = {"notes_root": notes, "repos": {}}
            found = {t.name for t in tracks.discover_tracks(cfg)}
        self.assertIn("good", found)
        self.assertNotIn("--repo", found)


if __name__ == "__main__":
    unittest.main()
