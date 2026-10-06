"""Preflight diagnostics (#427): every dependency failure names one specific
check and a remediation, results stay well-formed when subprocesses misbehave,
and nothing here touches the real machine (all seams are injected)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import preflight
from lib.preflight import (
    FAIL, OK, SKIP, WARN, check_config, check_git, check_gh, check_notes_root,
    check_plan_worktrees, check_python, check_yq, overall_status, run_preflight,
)


def proc(out="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr="")


def which_for(**paths):
    return lambda name: paths.get(name)


class FakeRunner:
    """Answers by command; records every call; can time out or raise."""
    def __init__(self, answers=None, raises=None):
        self.answers = answers or {}
        self.raises = raises or {}
        self.calls = []

    def __call__(self, cmd, input=None, capture_output=True, text=True, timeout=None):
        self.calls.append(list(cmd))
        key = tuple(cmd)
        if key in self.raises:
            raise self.raises[key]
        return self.answers.get(key, proc())


YQ_OK = {
    ("yq", "-o=json", "."): proc('{"work_plan_probe": 1}'),
    ("yq", "-P", "."): proc("work_plan_probe: 1\n"),
}
SIGNED_IN = lambda: {"gh_present": True, "authenticated": True, "probe_ok": True, "user": "eve", "error": None}


def by_id(results, id_):
    return next(r for r in results if r["id"] == id_)


class PythonTest(unittest.TestCase):
    def test_supported_versions_pass(self):
        for v in ((3, 9, 0), (3, 12, 4), (3, 14, 1)):
            self.assertEqual(check_python(v)["status"], OK, v)

    def test_old_python_is_blocking_with_a_fix(self):
        for v in ((3, 8, 18), (2, 7, 18)):
            r = check_python(v)
            self.assertEqual(r["status"], FAIL)
            self.assertIn("older than the required 3.9", r["message"])
            self.assertIn("python.org", r["remediation"])


class GitTest(unittest.TestCase):
    def test_ok(self):
        r = check_git(which_for(git="/usr/bin/git"), FakeRunner({("git", "--version"): proc("git version 2.40.0\n")}), False)
        self.assertEqual((r["id"], r["status"], r["message"]), ("git", OK, "git version 2.40.0"))

    def test_missing(self):
        r = check_git(which_for(), FakeRunner(), False)
        self.assertEqual(r["status"], FAIL)
        self.assertIn("not found on PATH", r["message"])
        self.assertIn("git-scm.com", r["remediation"])

    def test_timeout_is_a_warning_not_a_hang_or_exception(self):
        runner = FakeRunner(raises={("git", "--version"): subprocess.TimeoutExpired("git", 5)})
        r = check_git(which_for(git="/usr/bin/git"), runner, False)
        self.assertEqual(r["status"], WARN)
        self.assertIn("did not respond", r["message"])

    def test_nonzero_exit_fails(self):
        r = check_git(which_for(git="/usr/bin/git"), FakeRunner({("git", "--version"): proc("", 1)}), False)
        self.assertEqual(r["status"], FAIL)

    def test_empty_output_does_not_crash(self):
        r = check_git(which_for(git="/usr/bin/git"), FakeRunner({("git", "--version"): proc("")}), False)
        self.assertEqual(r["status"], OK)

    def test_spawn_oserror_is_a_failure_result(self):
        runner = FakeRunner(raises={("git", "--version"): OSError("exec format error")})
        r = check_git(which_for(git="/usr/bin/git"), runner, False)
        self.assertEqual(r["status"], FAIL)
        self.assertIn("exec format error", r["message"])


class WslPathMismatchTest(unittest.TestCase):
    def test_windows_binary_under_wsl_warns(self):
        for tool, path in (("git", "/mnt/c/Program Files/Git/cmd/git.exe"),
                           ("gh", "/mnt/c/Program Files/GitHub CLI/gh.exe")):
            r = preflight._tool_presence(tool, which_for(**{tool: path}), True)[1]
            self.assertEqual(r["status"], WARN, tool)
            self.assertIn("Windows binary under WSL", r["message"])
            self.assertIn("Linux build", r["remediation"])

    def test_same_path_outside_wsl_is_fine(self):
        self.assertIsNone(preflight._tool_presence("git", which_for(git="/mnt/c/x/git.exe"), False)[1])

    def test_linux_binary_under_wsl_is_fine(self):
        self.assertIsNone(preflight._tool_presence("git", which_for(git="/usr/bin/git"), True)[1])

    def test_windows_style_backslash_paths_are_handled_without_crashing(self):
        # A native-Windows resolution is not a WSL mismatch, and must not raise.
        for path in (r"C:\Program Files\Git\cmd\git.exe", r"\\mnt\\c\\x\\git.exe"):
            self.assertIsNone(preflight._tool_presence("git", which_for(git=path), False)[1])
        self.assertTrue(preflight._windows_binary_under_wsl(r"/mnt/c/Tools\gh.exe", True))

    def test_is_wsl_reads_proc_version(self):
        with mock.patch.object(Path, "read_text", return_value="Linux version 5.15 (Microsoft@Microsoft.com)"):
            self.assertTrue(preflight.is_wsl())
        with mock.patch.object(Path, "read_text", return_value="Linux version 6.1 (debian)"):
            self.assertFalse(preflight.is_wsl())
        with mock.patch.object(Path, "read_text", side_effect=OSError):
            self.assertFalse(preflight.is_wsl())


class GhTest(unittest.TestCase):
    def test_missing_gh_skips_auth_and_names_the_install(self):
        out = check_gh(which_for(), False, SIGNED_IN)
        self.assertEqual([r["id"] for r in out], ["gh", "gh-auth"])
        self.assertEqual(out[0]["status"], FAIL)
        self.assertIn("cli.github.com", out[0]["remediation"])
        self.assertEqual(out[1]["status"], SKIP)

    def test_signed_in(self):
        out = check_gh(which_for(gh="/usr/bin/gh"), False, SIGNED_IN)
        self.assertEqual([r["status"] for r in out], [OK, OK])
        self.assertIn("as eve", out[1]["message"])

    def test_signed_out_is_blocking_with_the_login_command(self):
        out = check_gh(which_for(gh="/usr/bin/gh"), False,
                       lambda: {"gh_present": True, "authenticated": False, "probe_ok": True, "user": None})
        self.assertEqual(out[1]["status"], FAIL)
        self.assertEqual(out[1]["remediation"], "Run: gh auth login")

    def test_unverifiable_probe_is_a_warning_never_a_logout(self):
        # #485: a network blip must not read as "signed out".
        out = check_gh(which_for(gh="/usr/bin/gh"), False,
                       lambda: {"gh_present": True, "authenticated": False, "probe_ok": False, "error": "timeout"})
        self.assertEqual(out[1]["status"], WARN)
        self.assertNotIn("gh auth login", out[1]["remediation"])

    def test_a_raising_probe_becomes_a_warning(self):
        def boom():
            raise RuntimeError("network down")
        out = check_gh(which_for(gh="/usr/bin/gh"), False, boom)
        self.assertEqual(out[1]["status"], WARN)
        self.assertIn("network down", out[1]["message"])


class YqTest(unittest.TestCase):
    def test_correct_yq(self):
        out = check_yq(which_for(yq="/usr/bin/yq"), FakeRunner(YQ_OK), False)
        self.assertEqual([(r["id"], r["status"]) for r in out], [("yq", OK), ("yq-implementation", OK)])

    def test_missing_yq_is_distinct_from_wrong_yq(self):
        missing = check_yq(which_for(), FakeRunner(), False)
        wrong = check_yq(which_for(yq="/usr/bin/yq"), FakeRunner({("yq", "-o=json", "."): proc("", 2)}), False)
        self.assertEqual((missing[0]["id"], missing[0]["status"]), ("yq", FAIL))
        self.assertEqual(missing[1]["status"], SKIP)
        self.assertEqual((wrong[0]["id"], wrong[0]["status"]), ("yq", OK))      # present...
        self.assertEqual((wrong[1]["id"], wrong[1]["status"]), ("yq-implementation", FAIL))  # ...but wrong
        self.assertNotEqual(missing[0]["message"], wrong[1]["message"])
        self.assertIn("not kislyuk/yq", wrong[1]["remediation"])

    def test_malformed_json_output_means_wrong_implementation(self):
        out = check_yq(which_for(yq="/usr/bin/yq"),
                       FakeRunner({("yq", "-o=json", "."): proc("not json at all")}), False)
        self.assertEqual(out[1]["status"], FAIL)

    def test_json_with_the_wrong_content_means_wrong_implementation(self):
        out = check_yq(which_for(yq="/usr/bin/yq"),
                       FakeRunner({("yq", "-o=json", "."): proc('{"something": "else"}')}), False)
        self.assertEqual(out[1]["status"], FAIL)

    def test_pretty_print_failure_means_wrong_implementation(self):
        answers = dict(YQ_OK)
        answers[("yq", "-P", ".")] = proc("", 1)
        out = check_yq(which_for(yq="/usr/bin/yq"), FakeRunner(answers), False)
        self.assertEqual(out[1]["status"], FAIL)
        self.assertIn("-P", out[1]["message"])

    def test_timeout_is_a_warning(self):
        runner = FakeRunner(raises={("yq", "-o=json", "."): subprocess.TimeoutExpired("yq", 5)})
        out = check_yq(which_for(yq="/usr/bin/yq"), runner, False)
        self.assertEqual(out[1]["status"], WARN)

    def test_windows_yq_under_wsl_warns_but_is_still_probed(self):
        out = check_yq(which_for(yq="/mnt/c/Tools/yq.exe"), FakeRunner(YQ_OK), True)
        self.assertEqual([(r["id"], r["status"]) for r in out], [("yq", WARN), ("yq-implementation", OK)])


class ConfigAndNotesTest(unittest.TestCase):
    def test_config_loads(self):
        r, cfg = check_config(lambda: {"notes_root": "/x"}, True)
        self.assertEqual(r["status"], OK)
        self.assertEqual(cfg, {"notes_root": "/x"})

    def test_config_failure_is_blocking_with_the_reason(self):
        def bad():
            raise ValueError("bad yaml on line 3")
        r, cfg = check_config(bad, True)
        self.assertEqual(r["status"], FAIL)
        self.assertIn("bad yaml on line 3", r["message"])
        self.assertIsNone(cfg)

    def test_config_is_skipped_not_failed_when_yq_is_unusable(self):
        called = []
        r, cfg = check_config(lambda: called.append(1), False)
        self.assertEqual(r["status"], SKIP)
        self.assertEqual(called, [])

    def test_notes_root_access(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(check_notes_root({"notes_root": d})["status"], OK)

    def test_notes_root_unreadable_is_blocking_and_readonly_is_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("lib.preflight.os.access", return_value=False):
                self.assertEqual(check_notes_root({"notes_root": d})["status"], FAIL)
            with mock.patch("lib.preflight.os.access", side_effect=lambda p, m: m != preflight.os.W_OK):
                self.assertEqual(check_notes_root({"notes_root": d})["status"], WARN)

    def test_missing_or_malformed_notes_root_is_skipped_to_avoid_a_duplicate_report(self):
        for cfg in (None, {}, {"notes_root": ""}, {"notes_root": 5}, {"notes_root": "/definitely/not/here"}):
            self.assertEqual(check_notes_root(cfg)["status"], SKIP, cfg)

    def test_windows_style_notes_root_does_not_crash(self):
        self.assertEqual(check_notes_root({"notes_root": r"C:\Users\eve\Notes"})["status"], SKIP)


class PlanWorktreeTest(unittest.TestCase):
    """#427/#260: read-only health of each configured plan_branch worktree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.local = self.root / "clone"
        self.local.mkdir()
        self.wt = self.root / "wt"
        self.calls = []

    def cfg(self, **entry):
        base = {"github": "o/r", "local": str(self.local), "plan_branch": "work-plan/plan"}
        base.update(entry)
        return {"repos": {"myrepo": base}}

    def make_git(self, *, head="work-plan/plan", head_rc=0, markers=()):
        def git(cwd, *args, timeout=None):
            self.calls.append(args)
            if args[:3] == ("rev-parse", "--abbrev-ref", "HEAD"):
                return None if head is None else proc(head + "\n", head_rc)
            if args[:2] == ("rev-parse", "--git-path"):
                name = args[2]
                return proc(str(self.root / "gitdir" / name) + "\n")
            raise AssertionError(f"unexpected git call {args}")
        for m in markers:
            (self.root / "gitdir").mkdir(exist_ok=True)
            (self.root / "gitdir" / m).mkdir(exist_ok=True)
        return git

    def run_check(self, cfg=None, *, git=None, exists=True, create_wt=False):
        if create_wt:
            self.wt.mkdir(exist_ok=True)
            (self.wt / ".git").write_text("gitdir: elsewhere\n")
        return check_plan_worktrees(
            cfg if cfg is not None else self.cfg(),
            git=git or self.make_git(), worktree_dir=lambda p: self.wt,
            branch_exists=lambda p, b: exists)

    def one(self, **kw):
        out = self.run_check(**kw)
        self.assertEqual(len(out), 1, out)
        return out[0]

    def test_healthy_worktree_on_the_plan_branch(self):
        r = self.one(create_wt=True)
        self.assertEqual((r["id"], r["status"]), ("plan-worktree:myrepo", OK))

    def test_not_created_yet_is_healthy_because_it_is_made_on_first_use(self):
        r = self.one()
        self.assertEqual(r["status"], OK)
        self.assertIn("created on first use", r["message"])

    def test_missing_plan_branch_warns_with_both_fixes(self):
        r = self.one(exists=False)
        self.assertEqual(r["status"], WARN)
        self.assertIn("not found locally or on origin", r["message"])
        self.assertIn("plan-branch init myrepo", r["remediation"])
        self.assertIn("fetch origin work-plan/plan", r["remediation"])

    def test_worktree_on_the_wrong_branch_warns(self):
        r = self.one(create_wt=True, git=self.make_git(head="feature/x"))
        self.assertEqual(r["status"], WARN)
        self.assertIn("is on 'feature/x', not 'work-plan/plan'", r["message"])
        self.assertIn("checkout work-plan/plan", r["remediation"])

    def test_unreadable_worktree_warns(self):
        for git in (self.make_git(head_rc=128), self.make_git(head=None)):
            r = self.one(create_wt=True, git=git)
            self.assertEqual(r["status"], WARN)
            self.assertIn("could not read the plan worktree", r["message"])

    def test_stale_non_worktree_directory_warns(self):
        self.wt.mkdir()
        (self.wt / "junk.txt").write_text("x")
        r = self.one()
        self.assertEqual(r["status"], WARN)
        self.assertIn("not a git worktree", r["message"])
        self.assertIn("git -C", r["remediation"])
        self.assertIn("worktree prune", r["remediation"])

    def test_empty_leftover_directory_is_not_a_problem(self):
        self.wt.mkdir()
        self.assertEqual(self.one()["status"], OK)

    def test_mid_rebase_and_mid_merge_are_reported_distinctly(self):
        for marker, word, abort in (("rebase-merge", "rebase", "rebase --abort"),
                                    ("rebase-apply", "rebase", "rebase --abort"),
                                    ("MERGE_HEAD", "merge", "merge --abort")):
            with self.subTest(marker=marker):
                shutil.rmtree(self.root / "gitdir", ignore_errors=True)  # one marker at a time
                r = self.one(create_wt=True, git=self.make_git(markers=[marker]))
                self.assertEqual(r["status"], WARN)
                self.assertIn(f"stuck in a {word}", r["message"])
                self.assertIn(abort, r["remediation"])

    def test_one_result_per_repo_that_declares_a_plan_branch(self):
        cfg = {"repos": {
            "a": {"local": str(self.local), "plan_branch": "p"},
            "b": {"local": str(self.local)},                     # no plan_branch → no result
            "c": "scalar-shorthand",                             # malformed entry → ignored
            "d": {"local": str(self.local), "plan_branch": "q"},
        }}
        out = self.run_check(cfg)
        self.assertEqual([r["id"] for r in out], ["plan-worktree:a", "plan-worktree:d"])

    def test_missing_local_clone_is_skipped_not_failed(self):
        for entry in ({"plan_branch": "p"}, {"plan_branch": "p", "local": None},
                      {"plan_branch": "p", "local": str(self.root / "nowhere")},
                      {"plan_branch": "p", "local": r"C:\Users\eve\clone"}):
            r = self.one(cfg={"repos": {"r": entry}})
            self.assertEqual(r["status"], SKIP, entry)

    def test_no_repos_or_no_config_yields_nothing(self):
        for cfg in (None, {}, {"repos": None}, {"repos": []}, {"repos": {}}):
            self.assertEqual(
                check_plan_worktrees(cfg, git=self.make_git(), worktree_dir=lambda p: self.wt,
                                     branch_exists=lambda p, b: True), [])

    def test_an_unexpected_error_becomes_a_warning_not_an_exception(self):
        def boom(*a, **k):
            raise RuntimeError("disk on fire")
        out = check_plan_worktrees(self.cfg(), git=self.make_git(), worktree_dir=boom,
                                   branch_exists=lambda p, b: True)
        self.assertEqual(out[0]["status"], WARN)
        self.assertIn("disk on fire", out[0]["message"])

    def test_never_creates_the_worktree_or_runs_a_write_command(self):
        self.run_check(create_wt=True)
        self.assertFalse(self.root.joinpath("gitdir").exists())
        self.assertTrue(all(a[0] == "rev-parse" for a in self.calls), self.calls)
        self.assertFalse((self.wt / "new-file").exists())


