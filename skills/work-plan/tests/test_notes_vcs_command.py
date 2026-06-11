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
           last="ab12 subject", set_ok=True, init_ok=True, dirty=False):
    cfg = cfg or _cfg()
    with patch("commands.notes_vcs.load_config", return_value=cfg), \
         patch("commands.notes_vcs.notes_vcs.is_git_root", return_value=is_root), \
         patch("commands.notes_vcs.notes_vcs.is_under_git", return_value=is_under), \
         patch("commands.notes_vcs.notes_vcs.last_commit_summary", return_value=last), \
         patch("commands.notes_vcs.notes_vcs.has_changes", return_value=dirty), \
         patch("commands.notes_vcs.notes_vcs.init_repo", return_value=init_ok), \
         patch("commands.notes_vcs._set_auto_commit", return_value=set_ok) as mset:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd.run(args)
    return rc, buf.getvalue(), mset


class NotesVcsStatusTest(unittest.TestCase):
    def test_status_repo_on(self):
        rc, out, _ = _drive(["status"], cfg=_cfg(auto=True), is_root=True)
        self.assertEqual(rc, 0)
        self.assertIn("local repo", out)
        self.assertIn("auto-commit: on", out)

    def test_status_not_a_repo(self):
        rc, out, _ = _drive(["status"], cfg=_cfg(auto=False), is_root=False)
        self.assertEqual(rc, 0)
        self.assertIn("not a repo", out)
        self.assertIn("auto-commit: off", out)

    def test_status_inside_other_repo(self):
        rc, out, _ = _drive(["status"], is_root=False, is_under=True)
        self.assertEqual(rc, 0)
        self.assertIn("NOT its root", out)

    def test_default_action_is_status(self):
        rc, out, _ = _drive([], is_root=True)
        self.assertEqual(rc, 0)
        self.assertIn("notes_root:", out)


class NotesVcsInitTest(unittest.TestCase):
    def test_init_enables_by_default(self):
        rc, out, mset = _drive(["init"], is_root=False, is_under=False)
        self.assertEqual(rc, 0)
        self.assertIn("Initialized local history", out)
        mset.assert_called_once_with(True)
        self.assertIn("auto-commit enabled", out)

    def test_init_no_enable_skips_toggle(self):
        rc, out, mset = _drive(["init", "--no-enable"], is_root=False)
        self.assertEqual(rc, 0)
        mset.assert_not_called()
        self.assertIn("left off", out)

    def test_init_refuses_inside_other_repo(self):
        rc, out, mset = _drive(["init"], is_root=False, is_under=True)
        self.assertEqual(rc, 1)
        self.assertIn("not its root", out.lower())
        mset.assert_not_called()

    def test_init_fails_when_init_repo_fails(self):
        rc, out, mset = _drive(["init"], is_root=False, is_under=False, init_ok=False)
        self.assertEqual(rc, 1)
        self.assertIn("failed to git-init", out)


class NotesVcsToggleTest(unittest.TestCase):
    def test_enable(self):
        rc, out, mset = _drive(["enable"], is_root=True)
        self.assertEqual(rc, 0)
        mset.assert_called_once_with(True)

    def test_enable_warns_when_not_repo(self):
        rc, out, mset = _drive(["enable"], is_root=False)
        self.assertEqual(rc, 0)
        self.assertIn("WARN", out)

    def test_disable(self):
        rc, out, mset = _drive(["disable"], is_root=True)
        self.assertEqual(rc, 0)
        mset.assert_called_once_with(False)

    def test_unknown_action_rc2(self):
        rc, out, _ = _drive(["frobnicate"])
        self.assertEqual(rc, 2)
        self.assertIn("usage", out.lower())


class RegistrationTest(unittest.TestCase):
    def test_in_subcommands(self):
        self.assertEqual(work_plan.SUBCOMMANDS["notes-vcs"], "commands.notes_vcs")

    def test_in_descriptions(self):
        names = [e[0] for e in work_plan.DESCRIPTIONS]
        self.assertIn("notes-vcs", names)


class DispatcherHookTest(unittest.TestCase):
    """_maybe_autocommit_notes: fires only when enabled + notes_root is a root,
    and never raises."""

    def _run_hook(self, sub, parts, *, cfg, is_root, is_under=False, sha="c0ffee"):
        with patch("lib.config.load_config", return_value=cfg), \
             patch("lib.notes_vcs.is_git_root", return_value=is_root), \
             patch("lib.notes_vcs.is_under_git", return_value=is_under), \
             patch("lib.notes_vcs.auto_commit", return_value=sha) as mac:
            err = io.StringIO()
            with redirect_stderr(err):
                work_plan._maybe_autocommit_notes(sub, parts)
            return err.getvalue(), mac

    def test_commits_when_enabled_and_root(self):
        out, mac = self._run_hook("slot", ["slot", "103", "tabletop"],
                                  cfg=_cfg(auto=True), is_root=True)
        mac.assert_called_once()
        self.assertEqual(mac.call_args[0][1], "work-plan slot 103 tabletop")
        self.assertIn("committed c0ffee", out)

    def test_skips_when_disabled(self):
        out, mac = self._run_hook("slot", ["slot", "1", "t"],
                                  cfg=_cfg(auto=False), is_root=True)
        mac.assert_not_called()

    def test_skips_when_no_config_block(self):
        out, mac = self._run_hook("slot", ["slot", "1", "t"],
                                  cfg=_cfg(auto=None), is_root=True)
        mac.assert_not_called()

    def test_nudges_when_enabled_but_not_repo(self):
        out, mac = self._run_hook("slot", ["slot", "1", "t"],
                                  cfg=_cfg(auto=True), is_root=False,
                                  is_under=False)
        mac.assert_not_called()
        self.assertIn("notes-vcs init", out)

    def test_skips_self(self):
        # notes-vcs manages its own repo; the hook must not double-commit.
        with patch("lib.config.load_config") as mload:
            work_plan._maybe_autocommit_notes("notes-vcs", ["notes-vcs", "init"])
            mload.assert_not_called()

    def test_never_raises_on_failure(self):
        with patch("lib.config.load_config", side_effect=RuntimeError("boom")):
            # Must swallow — no exception escapes.
            work_plan._maybe_autocommit_notes("slot", ["slot", "1", "t"])


if __name__ == "__main__":
    unittest.main()
