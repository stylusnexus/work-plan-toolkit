"""Tests for the rename-track command (issue #174).

Covers:
- Renames a private track → file moved (write new, unlink old), frontmatter
  rewritten with track=new_slug + bumped last_touched, rc 0.
- old@repo / --repo disambiguation flows through find_track_by_name.
- Invalid new slug → rc 2, no move.
- new_slug == old slug → rc 2, no move.
- Target already exists (same repo/tier) → rc 2, no move.
- Unknown old slug → rc 1, no move.
- Public repo, no token → needs_confirm JSON, no move, rc 0; token ==
  make_token(repo, new_slug). Valid token → renames.
- Shared track: --commit stages old+new and commits; without --commit prints
  the 'commit to share' hint and makes no git calls; git failure is non-fatal.
- Cross-references: sibling depends_on warned by default; --fix-refs rewrites
  them.
- "rename-track" in SUBCOMMANDS and DESCRIPTIONS.
"""
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import rename_track
from lib.tracks import Track, AmbiguousTrackError
from lib.write_guard import make_token
import work_plan


NOTES_ROOT = "/tmp/fake-notes"
CLONE_ROOT = "/tmp/fake-clone"


def _cfg():
    return {
        "notes_root": NOTES_ROOT,
        "repos": {"myrepo": {"github": "org/myrepo", "local": None}},
    }


def _track(name, *, repo="org/myrepo", folder="myrepo", tier="private",
           path=None, depends_on=None, meta=None):
    """Build a Track with frontmatter for use as a discover_tracks() return."""
    base_meta = {
        "track": name,
        "status": "active",
        "github": {"repo": repo, "issues": [], "branches": []},
        "depends_on": depends_on or [],
        "last_touched": "2026-01-01T00:00",
    }
    if meta:
        base_meta.update(meta)
    if path is None:
        root = CLONE_ROOT + "/.work-plan" if tier == "shared" else NOTES_ROOT + "/" + folder
        path = f"{root}/{name}.md"
    return Track(
        path=Path(path),
        name=name,
        has_frontmatter=True,
        needs_init=False,
        needs_filing=False,
        repo=repo,
        folder=folder,
        meta=base_meta,
        body=f"# {name}\n",
        tier=tier,
    )


def _drive(args, *, tracks=None, vis="PRIVATE", new_path_exists=False):
    """Run rename_track.run(args) with all external I/O mocked."""
    if tracks is None:
        tracks = [_track("old-feature")]

    def _path_exists(self):
        if self.suffix == ".md":
            return new_path_exists
        return True

    with patch("commands.rename_track.load_config", return_value=_cfg()), \
         patch("commands.rename_track.discover_tracks", return_value=tracks), \
         patch("commands.rename_track.write_file") as mw, \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("pathlib.Path.exists", _path_exists), \
         patch("pathlib.Path.unlink") as munlink:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rename_track.run(args)
    return rc, mw, munlink, buf.getvalue()