class RunPreflightTest(unittest.TestCase):
    def _run(self, **kw):
        base = dict(which=which_for(git="/usr/bin/git", gh="/usr/bin/gh", yq="/usr/bin/yq"),
                    runner=FakeRunner({**YQ_OK, ("git", "--version"): proc("git version 2.40\n")}),
                    version_info=(3, 12, 1), wsl=False, auth_fn=SIGNED_IN,
                    load_config_fn=lambda: {"notes_root": tempfile.gettempdir()}, version="2026.10.05+abc")
        base.update(kw)
        return run_preflight(**base)

    def test_healthy_machine(self):
        out = self._run()
        self.assertEqual([r["id"] for r in out],
                         ["python", "launcher", "git", "gh", "gh-auth", "yq", "yq-implementation", "config", "notes-root"])
        self.assertTrue(all(r["status"] == OK for r in out), [r for r in out if r["status"] != OK])
        self.assertEqual(overall_status(out), "healthy")

    def test_every_result_has_the_documented_shape_and_is_json_serialisable(self):
        for out in (self._run(), self._run(which=which_for(), version_info=(3, 8, 0))):
            blob = json.loads(json.dumps(out))
            for r in blob:
                self.assertEqual(set(r), {"id", "status", "message", "remediation"})
                self.assertIn(r["status"], {OK, WARN, FAIL, SKIP})
                self.assertTrue(r["message"])

    def test_a_bare_machine_gives_one_specific_failure_per_missing_tool(self):
        out = self._run(which=which_for())
        failed = sorted(r["id"] for r in out if r["status"] == FAIL)
        self.assertEqual(failed, ["gh", "git", "yq"])
        self.assertTrue(all(r["remediation"] for r in out if r["status"] == FAIL))
        self.assertEqual(by_id(out, "config")["status"], SKIP)
        self.assertEqual(overall_status(out), "blocking")

    def test_wrong_yq_blocks_config_loading_as_a_skip_not_a_second_failure(self):
        runner = FakeRunner({("yq", "-o=json", "."): proc("garbage"), ("git", "--version"): proc("git version 2\n")})
        out = self._run(runner=runner)
        self.assertEqual(by_id(out, "yq-implementation")["status"], FAIL)
        self.assertEqual(by_id(out, "config")["status"], SKIP)

    def test_old_python_alone_is_blocking(self):
        out = self._run(version_info=(3, 8, 0))
        self.assertEqual([r["id"] for r in out if r["status"] == FAIL], ["python"])
        self.assertEqual(overall_status(out), "blocking")

    def test_missing_version_file_is_only_a_warning(self):
        out = self._run(version=None)
        self.assertEqual(by_id(out, "launcher")["status"], WARN)
        self.assertEqual(overall_status(out), "warning")

    def test_plan_worktree_checks_join_the_run_when_a_repo_declares_one(self):
        cfg = {"notes_root": tempfile.gettempdir(),
               "repos": {"r": {"local": tempfile.gettempdir(), "plan_branch": "p"}}}
        with mock.patch("lib.plan_worktree._branch_exists", return_value=False):
            out = self._run(load_config_fn=lambda: cfg)
        self.assertEqual(out[-1]["id"], "plan-worktree:r")
        self.assertEqual(out[-1]["status"], WARN)
        self.assertEqual(overall_status(out), "warning")

    def test_only_expected_read_only_commands_run(self):
        runner = FakeRunner({**YQ_OK, ("git", "--version"): proc("git version 2\n")})
        self._run(runner=runner)
        self.assertEqual(sorted(map(tuple, runner.calls)),
                         sorted([("git", "--version"), ("yq", "-o=json", "."), ("yq", "-P", ".")]))


class OverallStatusTest(unittest.TestCase):
    def test_precedence(self):
        ok, warn, fail, skip = (dict(id="a", status=s, message="m", remediation=None) for s in (OK, WARN, FAIL, SKIP))
        self.assertEqual(overall_status([ok, skip]), "healthy")
        self.assertEqual(overall_status([ok, warn]), "warning")
        self.assertEqual(overall_status([ok], findings_count=2), "warning")
        self.assertEqual(overall_status([warn, fail], findings_count=2), "blocking")
        self.assertEqual(overall_status([]), "healthy")


if __name__ == "__main__":
    unittest.main()
