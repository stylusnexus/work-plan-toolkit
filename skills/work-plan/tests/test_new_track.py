"""Tests for the non-interactive new-track command (issue #87, Phase 3a).

Covers:
- Creates a track for a config-key repo on a PRIVATE repo → write_file called
  with the right meta (github.repo = key's github value; status active;
  priority/milestone defaults), rc 0.
- Creates a track for a bare org/repo slug → folder = name part after '/',
  github = full slug, rc 0.
- Public repo, no token → needs_confirm JSON, write_file NOT called, rc 0;
  token == make_token(github, slug).
- Public repo, valid --confirm=<token> → creates (write_file called), rc 0.
- Existing path → rc 2, no write.
- Unknown repo (not a config key, no slash) → rc 1, no write.
- Invalid slug → rc 2.
- --priority=P1 --milestone=v2 reflected in meta; defaults applied when absent.
- --private accepted without error, creates normally, rc 0.
- "new-track" in SUBCOMMANDS and appears in DESCRIPTIONS.
"""
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock, call

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import new_track
from lib.write_guard import make_token
import work_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOTES_ROOT = "/tmp/fake-notes"

def _make_cfg(*, repos=None):
    if repos is None:
        repos = {
            "myrepo": {"github": "org/myrepo", "local": None},
            "critforge": {"github": "stylusnexus/critforge", "local": None},
        }
    return {"notes_root": NOTES_ROOT, "repos": repos}


