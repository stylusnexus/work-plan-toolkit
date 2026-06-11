"""Tests for the notes-vcs command + the dispatcher auto-commit hook (#103).

All git and yq calls are mocked — offline, no real repo touched.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan
from commands import notes_vcs as cmd


def _cfg(notes_root="/tmp/notes", auto=None):
    c = {"notes_root": notes_root, "repos": {}}
    if auto is not None:
        c["notes_vcs"] = {"auto_commit": auto}
    return c


def _drive(args, *, cfg=None, is_root=False, is_under=False,
           last="ab12 subject", set_ok=True, init_ok=True, dirty=False,
           sha="ab12", revert_sha="rev99", remotes=False, owned=True,
           parent=None):
    cfg = cfg or _cfg()
    with patch("commands.notes_vcs.load_config", return_value=cfg), \
         patch("commands.notes_vcs.notes_vcs.is_git_root", return_value=is_root), \
         patch("commands.notes_vcs.notes_vcs.is_under_git", return_value=is_under), \
         patch("commands.notes_vcs.notes_vcs.has_remotes", return_value=remotes), \
         patch("commands.notes_vcs.notes_vcs.is_owned", return_value=owned), \
         patch("commands.notes_vcs.notes_vcs.last_commit_summary", return_value=last), \
         patch("commands.notes_vcs.notes_vcs.last_commit_sha", return_value=sha), \
         patch("commands.notes_vcs.notes_vcs.head_parent_sha", return_value=parent), \
         patch("commands.notes_vcs.notes_vcs.has_changes", return_value=dirty), \
         patch("commands.notes_vcs.notes_vcs.init_repo", return_value=init_ok), \
         patch("commands.notes_vcs.notes_vcs.revert", return_value=revert_sha) as mrev, \
         patch("commands.notes_vcs._set_auto_commit", return_value=set_ok) as mset:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd.run(args)
    return rc, buf.getvalue(), mset, mrev


class NotesVcsStatusTest(unittest.TestCase):
    def test_status_repo_on(self):
        rc, out, _, _ = _drive(["status"], cfg=_cfg(auto=True), is_root=True)
        self.assertEqual(rc, 0)
        self.assertIn("local repo", out)
        self.assertIn("auto-commit: on", out)

    def test_status_not_a_repo(self):
        rc, out, _, _ = _drive(["status"], cfg=_cfg(auto=False), is_root=False)
        self.assertEqual(rc, 0)
        self.assertIn("not a repo", out)
        self.assertIn("auto-commit: off", out)

    def test_status_inside_other_repo(self):
        rc, out, _, _ = _drive(["status"], is_root=False, is_under=True)
        self.assertEqual(rc, 0)
        self.assertIn("NOT its root", out)

    def test_default_action_is_status(self):
        rc, out, _, _ = _drive([], is_root=True)
        self.assertEqual(rc, 0)
        self.assertIn("notes_root:", out)


class NotesVcsInitTest(unittest.TestCase):
    def test_init_enables_by_default(self):
        rc, out, mset, _ = _drive(["init"], is_root=False, is_under=False)
        self.assertEqual(rc, 0)
        self.assertIn("Initialized local history", out)
        mset.assert_called_once_with(True)
        self.assertIn("auto-commit enabled", out)

    def test_init_no_enable_skips_toggle(self):
        rc, out, mset, _ = _drive(["init", "--no-enable"], is_root=False)
        self.assertEqual(rc, 0)
        mset.assert_not_called()
        self.assertIn("left off", out)

    def test_init_refuses_inside_other_repo(self):
        rc, out, mset, _ = _drive(["init"], is_root=False, is_under=True)
        self.assertEqual(rc, 1)
        self.assertIn("not its root", out.lower())
        mset.assert_not_called()

    def test_init_fails_when_init_repo_fails(self):
        rc, out, mset, _ = _drive(["init"], is_root=False, is_under=False, init_ok=False)
        self.assertEqual(rc, 1)
        self.assertIn("failed to git-init", out)

    def test_init_refuses_existing_repo_with_remote(self):
        # An existing repo with a remote must be rejected — private notes must
        # never be pushable (Codex high #1).
        rc, out, mset, _ = _drive(["init"], is_root=True, remotes=True)
        self.assertEqual(rc, 1)
        self.assertIn("remote", out.lower())
        mset.assert_not_called()

    def test_init_refuses_existing_unowned_repo(self):
        # An existing repo work-plan didn't create must not be adopted.
        rc, out, mset, _ = _drive(["init"], is_root=True, remotes=False, owned=False)
        self.assertEqual(rc, 1)
        self.assertIn("not created by work-plan", out)
        mset.assert_not_called()


class NotesVcsToggleTest(unittest.TestCase):
    def test_enable(self):
        rc, out, mset, _ = _drive(["enable"], is_root=True)
        self.assertEqual(rc, 0)
        mset.assert_called_once_with(True)

    def test_enable_warns_when_not_repo(self):
        rc, out, mset, _ = _drive(["enable"], is_root=False)
        self.assertEqual(rc, 0)
        self.assertIn("WARN", out)

    def test_disable(self):
        rc, out, mset, _ = _drive(["disable"], is_root=True)
        self.assertEqual(rc, 0)
        mset.assert_called_once_with(False)

    def test_unknown_action_rc2(self):
        rc, out, _, _ = _drive(["frobnicate"])
        self.assertEqual(rc, 2)
        self.assertIn("usage", out.lower())


class NotesVcsStatusJsonTest(unittest.TestCase):
    def test_json_shape(self):
        import json
        rc, out, _, _ = _drive(["status", "--json"], cfg=_cfg(auto=True),
                               is_root=True, is_under=True, sha="ab12",
                               last="ab12 subject", dirty=False, parent="pa01")
        self.assertEqual(rc, 0)
        blob = json.loads(out)
        self.assertEqual(blob["auto_commit"], True)
        self.assertEqual(blob["is_root"], True)
        self.assertEqual(blob["under_git"], True)
        self.assertEqual(blob["last_commit_sha"], "ab12")
        self.assertEqual(blob["head_parent_sha"], "pa01")
        self.assertEqual(blob["dirty"], False)

    def test_json_nulls_when_not_repo(self):
        import json
        rc, out, _, _ = _drive(["status", "--json"], cfg=_cfg(auto=False),
                               is_root=False, is_under=False)
        blob = json.loads(out)
        self.assertEqual(blob["is_root"], False)
        self.assertIsNone(blob["last_commit_sha"])
        self.assertEqual(blob["auto_commit"], False)


class NotesVcsUndoTest(unittest.TestCase):
    def test_undo_head_default(self):
        rc, out, _, mrev = _drive(["undo"], is_root=True, revert_sha="rev99")
        self.assertEqual(rc, 0)
        mrev.assert_called_once()
        # default sha is None → revert(notes_root, None)
        self.assertIsNone(mrev.call_args[0][1])
        self.assertIn("rev99", out)

    def test_undo_named_sha(self):
        rc, out, _, mrev = _drive(["undo", "abc1234"], is_root=True,
                                  revert_sha="rev88")
        self.assertEqual(rc, 0)
        self.assertEqual(mrev.call_args[0][1], "abc1234")

    def test_undo_refuses_when_not_repo(self):
        rc, out, _, mrev = _drive(["undo"], is_root=False)
        self.assertEqual(rc, 1)
        mrev.assert_not_called()
        self.assertIn("not a git repo", out)

    def test_undo_fails_when_revert_fails(self):
        rc, out, _, mrev = _drive(["undo"], is_root=True, revert_sha=None)
        self.assertEqual(rc, 1)
        self.assertIn("failed to revert", out)


class RegistrationTest(unittest.TestCase):
    def test_in_subcommands(self):
        self.assertEqual(work_plan.SUBCOMMANDS["notes-vcs"], "commands.notes_vcs")

    def test_in_descriptions(self):
        names = [e[0] for e in work_plan.DESCRIPTIONS]
        self.assertIn("notes-vcs", names)


class DispatcherHookTest(unittest.TestCase):
    """The two-phase auto-commit hook: snapshot dirty paths BEFORE the command
    (_notes_precommit_state), then commit ONLY the paths it changed
    (_commit_changed_notes). Gated on opt-in + owned + no-remote; never raises.
    """

    def _run_dispatch(self, sub, parts, *, cfg, is_root=True, is_under=False,
                      owned=True, remotes=False, before=None, after=None,
                      sha="c0ffee"):
        before = set() if before is None else set(before)
        after = before if after is None else set(after)
        dirty_seq = [before, after]
        with patch("lib.config.load_config", return_value=cfg), \
             patch("lib.notes_vcs.is_git_root", return_value=is_root), \
             patch("lib.notes_vcs.is_under_git", return_value=is_under), \
             patch("lib.notes_vcs.is_owned", return_value=owned), \
             patch("lib.notes_vcs.has_remotes", return_value=remotes), \
             patch("lib.notes_vcs.dirty_paths", side_effect=lambda _r: dirty_seq.pop(0)), \
             patch("lib.notes_vcs.auto_commit", return_value=sha) as mac:
            err = io.StringIO()
            with redirect_stderr(err):
                pre = work_plan._notes_precommit_state(sub)
                if pre is not None:
                    work_plan._commit_changed_notes(pre, parts)
            return err.getvalue(), mac, pre

    def test_commits_only_paths_changed_by_the_command(self):
        out, mac, pre = self._run_dispatch(
            "slot", ["slot", "103", "tabletop"], cfg=_cfg(auto=True),
            before=set(), after={"tabletop.md"})
        self.assertIsNotNone(pre)
        mac.assert_called_once()
        self.assertEqual(mac.call_args[0][1], "work-plan slot 103 tabletop")
        self.assertEqual(mac.call_args[1]["paths"], ["tabletop.md"])
        self.assertIn("committed c0ffee", out)

    def test_preserves_preexisting_dirty_files(self):
        # A file dirty BEFORE the command stays out of the commit.
        out, mac, _ = self._run_dispatch(
            "slot", ["slot", "1", "t"], cfg=_cfg(auto=True),
            before={"manual.md"}, after={"manual.md", "t.md"})
        mac.assert_called_once()
        self.assertEqual(mac.call_args[1]["paths"], ["t.md"])

    def test_noop_when_command_changed_nothing(self):
        out, mac, _ = self._run_dispatch(
            "slot", ["slot", "1", "t"], cfg=_cfg(auto=True),
            before={"manual.md"}, after={"manual.md"})
        mac.assert_not_called()

    def test_skips_read_only_command(self):
        out, mac, pre = self._run_dispatch(
            "brief", ["brief"], cfg=_cfg(auto=True), after={"x.md"})
        self.assertIsNone(pre)
        mac.assert_not_called()

    def test_skips_read_only_flag_alias(self):
        out, mac, pre = self._run_dispatch(
            "--brief", ["--brief"], cfg=_cfg(auto=True), after={"x.md"})
        self.assertIsNone(pre)
        mac.assert_not_called()

    def test_skips_when_disabled(self):
        out, mac, pre = self._run_dispatch(
            "slot", ["slot", "1", "t"], cfg=_cfg(auto=False), after={"x.md"})
        self.assertIsNone(pre)
        mac.assert_not_called()

    def test_skips_when_unowned(self):
        out, mac, pre = self._run_dispatch(
            "slot", ["slot", "1", "t"], cfg=_cfg(auto=True), owned=False,
            after={"x.md"})
        self.assertIsNone(pre)
        mac.assert_not_called()

    def test_skips_when_remote_backed(self):
        out, mac, pre = self._run_dispatch(
            "slot", ["slot", "1", "t"], cfg=_cfg(auto=True), remotes=True,
            after={"x.md"})
        self.assertIsNone(pre)
        mac.assert_not_called()

    def test_nudges_when_enabled_but_not_repo(self):
        out, mac, pre = self._run_dispatch(
            "slot", ["slot", "1", "t"], cfg=_cfg(auto=True), is_root=False,
            is_under=False, after={"x.md"})
        self.assertIsNone(pre)
        mac.assert_not_called()
        self.assertIn("notes-vcs init", out)

    def test_skips_self(self):
        # notes-vcs manages its own repo; the hook must not double-commit.
        with patch("lib.config.load_config") as mload:
            pre = work_plan._notes_precommit_state("notes-vcs")
            self.assertIsNone(pre)
            mload.assert_not_called()

    def test_precommit_never_raises_on_failure(self):
        with patch("lib.config.load_config", side_effect=RuntimeError("boom")):
            self.assertIsNone(work_plan._notes_precommit_state("slot"))


if __name__ == "__main__":
    unittest.main()
