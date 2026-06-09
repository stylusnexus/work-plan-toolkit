"""Tests for repo-qualified track resolution (Phase B).

Covers:
- find_track_by_name: single match, no match, ambiguous (raises AmbiguousTrackError)
- find_track_by_name with repo=: disambiguates cross-repo same slug
- parse_track_repo_arg: all split cases
- close command accepts --repo=<key>
- handoff command accepts --repo=<key>
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.tracks import (
    Track,
    AmbiguousTrackError,
    find_track_by_name,
    parse_track_repo_arg,
)
from commands import close, handoff


# ---------------------------------------------------------------------------
# Track factory helpers
# ---------------------------------------------------------------------------

def _track(name, repo=None, folder=None, status="active"):
    """Build a minimal Track for testing."""
    return Track(
        path=Path(f"/tmp/notes/{name}.md"),
        name=name,
        has_frontmatter=True,
        needs_init=False,
        needs_filing=False,
        repo=repo,
        folder=folder,
        meta={"track": name, "status": status},
        body="",
    )


# ---------------------------------------------------------------------------
# find_track_by_name tests
# ---------------------------------------------------------------------------

class FindTrackByNameTest(unittest.TestCase):

    def test_single_match_returns_track(self):
        """One matching track → returned directly."""
        t = _track("feat-x", repo="org/repo")
        result = find_track_by_name("feat-x", [t])
        self.assertIs(result, t)

    def test_no_match_returns_none(self):
        """No matching track → returns None."""
        t = _track("feat-x", repo="org/repo")
        result = find_track_by_name("feat-y", [t])
        self.assertIsNone(result)

    def test_two_matches_raises_ambiguous_error(self):
        """Same slug across two repos → raises AmbiguousTrackError."""
        t1 = _track("feat-x", repo="org/repo-a", folder="repo-a")
        t2 = _track("feat-x", repo="org/repo-b", folder="repo-b")
        with self.assertRaises(AmbiguousTrackError) as cm:
            find_track_by_name("feat-x", [t1, t2])
        err = cm.exception
        self.assertEqual(err.name, "feat-x")
        self.assertIn(t1, err.candidates)
        self.assertIn(t2, err.candidates)
        self.assertEqual(len(err.candidates), 2)

    def test_ambiguous_error_message_contains_repos(self):
        """Error message names both repos and disambiguation hint."""
        t1 = _track("feat-x", repo="org/repo-a", folder="repo-a")
        t2 = _track("feat-x", repo="org/repo-b", folder="repo-b")
        with self.assertRaises(AmbiguousTrackError) as cm:
            find_track_by_name("feat-x", [t1, t2])
        msg = str(cm.exception)
        self.assertIn("repo-a", msg)
        self.assertIn("repo-b", msg)
        self.assertIn("--repo=", msg)
        self.assertIn("@", msg)

    def test_repo_qualifier_by_github_slug_disambiguates(self):
        """repo= matching github slug returns the correct track."""
        t1 = _track("feat-x", repo="org/repo-a", folder="repo-a")
        t2 = _track("feat-x", repo="org/repo-b", folder="repo-b")
        result = find_track_by_name("feat-x", [t1, t2], repo="org/repo-a")
        self.assertIs(result, t1)

    def test_repo_qualifier_by_folder_key_disambiguates(self):
        """repo= matching folder key (case-insensitive) returns the correct track."""
        t1 = _track("feat-x", repo="org/repo-a", folder="repo-a")
        t2 = _track("feat-x", repo="org/repo-b", folder="repo-b")
        result = find_track_by_name("feat-x", [t1, t2], repo="REPO-B")
        self.assertIs(result, t2)

    def test_repo_qualifier_no_match_returns_none(self):
        """repo= that doesn't match any track → None (not ambiguous)."""
        t1 = _track("feat-x", repo="org/repo-a", folder="repo-a")
        t2 = _track("feat-x", repo="org/repo-b", folder="repo-b")
        result = find_track_by_name("feat-x", [t1, t2], repo="nonexistent")
        self.assertIsNone(result)

    def test_active_only_filters_before_match(self):
        """active_only=True excludes non-active tracks even when name matches."""
        t_parked = _track("feat-x", repo="org/repo", status="parked")
        t_active = _track("feat-y", repo="org/repo", status="active")
        result = find_track_by_name("feat-x", [t_parked, t_active], active_only=True)
        self.assertIsNone(result)

    def test_active_only_with_repo_disambiguates(self):
        """active_only=True + repo= both apply; non-active filtered then repo narrows."""
        t1 = _track("feat-x", repo="org/repo-a", folder="repo-a", status="active")
        t2 = _track("feat-x", repo="org/repo-b", folder="repo-b", status="parked")
        result = find_track_by_name("feat-x", [t1, t2], active_only=True, repo="repo-a")
        self.assertIs(result, t1)


