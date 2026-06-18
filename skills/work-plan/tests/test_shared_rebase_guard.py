"""Tests for the shared-tier rebase guard (#241 phase 2).

Covers:
- plan_worktree.rebase_onto_origin: clean rebase / nothing-to-do → True;
  unpublished branch (no upstream) → True; conflict → abort + False;
  git unavailable → False.
- membership_guard.shared_rebase_guard: private track → no-op; legacy shared
  (no plan_branch) → no-op; shared + plan_branch clean rebase → ok; divergence →
  (False, reason).
- slot integration: a shared track whose rebase diverges emits {needs_rebase}
  and does NOT write.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import plan_worktree
from lib.membership_guard import shared_rebase_guard


def _git_stub(*, rebase_rc=0, remote_exists=True, rebase_none=False):
    """Build a fake plan_worktree._git dispatching on the git subcommand."""
    calls = []

    def _git(cwd, *args, **kw):
        calls.append(tuple(args))
        head = args[0]
        if head == "fetch":
            return MagicMock(returncode=0, stdout="", stderr="")
        if head == "rev-parse":
            # remote_branch_exists → refs/remotes/origin/<branch>
            rc = 0 if remote_exists else 1
            return MagicMock(returncode=rc, stdout="", stderr="")
        if head == "rebase" and args[-1] != "--abort":
            if rebase_none:
                return None
            return MagicMock(returncode=rebase_rc, stdout="", stderr="conflict")
        if args == ("rebase", "--abort"):
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    return _git, calls


class RebaseOntoOriginTest(unittest.TestCase):

    def test_clean_rebase_returns_true_with_autostash(self):
        gitfn, calls = _git_stub(rebase_rc=0, remote_exists=True)
        with patch("lib.plan_worktree._git", side_effect=gitfn):
            self.assertTrue(plan_worktree.rebase_onto_origin(Path("/wt"), "work-plan/plan"))
        # --autostash so a dirty .work-plan/ (the normal write-then-commit flow)
        # doesn't make the rebase refuse with a spurious needs_rebase.
        self.assertIn(("rebase", "--autostash", "origin/work-plan/plan"), calls)
        self.assertNotIn(("rebase", "--abort"), calls)

    def test_unpublished_branch_returns_true_without_rebasing(self):
        gitfn, calls = _git_stub(remote_exists=False)
        with patch("lib.plan_worktree._git", side_effect=gitfn):
            self.assertTrue(plan_worktree.rebase_onto_origin(Path("/wt"), "work-plan/plan"))
        self.assertNotIn(("rebase", "--autostash", "origin/work-plan/plan"), calls)

    def test_conflict_aborts_and_returns_false(self):
        gitfn, calls = _git_stub(rebase_rc=1, remote_exists=True)
        with patch("lib.plan_worktree._git", side_effect=gitfn):
            self.assertFalse(plan_worktree.rebase_onto_origin(Path("/wt"), "work-plan/plan"))
        # Conflict must leave the worktree clean.
        self.assertIn(("rebase", "--abort"), calls)

    def test_git_unavailable_returns_false(self):
        gitfn, calls = _git_stub(rebase_none=True, remote_exists=True)
        with patch("lib.plan_worktree._git", side_effect=gitfn):
            self.assertFalse(plan_worktree.rebase_onto_origin(Path("/wt"), "work-plan/plan"))


class SharedRebaseGuardTest(unittest.TestCase):

    CFG = {"repos": {"ok": {"github": "ok/repo", "local": "/repo",
                            "plan_branch": "work-plan/plan"}}}

    def _track(self, *, tier="shared", folder="ok", repo="ok/repo"):
        return SimpleNamespace(name="alpha", tier=tier, folder=folder, repo=repo,
                               path=Path("/wt/.work-plan/alpha.md"))

    def test_private_track_is_noop(self):
        ok, reason = shared_rebase_guard(self._track(tier="private"), self.CFG)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_legacy_shared_no_plan_branch_is_noop(self):
        cfg = {"repos": {"ok": {"github": "ok/repo", "local": "/repo"}}}  # no plan_branch
        ok, reason = shared_rebase_guard(self._track(), cfg)
        self.assertTrue(ok)

    def test_shared_clean_rebase_ok(self):
        with patch("lib.plan_worktree.ensure_worktree", return_value=Path("/wt")), \
             patch("lib.plan_worktree.rebase_onto_origin", return_value=True):
            ok, reason = shared_rebase_guard(self._track(), self.CFG)
        self.assertTrue(ok)

    def test_shared_divergence_blocks(self):
        with patch("lib.plan_worktree.ensure_worktree", return_value=Path("/wt")), \
             patch("lib.plan_worktree.rebase_onto_origin", return_value=False):
            ok, reason = shared_rebase_guard(self._track(), self.CFG)
        self.assertFalse(ok)
        self.assertIn("diverged", reason)

    def test_worktree_unavailable_degrades_to_proceed(self):
        with patch("lib.plan_worktree.ensure_worktree", return_value=None):
            ok, reason = shared_rebase_guard(self._track(), self.CFG)
        self.assertTrue(ok)


class SlotNeedsRebaseTest(unittest.TestCase):

    def test_slot_aborts_with_needs_rebase_json_no_write(self):
        from commands import slot
        track = SimpleNamespace(
            name="alpha", tier="shared", folder="ok", repo="ok/repo",
            path=Path("/wt/.work-plan/alpha.md"), body="# x",
            meta={"track": "alpha", "status": "active",
                  "github": {"repo": "ok/repo", "issues": []}},
            has_frontmatter=True,
        )
        cfg = {"notes_root": "/tmp/n",
               "repos": {"ok": {"github": "ok/repo", "local": "/repo",
                                "plan_branch": "work-plan/plan"}}}
        gh_proc = MagicMock(returncode=0, stdout="{}", stderr="")
        with patch("commands.slot.load_config", return_value=cfg), \
             patch("commands.slot.discover_tracks", return_value=[track]), \
             patch("commands.slot.subprocess.run", return_value=gh_proc), \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("lib.plan_worktree.ensure_worktree", return_value=Path("/wt")), \
             patch("lib.plan_worktree.rebase_onto_origin", return_value=False), \
             patch("lib.membership_guard.write_file") as mw:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = slot.run(["30", "alpha"])
        self.assertEqual(rc, 0)
        mw.assert_not_called()  # divergence → no write
        data = json.loads(buf.getvalue().strip())
        self.assertTrue(data["needs_rebase"])
        self.assertEqual(data["track"], "alpha")


if __name__ == "__main__":
    unittest.main()