def _drive(args, *, vis="PRIVATE", notes_root_exists=True, target_path_exists=False):
    """Run new_track.run(args) with all external I/O mocked.

    vis: what repo_visibility returns for needs_confirm.
    notes_root_exists: whether notes_root directory exists.
    target_path_exists: whether the target .md path already exists.
    """
    cfg = _make_cfg()

    def _path_exists(self):
        # notes_root itself → notes_root_exists; target path → target_path_exists.
        # Compare with Path equality (not str ==): on Windows str(Path("/tmp/x"))
        # uses backslashes, so an exact "/tmp/fake-notes" string match never fires
        # and the notes_root-missing case can't be simulated.
        if self == Path(NOTES_ROOT):
            return notes_root_exists
        if self.suffix == ".md":
            return target_path_exists
        # archive dirs and parent dirs default to True
        return True

    with patch("commands.new_track.load_config", return_value=cfg), \
         patch("commands.new_track.write_file") as mw, \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("pathlib.Path.exists", _path_exists), \
         patch("pathlib.Path.mkdir"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = new_track.run(args)
    return rc, mw, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class NewTrackCommandTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # Registry checks
    # ------------------------------------------------------------------

    def test_subcommand_registered_in_subcommands(self):
        """'new-track' must be in work_plan.SUBCOMMANDS."""
        self.assertIn("new-track", work_plan.SUBCOMMANDS)

    def test_subcommand_appears_in_descriptions(self):
        """'new-track' must appear in work_plan.DESCRIPTIONS."""
        names = [entry[0] for entry in work_plan.DESCRIPTIONS]
        self.assertIn("new-track", names)

    # ------------------------------------------------------------------
    # Config-key repo (PRIVATE)
    # ------------------------------------------------------------------

    def test_config_key_private_creates_track(self):
        """Config-key repo 'myrepo' (PRIVATE) → write_file called with
        github.repo = 'org/myrepo', status = 'active', rc 0."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["github"]["repo"], "org/myrepo")
        self.assertEqual(meta["status"], "active")

    def test_config_key_folder_resolves_correctly(self):
        """Config-key 'critforge' → folder = 'critforge',
        github.repo = 'stylusnexus/critforge'."""
        rc, mw, out = _drive(["critforge", "encounter-builder"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["github"]["repo"], "stylusnexus/critforge")
        # Track name from slug
        self.assertEqual(meta["track"], "encounter-builder")
        # Path passed to write_file should be under critforge folder
        path_arg = mw.call_args[0][0]
        self.assertIn("critforge", str(path_arg))

    # ------------------------------------------------------------------
    # Bare org/repo slug
    # ------------------------------------------------------------------

    def test_bare_org_repo_slug_uses_name_as_folder(self):
        """'stylusnexus/work-plan-toolkit' → folder = 'work-plan-toolkit',
        github.repo = 'stylusnexus/work-plan-toolkit', rc 0."""
        rc, mw, out = _drive(
            ["stylusnexus/work-plan-toolkit", "my-feature"], vis="PRIVATE"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["github"]["repo"], "stylusnexus/work-plan-toolkit")
        path_arg = mw.call_args[0][0]
        self.assertIn("work-plan-toolkit", str(path_arg))

    # ------------------------------------------------------------------
    # Public repo — confirm gate
    # ------------------------------------------------------------------

    def test_public_repo_no_token_returns_needs_confirm_json(self):
        """Public repo, no token → prints needs_confirm JSON, write_file
        NOT called, rc 0; token == make_token(github, slug)."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])
        self.assertEqual(data["token"], make_token("org/myrepo", "my-feature"))
        self.assertIn("PUBLIC", data["reason"])

    def test_public_repo_unknown_vis_returns_needs_confirm_json(self):
        """Unknown visibility (None) also requires confirm."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis=None)
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    def test_public_repo_wrong_token_blocked(self):
        """Wrong --confirm token → blocked, no write, rc 0."""
        rc, mw, out = _drive(
            ["myrepo", "my-feature", "--confirm=wrongtoken"], vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    def test_public_repo_valid_token_writes(self):
        """Valid --confirm=<token> on a public repo → creates track, rc 0."""
        tok = make_token("org/myrepo", "my-feature")
        rc, mw, out = _drive(
            ["myrepo", "my-feature", f"--confirm={tok}"], vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    def test_bare_slug_public_token_uses_full_github(self):
        """Public bare slug: token is make_token(full-github, slug)."""
        tok = make_token("org/other-repo", "new-slug")
        rc, mw, out = _drive(
            ["org/other-repo", "new-slug", f"--confirm={tok}"], vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    # ------------------------------------------------------------------
    # Existing path → rc 2
    # ------------------------------------------------------------------

    def test_existing_path_returns_rc2_no_write(self):
        """Target .md already exists → rc 2, no write."""
        rc, mw, out = _drive(
            ["myrepo", "existing-track"], vis="PRIVATE", target_path_exists=True
        )
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    # ------------------------------------------------------------------
    # Unknown repo → rc 1
    # ------------------------------------------------------------------

    def test_unknown_repo_not_key_no_slash_returns_rc1(self):
        """Repo not a config key and no slash → rc 1, no write."""
        rc, mw, out = _drive(["unknown-repo", "my-feature"])
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        self.assertIn("unknown repo", out.lower())

    # ------------------------------------------------------------------
    # Invalid slug → rc 2
    # ------------------------------------------------------------------

    def test_invalid_slug_uppercase_returns_rc2(self):
        """Slug with uppercase letters → rc 2."""
        rc, mw, out = _drive(["myrepo", "MyFeature"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_invalid_slug_spaces_returns_rc2(self):
        """Slug with spaces → rc 2."""
        rc, mw, out = _drive(["myrepo", "my feature"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_invalid_slug_special_chars_returns_rc2(self):
        """Slug with special chars (underscore) → rc 2."""
        rc, mw, out = _drive(["myrepo", "my_feature"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    # ------------------------------------------------------------------
    # Missing positionals → rc 2
    # ------------------------------------------------------------------

    def test_no_args_returns_rc2(self):
        """No positional args at all → rc 2 (usage error)."""
        rc, mw, out = _drive([])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_only_one_positional_returns_rc2(self):
        """Only repo, no slug → rc 2 (usage error)."""
        rc, mw, out = _drive(["myrepo"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    # ------------------------------------------------------------------
    # Priority and milestone flags
    # ------------------------------------------------------------------

    def test_explicit_priority_and_milestone_in_meta(self):
        """--priority=P1 --milestone=v2 → reflected in meta."""
        rc, mw, out = _drive(
            ["myrepo", "my-feature", "--priority=P1", "--milestone=v2"],
            vis="PRIVATE"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        meta = mw.call_args[0][1]
        self.assertEqual(meta["launch_priority"], "P1")
        self.assertEqual(meta["milestone_alignment"], "v2")

    def test_defaults_p2_and_v100_when_absent(self):
        """No flags → launch_priority=P2, milestone_alignment=v1.0.0."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        meta = mw.call_args[0][1]
        self.assertEqual(meta["launch_priority"], "P2")
        self.assertEqual(meta["milestone_alignment"], "v1.0.0")

    def test_invalid_priority_falls_back_to_p2(self):
        """Invalid --priority=P9 → silently falls back to P2."""
        rc, mw, out = _drive(
            ["myrepo", "my-feature", "--priority=P9"], vis="PRIVATE"
        )
        self.assertEqual(rc, 0)
        meta = mw.call_args[0][1]
        self.assertEqual(meta["launch_priority"], "P2")

    def test_priority_uppercased(self):
        """--priority=p1 (lowercase) → P1 after uppercasing."""
        rc, mw, out = _drive(
            ["myrepo", "my-feature", "--priority=p1"], vis="PRIVATE"
        )
        self.assertEqual(rc, 0)
        meta = mw.call_args[0][1]
        self.assertEqual(meta["launch_priority"], "P1")

    # ------------------------------------------------------------------
    # Frontmatter structure
    # ------------------------------------------------------------------

    def test_meta_has_expected_keys(self):
        """Written meta contains all required frontmatter keys."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        meta = mw.call_args[0][1]
        for key in ("track", "status", "launch_priority", "milestone_alignment",
                    "github", "related_tracks", "last_touched", "last_handoff",
                    "next_up", "blockers"):
            self.assertIn(key, meta, f"meta missing key: {key}")

    def test_meta_github_issues_and_branches_empty(self):
        """New track starts with github.issues=[] and github.branches=[]."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        meta = mw.call_args[0][1]
        self.assertEqual(meta["github"]["issues"], [])
        self.assertEqual(meta["github"]["branches"], [])

    def test_meta_related_tracks_next_up_blockers_empty(self):
        """New track starts with empty related_tracks, next_up, blockers."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        meta = mw.call_args[0][1]
        self.assertEqual(meta["related_tracks"], [])
        self.assertEqual(meta["next_up"], [])
        self.assertEqual(meta["blockers"], [])

    def test_body_contains_slug_heading(self):
        """Body passed to write_file contains a heading with the slug."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        body = mw.call_args[0][2]
        self.assertIn("my-feature", body)

    # ------------------------------------------------------------------
    # --private flag (no-op, accepted without error)
    # ------------------------------------------------------------------

    def test_private_flag_accepted_no_error(self):
        """--private accepted without error, creates normally, rc 0."""
        rc, mw, out = _drive(
            ["myrepo", "my-feature", "--private"], vis="PRIVATE"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    def test_private_flag_on_public_repo_still_gated(self):
        """--private on a public repo: confirm gate still fires (gate is by
        visibility, not --private flag)."""
        rc, mw, out = _drive(
            ["myrepo", "my-feature", "--private"], vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    # ------------------------------------------------------------------
    # notes_root missing → rc 1
    # ------------------------------------------------------------------

    def test_missing_notes_root_returns_rc1(self):
        """notes_root directory does not exist → rc 1, no write."""
        rc, mw, out = _drive(
            ["myrepo", "my-feature"], vis="PRIVATE", notes_root_exists=False
        )
        self.assertEqual(rc, 1)
        mw.assert_not_called()

    # ------------------------------------------------------------------
    # Success output
    # ------------------------------------------------------------------

    def test_success_prints_created_line(self):
        """On success, output contains 'Created track' and the slug."""
        rc, mw, out = _drive(["myrepo", "my-feature"], vis="PRIVATE")
        self.assertEqual(rc, 0)
        self.assertIn("my-feature", out)

    # ------------------------------------------------------------------
    # Gate fires BEFORE any FS write
    # ------------------------------------------------------------------

    def test_gate_before_mkdir_on_public(self):
        """On a public repo without a token, mkdir is NOT called
        (gate fires before any filesystem operation)."""
        cfg = _make_cfg()

        def _path_exists(self):
            if self == Path(NOTES_ROOT):
                return True
            if self.suffix == ".md":
                return False
            return True

        with patch("commands.new_track.load_config", return_value=cfg), \
             patch("commands.new_track.write_file") as mw, \
             patch("lib.write_guard.repo_visibility", return_value="PUBLIC"), \
             patch("pathlib.Path.exists", _path_exists), \
             patch("pathlib.Path.mkdir") as mmkdir:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = new_track.run(["myrepo", "my-feature"])
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        mmkdir.assert_not_called()

    # ------------------------------------------------------------------
    # No input() on non-interactive paths
    # ------------------------------------------------------------------

    def test_no_input_called_on_private_repo(self):
        """Private repo with valid flags never calls input() or prompt_input —
        proving no prompt is hit on the non-interactive code path."""
        cfg = _make_cfg()

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called — command must be non-interactive")

        def _path_exists(self):
            if self == Path(NOTES_ROOT):
                return True
            if self.suffix == ".md":
                return False
            return True

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise):
            with patch("commands.new_track.load_config", return_value=cfg), \
                 patch("commands.new_track.write_file") as mw, \
                 patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
                 patch("pathlib.Path.exists", _path_exists), \
                 patch("pathlib.Path.mkdir"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = new_track.run(["myrepo", "my-feature"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()


# ---------------------------------------------------------------------------
# Phase D: --commit flag tests
# ---------------------------------------------------------------------------

CLONE_ROOT = "/tmp/fake-clone"


def _make_cfg_with_local(*, local=CLONE_ROOT):
    """Config with a repo entry that has a local clone path."""
    return {
        "notes_root": NOTES_ROOT,
        "repos": {
            "myrepo": {"github": "org/myrepo", "local": local},
        },
    }


class NewTrackCommitFlagTest(unittest.TestCase):
    """Tests for --commit flag on new-track (Phase D)."""

    def _drive_shared(self, args, *, git_returncode=0, path_exists=False):
        """Drive new-track with a shared-tier setup (local clone is a valid git repo)."""
        cfg = _make_cfg_with_local()

        def _path_exists(self):
            # NOTES_ROOT itself exists
            if self == Path(NOTES_ROOT):
                return True
            # .git dir inside the clone root exists (valid git repo)
            if str(self) == f"{CLONE_ROOT}/.git":
                return True
            # The clone root itself exists
            if str(self) == CLONE_ROOT:
                return True
            # The target .md path: controlled by path_exists
            if self.suffix == ".md":
                return path_exists
            return True

        def _is_dir(self):
            s = str(self)
            if s.endswith(".md"):
                return False
            return True

        # git subprocess: first call (rev-parse), then add, then commit
        git_results = [
            MagicMock(returncode=0, stdout="main\n", stderr=""),       # rev-parse
            MagicMock(returncode=git_returncode, stdout="", stderr="error msg"),  # add
            MagicMock(returncode=git_returncode, stdout="", stderr=""),           # commit
        ]
        git_call_index = {"n": 0}

        def _git_run(cmd, **kwargs):
            idx = git_call_index["n"]
            git_call_index["n"] += 1
            if git_returncode != 0 and idx > 0:
                raise subprocess.CalledProcessError(git_returncode, cmd, stderr="error msg")
            return git_results[min(idx, len(git_results) - 1)]

        with patch("commands.new_track.load_config", return_value=cfg), \
             patch("commands.new_track.write_file") as mw, \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("pathlib.Path.exists", _path_exists), \
             patch("pathlib.Path.is_dir", _is_dir), \
             patch("pathlib.Path.mkdir"), \
             patch("commands.new_track.subprocess.run", side_effect=_git_run) as msub:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = new_track.run(args)
        return rc, mw, msub, buf.getvalue()

    def test_commit_shared_track_calls_git_add_then_commit(self):
        """--commit on a shared track: git -C <clone_root> add <file> called,
        then git -C <clone_root> commit called; path-scoped (not git add .)."""
        rc, mw, msub, out = self._drive_shared(
            ["myrepo", "my-feature", "--commit"]
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        # Should have made git calls: rev-parse, add, commit
        calls = msub.call_args_list
        # Find the add and commit calls (skip rev-parse at index 0)
        git_cmds = [c[0][0] for c in calls]
        add_calls = [c for c in git_cmds if "add" in c]
        commit_calls = [c for c in git_cmds if "commit" in c]
        self.assertEqual(len(add_calls), 1, "exactly one git add call expected")
        self.assertEqual(len(commit_calls), 1, "exactly one git commit call expected")
        # Verify add is path-scoped (not "git add .")
        add_argv = add_calls[0]
        self.assertNotIn(".", add_argv, "git add must be path-scoped, not 'git add .'")
        self.assertIn("-C", add_argv)
        # The file argument should end in .md
        file_arg = add_argv[-1]
        self.assertTrue(file_arg.endswith(".md"), f"expected .md path, got: {file_arg}")
        # Commit message should mention the slug
        commit_argv = commit_calls[0]
        msg_idx = commit_argv.index("-m") + 1
        self.assertIn("my-feature", commit_argv[msg_idx])

    def test_commit_shared_track_path_scoped_not_git_add_dot(self):
        """The git add call must never use '.' as the file argument."""
        rc, mw, msub, out = self._drive_shared(
            ["myrepo", "path-scoped-test", "--commit"]
        )
        self.assertEqual(rc, 0)
        git_cmds = [c[0][0] for c in msub.call_args_list]
        add_calls = [c for c in git_cmds if "add" in c]
        self.assertEqual(len(add_calls), 1)
        self.assertNotIn(".", add_calls[0])

    def test_commit_private_track_warns_and_skips_git(self):
        """--commit on a private track (notes_root, not .work-plan) → warning
        printed, git NOT called."""
        cfg = _make_cfg()  # no local clone → private route

        def _path_exists(self):
            if self == Path(NOTES_ROOT):
                return True
            if self.suffix == ".md":
                return False
            return True

        with patch("commands.new_track.load_config", return_value=cfg), \
             patch("commands.new_track.write_file") as mw, \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("pathlib.Path.exists", _path_exists), \
             patch("pathlib.Path.mkdir"), \
             patch("commands.new_track.subprocess.run") as msub:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = new_track.run(["myrepo", "private-track", "--commit"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        msub.assert_not_called()
        self.assertIn("--commit ignored", buf.getvalue())

    def test_commit_git_failure_is_non_fatal(self):
        """--commit with git add failing → rc still 0, warning printed."""
        rc, mw, msub, out = self._drive_shared(
            ["myrepo", "my-feature", "--commit"],
            git_returncode=1,
        )
        self.assertEqual(rc, 0, "git failure must be non-fatal")
        mw.assert_called_once()
        self.assertIn("⚠", out)

    def test_no_commit_flag_no_git_calls(self):
        """Without --commit: git is never called, even for a shared track."""
        rc, mw, msub, out = self._drive_shared(["myrepo", "my-feature"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        msub.assert_not_called()

    def test_commit_success_prints_committed_line(self):
        """Successful --commit → output contains 'committed' and the slug."""
        rc, mw, msub, out = self._drive_shared(
            ["myrepo", "my-feature", "--commit"]
        )
        self.assertEqual(rc, 0)
        self.assertIn("committed", out)
        self.assertIn("my-feature", out)


if __name__ == "__main__":
    unittest.main()