# ---------------------------------------------------------------------------
# parse_track_repo_arg tests
# ---------------------------------------------------------------------------

class ParseTrackRepoArgTest(unittest.TestCase):

    def test_name_at_repo_splits_correctly(self):
        name, repo = parse_track_repo_arg("foo@critforge")
        self.assertEqual(name, "foo")
        self.assertEqual(repo, "critforge")

    def test_no_at_returns_original_none(self):
        name, repo = parse_track_repo_arg("foo")
        self.assertEqual(name, "foo")
        self.assertIsNone(repo)

    def test_leading_at_invalid_returns_original_none(self):
        """@foo has no valid name before @, so returns original arg and None."""
        name, repo = parse_track_repo_arg("@foo")
        self.assertEqual(name, "@foo")
        self.assertIsNone(repo)

    def test_rpartition_uses_last_at(self):
        """track@name@repo uses last @ as separator so earlier @ stays in name."""
        name, repo = parse_track_repo_arg("track@name@repo")
        self.assertEqual(name, "track@name")
        self.assertEqual(repo, "repo")


# ---------------------------------------------------------------------------
# close command — --repo=<key> accepted and passed through
# ---------------------------------------------------------------------------

def _make_close_track(name="alpha", repo="org/repo-a", folder="repo-a"):
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake/{name}.md"),
        body="# body",
        meta={"track": name, "status": "active", "github": {"repo": repo}},
        has_frontmatter=True,
        repo=repo,
    )


