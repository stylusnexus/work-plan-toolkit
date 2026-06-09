"""Tests for the coverage subcommand."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import coverage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(repos=None):
    if repos is None:
        repos = {"myrepo": {"github": "org/myrepo", "local": "/tmp/myrepo"}}
    return {"notes_root": "/tmp/notes", "repos": repos}


def _make_track(name, repo, issue_nums, status="active"):
    return SimpleNamespace(
        name=name,
        repo=repo,
        has_frontmatter=True,
        meta={"status": status, "github": {"repo": repo, "issues": issue_nums}},
    )


def _run(args, *, cfg, tracks, open_issues_by_repo):
    """Run coverage.run with mocked config, tracks, and gh calls."""
    def _mock_open_issues(repo, limit=1000):
        return open_issues_by_repo.get(repo, [])

    buf = io.StringIO()
    with patch("commands.coverage.load_config", return_value=cfg), \
         patch("commands.coverage.discover_tracks", return_value=tracks), \
         patch("commands.coverage.fetch_open_issues", side_effect=_mock_open_issues), \
         redirect_stdout(buf):
        rc = coverage.run(args)
    return rc, buf.getvalue()


def _issues(*numbers):
    return [{"number": n, "title": f"Issue {n}", "state": "OPEN"} for n in numbers]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class CoverageBasicTest(unittest.TestCase):

    def test_all_tracked_reports_full_coverage(self):
        cfg = _make_cfg()
        tracks = [_make_track("t1", "org/myrepo", [1, 2, 3])]
        rc, out = _run([], cfg=cfg, tracks=tracks,
                       open_issues_by_repo={"org/myrepo": _issues(1, 2, 3)})
        self.assertEqual(rc, 0)
        self.assertIn("full coverage", out)
        self.assertIn("Untracked:    0", out)

    def test_partial_coverage_shows_count_and_percent(self):
        cfg = _make_cfg()
        tracks = [_make_track("t1", "org/myrepo", [1, 2])]
        rc, out = _run([], cfg=cfg, tracks=tracks,
                       open_issues_by_repo={"org/myrepo": _issues(1, 2, 3, 4)})
        self.assertEqual(rc, 0)
        self.assertIn("Untracked:    2", out)
        self.assertIn("50%", out)

    def test_no_open_issues_reports_zero(self):
        cfg = _make_cfg()
        tracks = [_make_track("t1", "org/myrepo", [1])]
        rc, out = _run([], cfg=cfg, tracks=tracks,
                       open_issues_by_repo={"org/myrepo": []})
        self.assertEqual(rc, 0)
        self.assertIn("No open issues", out)

    def test_no_tracks_everything_untracked(self):
        cfg = _make_cfg()
        rc, out = _run([], cfg=cfg, tracks=[],
                       open_issues_by_repo={"org/myrepo": _issues(1, 2, 3)})
        self.assertEqual(rc, 0)
        self.assertIn("Untracked:    3", out)
        self.assertIn("100%", out)


class CoverageRepoFlagTest(unittest.TestCase):

    def test_repo_flag_scopes_to_one_repo(self):
        cfg = _make_cfg(repos={
            "repoA": {"github": "org/repoA"},
            "repoB": {"github": "org/repoB"},
        })
        tracks = [
            _make_track("tA", "org/repoA", [1]),
            _make_track("tB", "org/repoB", [2]),
        ]
        rc, out = _run(["--repo=repoA"], cfg=cfg, tracks=tracks,
                       open_issues_by_repo={"org/repoA": _issues(1, 99),
                                            "org/repoB": _issues(2, 98)})
        self.assertEqual(rc, 0)
        self.assertIn("repoA", out)
        self.assertNotIn("repoB", out)

    def test_unknown_repo_flag_returns_error(self):
        cfg = _make_cfg()
        rc, out = _run(["--repo=nope"], cfg=cfg, tracks=[],
                       open_issues_by_repo={})
        self.assertEqual(rc, 1)
        self.assertIn("ERROR", out)


class CoverageListFlagTest(unittest.TestCase):

    def test_list_flag_shows_issue_titles(self):
        cfg = _make_cfg()
        tracks = [_make_track("t1", "org/myrepo", [1])]
        rc, out = _run(["--list"], cfg=cfg, tracks=tracks,
                       open_issues_by_repo={"org/myrepo": _issues(1, 2, 3)})
        self.assertEqual(rc, 0)
        self.assertIn("Issue 2", out)
        self.assertIn("Issue 3", out)

    def test_list_flag_truncates_at_default_20(self):
        cfg = _make_cfg()
        open_nums = list(range(1, 26))  # 25 issues, none tracked
        rc, out = _run(["--list"], cfg=cfg, tracks=[],
                       open_issues_by_repo={"org/myrepo": _issues(*open_nums)})
        self.assertEqual(rc, 0)
        self.assertIn("and 5 more", out)

    def test_limit_flag_overrides_default(self):
        cfg = _make_cfg()
        open_nums = list(range(1, 11))  # 10 issues
        rc, out = _run(["--list", "--limit=3"], cfg=cfg, tracks=[],
                       open_issues_by_repo={"org/myrepo": _issues(*open_nums)})
        self.assertEqual(rc, 0)
        self.assertIn("and 7 more", out)

    def test_without_list_flag_no_titles_shown(self):
        cfg = _make_cfg()
        tracks = [_make_track("t1", "org/myrepo", [1])]
        rc, out = _run([], cfg=cfg, tracks=tracks,
                       open_issues_by_repo={"org/myrepo": _issues(1, 2, 3)})
        self.assertEqual(rc, 0)
        self.assertNotIn("Issue 2", out)
        self.assertNotIn("Issue 3", out)
        self.assertIn("--list", out)  # hint printed

    def test_exact_limit_no_remainder_line(self):
        cfg = _make_cfg()
        rc, out = _run(["--list", "--limit=3"], cfg=cfg, tracks=[],
                       open_issues_by_repo={"org/myrepo": _issues(1, 2, 3)})
        self.assertEqual(rc, 0)
        self.assertNotIn("more", out)


class CoverageMultiRepoTest(unittest.TestCase):

    def test_all_repos_reported_when_no_repo_flag(self):
        cfg = _make_cfg(repos={
            "repoA": {"github": "org/repoA"},
            "repoB": {"github": "org/repoB"},
        })
        tracks = [_make_track("tA", "org/repoA", [1])]
        rc, out = _run([], cfg=cfg, tracks=tracks,
                       open_issues_by_repo={"org/repoA": _issues(1, 2),
                                            "org/repoB": _issues(3, 4)})
        self.assertEqual(rc, 0)
        self.assertIn("repoA", out)
        self.assertIn("repoB", out)

    def test_tracks_without_frontmatter_ignored(self):
        cfg = _make_cfg()
        no_fm = SimpleNamespace(name="orphan", repo="org/myrepo",
                                has_frontmatter=False, meta={})
        rc, out = _run([], cfg=cfg, tracks=[no_fm],
                       open_issues_by_repo={"org/myrepo": _issues(1, 2)})
        self.assertEqual(rc, 0)
        # Both issues should be untracked since the track has no frontmatter
        self.assertIn("Untracked:    2", out)


if __name__ == "__main__":
    unittest.main()
