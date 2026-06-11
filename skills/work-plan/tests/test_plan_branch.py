"""Tests for the plan-branch command (#260 Phase 3). All git + config writes
are mocked — offline, no real repo or yq touched.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_branch as pb


def _cfg(plan_branch=None, local="/tmp/repo", github="o/r", visibility=None):
    entry = {"github": github}
    if local is not None:
        entry["local"] = local
    if plan_branch is not None:
        entry["plan_branch"] = plan_branch
    return {"notes_root": "/tmp/notes", "repos": {"myrepo": entry}}


def _run(args, *, cfg, pw=None, needs=False, valid=True, repo_ok=True,
         set_ok=True):
    """Drive plan_branch.run with the lib + guards mocked. `pw` is a dict of
    plan_worktree function-name → MagicMock/return overrides."""
    pwmod = MagicMock()
    # sensible defaults
    pwmod._branch_exists.return_value = False
    pwmod.local_branch_exists.return_value = True
    pwmod.is_published.return_value = False
    pwmod.unpushed_oneline.return_value = []
    pwmod.fetch_branch.return_value = True
    pwmod.ensure_worktree.return_value = Path("/wt")
    pwmod.create_orphan_worktree.return_value = Path("/wt")
    pwmod.dirty_work_plan_paths.return_value = [".work-plan/README.md"]
    pwmod.commit_shared_tier.return_value = "abc1234"
    pwmod.push_plan_branch.return_value = MagicMock(returncode=0, stderr="")
    # Overrides set each function's return_value (the function stays a MagicMock
    # so call-count assertions still work).
    for k, v in (pw or {}).items():
        getattr(pwmod, k).return_value = v
    with patch("commands.plan_branch.load_config", return_value=cfg), \
         patch("commands.plan_branch.is_valid_git_repo", return_value=repo_ok), \
         patch("commands.plan_branch.seed_readme", return_value=True), \
         patch("commands.plan_branch.needs_confirm", return_value=needs), \
         patch("commands.plan_branch.valid_token", return_value=valid), \
         patch("commands.plan_branch.make_token", return_value="tok123"), \
         patch("commands.plan_branch._set_plan_branch", return_value=set_ok), \
         patch("commands.plan_branch.pw", pwmod):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pb.run(args)
    return rc, buf.getvalue(), pwmod


class UsageTest(unittest.TestCase):
    def test_bad_action_rc2(self):
        rc, out, _ = _run(["frobnicate", "myrepo"], cfg=_cfg())
        self.assertEqual(rc, 2)
        self.assertIn("usage", out)

    def test_no_action_rc2(self):
        rc, out, _ = _run([], cfg=_cfg())
        self.assertEqual(rc, 2)


class ResolveRepoTest(unittest.TestCase):
    def test_unconfigured_repo_errs(self):
        rc, out, _ = _run(["status", "nope"], cfg=_cfg())
        self.assertEqual(rc, 1)
        self.assertIn("not a configured repo", out)

    def test_missing_local_path_errs(self):
        rc, out, _ = _run(["status", "myrepo"], cfg=_cfg(local=None))
        self.assertEqual(rc, 1)
        self.assertIn("no local clone path", out)

    def test_not_a_git_repo_errs(self):
        rc, out, _ = _run(["status", "myrepo"], cfg=_cfg(), repo_ok=False)
        self.assertEqual(rc, 1)
        self.assertIn("not a git repository", out)

    def test_single_repo_inferred_when_arg_omitted(self):
        rc, out, _ = _run(["status"], cfg=_cfg(plan_branch="work-plan/plan"))
        self.assertEqual(rc, 0)

    def test_ambiguous_repo_requires_arg(self):
        cfg = _cfg(plan_branch="x")
        cfg["repos"]["other"] = {"github": "o/o", "local": "/tmp/o"}
        rc, out, _ = _run(["status"], cfg=cfg)
        self.assertEqual(rc, 1)
        self.assertIn("specify which repo", out)


class InitTest(unittest.TestCase):
    def test_create_orphan_when_branch_absent(self):
        rc, out, pwmod = _run(["init", "myrepo"], cfg=_cfg(),
                              pw={"_branch_exists": False})
        self.assertEqual(rc, 0)
        pwmod.create_orphan_worktree.assert_called_once()
        pwmod.commit_shared_tier.assert_called_once()
        pwmod.ensure_worktree.assert_not_called()
        self.assertIn("Created orphan branch 'work-plan/plan'", out)
        self.assertIn("Recorded plan_branch", out)

    def test_connect_when_branch_exists(self):
        rc, out, pwmod = _run(["init", "myrepo"], cfg=_cfg(),
                              pw={"_branch_exists": True})
        self.assertEqual(rc, 0)
        pwmod.ensure_worktree.assert_called_once()
        pwmod.create_orphan_worktree.assert_not_called()
        self.assertIn("Connected", out)

    def test_custom_branch_name(self):
        rc, out, pwmod = _run(["init", "myrepo", "--branch=wp/custom"],
                              cfg=_cfg(), pw={"_branch_exists": False})
        self.assertEqual(rc, 0)
        self.assertIn("wp/custom", out)

    def test_invalid_branch_rc2(self):
        for bad in ["--branch=-evil", "--branch=a..b", "--branch=/lead",
                    "--branch=trail/", "--branch=a//b"]:
            rc, out, _ = _run(["init", "myrepo", bad], cfg=_cfg())
            self.assertEqual(rc, 2, bad)
            self.assertIn("not a valid branch", out)

    def test_refuses_switching_existing_plan_branch(self):
        rc, out, _ = _run(["init", "myrepo", "--branch=work-plan/other"],
                          cfg=_cfg(plan_branch="work-plan/plan"))
        self.assertEqual(rc, 1)
        self.assertIn("already has plan_branch", out)

    def test_commit_failure_errs(self):
        rc, out, _ = _run(["init", "myrepo"], cfg=_cfg(),
                          pw={"_branch_exists": False, "commit_shared_tier": None})
        self.assertEqual(rc, 1)
        self.assertIn("initial commit failed", out)

    def test_orphan_creation_failure_errs(self):
        rc, out, _ = _run(["init", "myrepo"], cfg=_cfg(),
                          pw={"_branch_exists": False,
                              "create_orphan_worktree": None})
        self.assertEqual(rc, 1)
        self.assertIn("could not create the plan worktree", out)

    def test_public_repo_push_warning_shown(self):
        rc, out, _ = _run(["init", "myrepo"], cfg=_cfg(),
                          pw={"_branch_exists": False}, needs=True)
        self.assertEqual(rc, 0)
        self.assertIn("public", out.lower())


class StatusTest(unittest.TestCase):
    def test_no_plan_branch(self):
        rc, out, _ = _run(["status", "myrepo"], cfg=_cfg())
        self.assertEqual(rc, 0)
        self.assertIn("no plan_branch configured", out)

    def test_no_plan_branch_json(self):
        rc, out, _ = _run(["status", "myrepo", "--json"], cfg=_cfg())
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["configured"], False)

    def test_published_with_unpushed(self):
        rc, out, _ = _run(["status", "myrepo"], cfg=_cfg(plan_branch="work-plan/plan"),
                          pw={"is_published": True,
                              "unpushed_oneline": ["a1 one", "b2 two"]})
        self.assertEqual(rc, 0)
        self.assertIn("on origin", out)
        self.assertIn("2 commit(s)", out)

    def test_local_only_json_shape(self):
        rc, out, _ = _run(["status", "myrepo", "--json"],
                          cfg=_cfg(plan_branch="work-plan/plan"),
                          pw={"is_published": False, "local_branch_exists": True,
                              "unpushed_oneline": ["a1 x"]})
        d = json.loads(out)
        self.assertEqual(d["plan_branch"], "work-plan/plan")
        self.assertTrue(d["configured"])
        self.assertFalse(d["published"])
        self.assertEqual(d["unpushed_count"], 1)


class PushTest(unittest.TestCase):
    def test_no_plan_branch_errs(self):
        rc, out, _ = _run(["push", "myrepo"], cfg=_cfg())
        self.assertEqual(rc, 1)
        self.assertIn("no plan_branch", out)

    def test_local_branch_missing_errs(self):
        rc, out, _ = _run(["push", "myrepo"], cfg=_cfg(plan_branch="work-plan/plan"),
                          pw={"local_branch_exists": False})
        self.assertEqual(rc, 1)
        self.assertIn("doesn't exist locally", out)

    def test_nothing_to_push(self):
        rc, out, pwmod = _run(["push", "myrepo"],
                             cfg=_cfg(plan_branch="work-plan/plan"),
                             pw={"unpushed_oneline": []})
        self.assertEqual(rc, 0)
        self.assertIn("Nothing to push", out)
        pwmod.push_plan_branch.assert_not_called()

    def test_dry_run_lists_without_pushing(self):
        rc, out, pwmod = _run(["push", "myrepo", "--dry-run"],
                             cfg=_cfg(plan_branch="work-plan/plan"),
                             pw={"unpushed_oneline": ["a1 one", "b2 two"]})
        self.assertEqual(rc, 0)
        self.assertIn("Would push 2 commit(s)", out)
        pwmod.push_plan_branch.assert_not_called()

    def test_public_repo_blocks_without_confirm(self):
        rc, out, pwmod = _run(["push", "myrepo"],
                             cfg=_cfg(plan_branch="work-plan/plan"),
                             pw={"unpushed_oneline": ["a1 x"]},
                             needs=True, valid=False)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_confirm"])
        self.assertEqual(d["token"], "tok123")
        self.assertIn("visible to anyone on the internet", d["reason"])
        pwmod.push_plan_branch.assert_not_called()

    def test_public_repo_pushes_with_valid_confirm(self):
        rc, out, pwmod = _run(["push", "myrepo", "--confirm=tok123"],
                             cfg=_cfg(plan_branch="work-plan/plan"),
                             pw={"unpushed_oneline": ["a1 x"]},
                             needs=True, valid=True)
        self.assertEqual(rc, 0)
        pwmod.push_plan_branch.assert_called_once()
        self.assertIn("Pushed", out)

    def test_private_repo_pushes_without_gate(self):
        rc, out, pwmod = _run(["push", "myrepo"],
                             cfg=_cfg(plan_branch="work-plan/plan"),
                             pw={"unpushed_oneline": ["a1 x"]}, needs=False)
        self.assertEqual(rc, 0)
        pwmod.push_plan_branch.assert_called_once()

    def test_protected_branch_failure_actionable(self):
        proc = MagicMock(returncode=1, stderr="remote: protected branch hook declined")
        rc, out, _ = _run(["push", "myrepo"],
                          cfg=_cfg(plan_branch="work-plan/plan"),
                          pw={"unpushed_oneline": ["a1 x"],
                              "push_plan_branch": proc}, needs=False)
        self.assertEqual(rc, 1)
        self.assertIn("protected", out.lower())
        self.assertIn("work-plan/**", out)

    def test_generic_push_failure(self):
        proc = MagicMock(returncode=1, stderr="fatal: unable to access")
        rc, out, _ = _run(["push", "myrepo"],
                          cfg=_cfg(plan_branch="work-plan/plan"),
                          pw={"unpushed_oneline": ["a1 x"],
                              "push_plan_branch": proc}, needs=False)
        self.assertEqual(rc, 1)
        self.assertIn("push failed", out)


if __name__ == "__main__":
    unittest.main()