class RenameTrackTest(unittest.TestCase):

    # -- registry --------------------------------------------------------
    def test_registered_in_subcommands(self):
        self.assertIn("rename-track", work_plan.SUBCOMMANDS)

    def test_appears_in_descriptions(self):
        names = [e[0] for e in work_plan.DESCRIPTIONS]
        self.assertIn("rename-track", names)

    # -- happy path ------------------------------------------------------
    def test_private_rename_moves_file_and_rewrites_frontmatter(self):
        rc, mw, munlink, out = _drive(["old-feature", "new-feature"])
        self.assertEqual(rc, 0)
        munlink.assert_called_once()
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["track"], "new-feature")
        # write_file targets the new path
        self.assertTrue(str(mw.call_args[0][0]).endswith("new-feature.md"))
        self.assertIn("Renamed track", out)

    def test_last_touched_is_bumped(self):
        rc, mw, munlink, out = _drive(["old-feature", "new-feature"])
        self.assertEqual(rc, 0)
        meta = mw.call_args[0][1]
        self.assertNotEqual(meta["last_touched"], "2026-01-01T00:00")

    def test_rename_uses_same_directory(self):
        """The new file lands in the same dir as the old (rename, not relocate)."""
        rc, mw, munlink, out = _drive(["old-feature", "new-feature"])
        self.assertEqual(rc, 0)
        # write_file targets the new path in the original's directory; the old
        # file is then unlinked (write-new-then-remove-old, no data-loss window).
        write_target = str(mw.call_args[0][0])
        self.assertEqual(write_target, f"{NOTES_ROOT}/myrepo/new-feature.md")
        munlink.assert_called_once()

    # -- validation ------------------------------------------------------
    def test_invalid_new_slug_rc2(self):
        rc, mw, munlink, out = _drive(["old-feature", "New_Feature"])
        self.assertEqual(rc, 2)
        munlink.assert_not_called()
        mw.assert_not_called()

    def test_same_slug_rc2(self):
        rc, mw, munlink, out = _drive(["old-feature", "old-feature"])
        self.assertEqual(rc, 2)
        munlink.assert_not_called()

    def test_target_exists_rc2(self):
        rc, mw, munlink, out = _drive(
            ["old-feature", "taken"], new_path_exists=True
        )
        self.assertEqual(rc, 2)
        munlink.assert_not_called()
        mw.assert_not_called()

    def test_unknown_old_slug_rc1(self):
        rc, mw, munlink, out = _drive(["does-not-exist", "new-feature"])
        self.assertEqual(rc, 1)
        munlink.assert_not_called()

    def test_missing_positionals_rc2(self):
        rc, mw, munlink, out = _drive(["only-one"])
        self.assertEqual(rc, 2)
        munlink.assert_not_called()

    def test_ambiguous_old_slug_rc1(self):
        with patch("commands.rename_track.load_config", return_value=_cfg()), \
             patch("commands.rename_track.discover_tracks", return_value=[]), \
             patch("commands.rename_track.find_track_by_name",
                   side_effect=AmbiguousTrackError("old-feature", [])), \
             patch("commands.rename_track.write_file") as mw:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rename_track.run(["old-feature", "new-feature"])
        self.assertEqual(rc, 1)
        mw.assert_not_called()

    # -- public-repo confirm gate ---------------------------------------
    def test_public_no_token_needs_confirm(self):
        rc, mw, munlink, out = _drive(["old-feature", "new-feature"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        munlink.assert_not_called()
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])
        self.assertEqual(data["token"], make_token("org/myrepo", "new-feature"))

    def test_public_valid_token_renames(self):
        tok = make_token("org/myrepo", "new-feature")
        rc, mw, munlink, out = _drive(
            ["old-feature", "new-feature", f"--confirm={tok}"], vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        munlink.assert_called_once()
        mw.assert_called_once()

    def test_public_wrong_token_blocked(self):
        rc, mw, munlink, out = _drive(
            ["old-feature", "new-feature", "--confirm=nope"], vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        munlink.assert_not_called()

    # -- disambiguation --------------------------------------------------
    def test_repo_qualifier_passed_to_finder(self):
        tracks = [_track("old-feature")]
        with patch("commands.rename_track.load_config", return_value=_cfg()), \
             patch("commands.rename_track.discover_tracks", return_value=tracks), \
             patch("commands.rename_track.find_track_by_name",
                   return_value=tracks[0]) as mfind, \
             patch("commands.rename_track.write_file"), \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("pathlib.Path.exists", lambda self: not str(self).endswith(".md")), \
             patch("pathlib.Path.unlink"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rename_track.run(["old-feature@myrepo", "new-feature"])
        self.assertEqual(mfind.call_args.kwargs.get("repo"), "myrepo")

    # -- cross-references ------------------------------------------------
    def test_dependents_warned_by_default(self):
        tracks = [
            _track("old-feature"),
            _track("sibling", depends_on=["old-feature"]),
        ]
        rc, mw, munlink, out = _drive(
            ["old-feature", "new-feature"], tracks=tracks
        )
        self.assertEqual(rc, 0)
        self.assertIn("depend on 'old-feature'", out)
        self.assertIn("--fix-refs", out)
        # Only the renamed track was written, not the sibling.
        self.assertEqual(mw.call_count, 1)

    def test_fix_refs_rewrites_dependents(self):
        tracks = [
            _track("old-feature"),
            _track("sibling", depends_on=["old-feature", "other"]),
        ]
        rc, mw, munlink, out = _drive(
            ["old-feature", "new-feature", "--fix-refs"], tracks=tracks
        )
        self.assertEqual(rc, 0)
        # Renamed track + the one sibling rewritten.
        self.assertEqual(mw.call_count, 2)
        sibling_write = [c for c in mw.call_args_list
                         if str(c[0][0]).endswith("sibling.md")][0]
        self.assertEqual(sibling_write[0][1]["depends_on"], ["new-feature", "other"])

    def test_dependents_in_other_repo_ignored(self):
        tracks = [
            _track("old-feature"),
            _track("sibling", repo="org/elsewhere", folder="elsewhere",
                   depends_on=["old-feature"]),
        ]
        rc, mw, munlink, out = _drive(
            ["old-feature", "new-feature", "--fix-refs"], tracks=tracks
        )
        self.assertEqual(rc, 0)
        # Different repo → not a referrer; only the renamed track written.
        self.assertEqual(mw.call_count, 1)


# ---------------------------------------------------------------------------
# Shared-track --commit behavior
# ---------------------------------------------------------------------------

class RenameTrackCommitTest(unittest.TestCase):

    def _drive_shared(self, args, *, git_returncode=0):
        track = _track("old-feature", tier="shared")

        def _path_exists(self):
            s = str(self)
            if s == f"{CLONE_ROOT}/.git":
                return True
            if s == CLONE_ROOT:
                return True
            if self.suffix == ".md":
                return False
            return True

        def _is_dir(self):
            return not str(self).endswith(".md")

        git_results = [
            MagicMock(returncode=0, stdout="main\n", stderr=""),  # rev-parse
            MagicMock(returncode=git_returncode, stdout="", stderr="err"),  # add
            MagicMock(returncode=git_returncode, stdout="", stderr=""),  # commit
        ]
        idx = {"n": 0}

        def _git_run(cmd, **kwargs):
            i = idx["n"]
            idx["n"] += 1
            if git_returncode != 0 and i > 0:
                raise subprocess.CalledProcessError(git_returncode, cmd, stderr="err")
            return git_results[min(i, len(git_results) - 1)]

        with patch("commands.rename_track.load_config", return_value=_cfg()), \
             patch("commands.rename_track.discover_tracks", return_value=[track]), \
             patch("commands.rename_track.write_file") as mw, \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("pathlib.Path.exists", _path_exists), \
             patch("pathlib.Path.is_dir", _is_dir), \
             patch("pathlib.Path.unlink"), \
             patch("commands.rename_track.subprocess.run", side_effect=_git_run) as msub:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = rename_track.run(args)
        return rc, mw, msub, buf.getvalue()

    def test_commit_stages_old_and_new_then_commits(self):
        rc, mw, msub, out = self._drive_shared(
            ["old-feature", "new-feature", "--commit"]
        )
        self.assertEqual(rc, 0)
        git_cmds = [c[0][0] for c in msub.call_args_list]
        add_calls = [c for c in git_cmds if "add" in c]
        commit_calls = [c for c in git_cmds if "commit" in c]
        self.assertEqual(len(add_calls), 1)
        self.assertEqual(len(commit_calls), 1)
        # Path-scoped: stages exactly two .md paths (old + new), never ".".
        add_argv = add_calls[0]
        self.assertNotIn(".", add_argv)
        md_args = [a for a in add_argv if a.endswith(".md")]
        self.assertEqual(len(md_args), 2)
        # Commit message names both slugs.
        msg = commit_calls[0][commit_calls[0].index("-m") + 1]
        self.assertIn("old-feature", msg)
        self.assertIn("new-feature", msg)

    def test_no_commit_flag_prints_hint_no_git(self):
        rc, mw, msub, out = self._drive_shared(["old-feature", "new-feature"])
        self.assertEqual(rc, 0)
        msub.assert_not_called()
        self.assertIn("commit + push to share", out)

    def test_commit_git_failure_non_fatal(self):
        rc, mw, msub, out = self._drive_shared(
            ["old-feature", "new-feature", "--commit"], git_returncode=1
        )
        self.assertEqual(rc, 0)
        self.assertIn("⚠", out)


if __name__ == "__main__":
    unittest.main()
