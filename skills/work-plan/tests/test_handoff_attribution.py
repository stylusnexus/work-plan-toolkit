"""Tests for handoff commit-attribution helpers: path-glob attribution
(`github.paths`) and the repo-wide commit counter that drives the soft
'silence is expected' signal.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from datetime import datetime

from commands import handoff


def _track(meta_github, local_path="/tmp/repo"):
    return SimpleNamespace(
        meta={"github": meta_github},
        local_path=local_path,
    )


def _proc(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr="")


SINCE = datetime(2026, 4, 29, 0, 0, 0)


class RecentCommitsPathGlobsTest(unittest.TestCase):
    def test_path_glob_attributes_commit_with_no_issue_ref(self):
        """A commit whose subject doesn't mention any tracked issue but
        whose changed paths match `github.paths` should be attributed."""
        log_output = (
            "---COMMIT---\nabc1234|fix(useToast): debounce stacking|2026-04-30T10:00:00+00:00\n"
            "apps/web/src/hooks/useToast.tsx\napps/web/src/hooks/useToast.test.tsx\n\n"
            "---COMMIT---\ndef5678|chore: bump deps|2026-04-30T09:00:00+00:00\n"
            "package.json\n"
        )
        track = _track({
            "issues": [4148, 4149],
            "paths": ["apps/web/src/hooks/useToast*"],
        })
        with mock.patch("commands.handoff.subprocess.run",
                        return_value=_proc(stdout=log_output)):
            commits = handoff._recent_commits(track, SINCE)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["sha"], "abc1234")

    def test_issue_ref_still_attributes_when_paths_set(self):
        """Issue-ref attribution and path attribution are an OR, not AND."""
        log_output = (
            "---COMMIT---\nabc1234|fix #4148: tighten guardrails|2026-04-30T10:00:00+00:00\n"
            "infra/iam/policy.tf\n"
        )
        track = _track({
            "issues": [4148],
            "paths": ["apps/web/src/hooks/useToast*"],
        })
        with mock.patch("commands.handoff.subprocess.run",
                        return_value=_proc(stdout=log_output)):
            commits = handoff._recent_commits(track, SINCE)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["sha"], "abc1234")

    def test_no_paths_no_issues_returns_empty(self):
        """A track with neither tracked issues nor path globs gets nothing."""
        track = _track({"issues": [], "paths": []})
        with mock.patch("commands.handoff.subprocess.run") as run:
            commits = handoff._recent_commits(track, SINCE)
            run.assert_not_called()
        self.assertEqual(commits, [])

    def test_explicit_branches_skip_path_globs(self):
        """When `github.branches` is set, paths do not apply (explicit
        branches are the contract)."""
        log_output = "abc1234|merge: feature work|2026-04-30T10:00:00+00:00"
        track = _track({
            "issues": [4148],
            "branches": ["feature/x"],
            "paths": ["should-not-apply/**"],
        })
        with mock.patch("commands.handoff.subprocess.run",
                        return_value=_proc(stdout=log_output)) as run:
            commits = handoff._recent_commits(track, SINCE)
            args = run.call_args.args[0]
            self.assertIn("feature/x", args)
            self.assertNotIn("--name-only", args)
        self.assertEqual(len(commits), 1)


class RepoCommitsSinceTest(unittest.TestCase):
    def test_counts_lines_in_log_output(self):
        out = "sha1\nsha2\nsha3\n"
        with mock.patch("commands.handoff.subprocess.run",
                        return_value=_proc(stdout=out)):
            n = handoff._repo_commits_since(Path("/tmp/repo"), SINCE)
        self.assertEqual(n, 3)

    def test_returns_zero_on_empty(self):
        with mock.patch("commands.handoff.subprocess.run",
                        return_value=_proc(stdout="")):
            n = handoff._repo_commits_since(Path("/tmp/repo"), SINCE)
        self.assertEqual(n, 0)

    def test_returns_zero_on_failure(self):
        with mock.patch("commands.handoff.subprocess.run",
                        return_value=_proc(stdout="", returncode=128)):
            n = handoff._repo_commits_since(Path("/tmp/repo"), SINCE)
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