class CloseRepoFlagTest(unittest.TestCase):

    def _drive(self, args, find_result, vis="PRIVATE"):
        cfg = {"notes_root": "/tmp/fake", "repos": {}}
        with patch("commands.close.load_config", return_value=cfg), \
             patch("commands.close.discover_tracks", return_value=[]), \
             patch("commands.close.find_track_by_name", return_value=find_result) as mock_find, \
             patch("lib.write_guard.repo_visibility", return_value=vis), \
             patch("commands.close.write_file"), \
             patch("commands.close.shutil"), \
             patch("pathlib.Path.mkdir"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = close.run(args)
        return rc, mock_find, buf.getvalue()

    def test_repo_flag_passed_to_find_track(self):
        """--repo=<key> is extracted and passed as repo= to find_track_by_name."""
        track = _make_close_track()
        rc, mock_find, out = self._drive(
            ["alpha", "--state=parked", "--repo=repo-a"],
            find_result=track,
        )
        self.assertEqual(rc, 0)
        call_kwargs = mock_find.call_args
        # find_track_by_name called with repo="repo-a"
        self.assertEqual(call_kwargs.kwargs.get("repo"), "repo-a")

    def test_at_syntax_extracted_as_repo(self):
        """alpha@repo-a positional arg → track_name='alpha', repo_qualifier='repo-a'."""
        track = _make_close_track()
        rc, mock_find, out = self._drive(
            ["alpha@repo-a", "--state=parked"],
            find_result=track,
        )
        self.assertEqual(rc, 0)
        call_kwargs = mock_find.call_args
        self.assertEqual(call_kwargs.kwargs.get("repo"), "repo-a")

    def test_ambiguous_error_returns_rc1(self):
        """AmbiguousTrackError from find_track_by_name → prints message, returns 1."""
        t1 = _track("alpha", repo="org/a", folder="a")
        t2 = _track("alpha", repo="org/b", folder="b")
        err = AmbiguousTrackError("alpha", [t1, t2])
        cfg = {"notes_root": "/tmp/fake", "repos": {}}
        with patch("commands.close.load_config", return_value=cfg), \
             patch("commands.close.discover_tracks", return_value=[]), \
             patch("commands.close.find_track_by_name", side_effect=err):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = close.run(["alpha", "--state=parked"])
        self.assertEqual(rc, 1)
        self.assertIn("ambiguous", buf.getvalue().lower())


# ---------------------------------------------------------------------------
# handoff command — --repo=<key> accepted and passed through
# ---------------------------------------------------------------------------

class HandoffRepoFlagTest(unittest.TestCase):

    def _drive(self, args, find_result=None):
        """Drive handoff.run() minimally — mock everything except arg parsing."""
        cfg = {"notes_root": "/tmp/fake", "repos": {}}

        # Build a minimal track namespace if not supplied
        if find_result is None:
            find_result = SimpleNamespace(
                name="alpha",
                path=Path("/tmp/fake/alpha.md"),
                body="",
                meta={"track": "alpha", "status": "active", "github": {"issues": []}},
                has_frontmatter=True,
                repo="org/repo",
                local_path=None,
            )

        with patch("commands.handoff.load_config", return_value=cfg), \
             patch("commands.handoff.discover_tracks", return_value=[]), \
             patch("commands.handoff.find_track_by_name", return_value=find_result) as mock_find, \
             patch("commands.handoff.fetch_issues", return_value=[]), \
             patch("commands.handoff.write_file"), \
             patch("commands.handoff.append_session_log", return_value=""), \
             patch("commands.handoff.update_row_status", return_value=""), \
             patch("commands.handoff.sync_missing_rows", return_value=("", 0)), \
             patch("commands.handoff.find_new_issues_for_tracks", return_value={}), \
             patch("commands.handoff.has_uncommitted", return_value=False), \
             patch("commands.handoff.current_branch", return_value=None), \
             patch("commands.handoff.uncommitted_file_count", return_value=0), \
             patch("commands.handoff.commits_ahead", return_value=0):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = handoff.run(args)
        return rc, mock_find, buf.getvalue()

    def test_repo_flag_passed_to_find_track(self):
        """--repo=<key> reaches find_track_by_name as repo= kwarg."""
        rc, mock_find, _ = self._drive(["alpha", "--repo=repo-a"])
        call_kwargs = mock_find.call_args
        self.assertEqual(call_kwargs.kwargs.get("repo"), "repo-a")

    def test_at_syntax_passed_to_find_track(self):
        """alpha@repo-a positional → track_name='alpha', repo='repo-a'."""
        rc, mock_find, _ = self._drive(["alpha@repo-a"])
        call_kwargs = mock_find.call_args
        self.assertEqual(call_kwargs.kwargs.get("repo"), "repo-a")

    def test_ambiguous_error_returns_rc1(self):
        """AmbiguousTrackError → prints message, returns 1."""
        t1 = _track("alpha", repo="org/a", folder="a")
        t2 = _track("alpha", repo="org/b", folder="b")
        err = AmbiguousTrackError("alpha", [t1, t2])
        cfg = {"notes_root": "/tmp/fake", "repos": {}}
        with patch("commands.handoff.load_config", return_value=cfg), \
             patch("commands.handoff.discover_tracks", return_value=[]), \
             patch("commands.handoff.find_track_by_name", side_effect=err):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = handoff.run(["alpha"])
        self.assertEqual(rc, 1)
        self.assertIn("ambiguous", buf.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
