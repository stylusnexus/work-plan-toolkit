"""Tests for the move subcommand (issue #162).

Covers:
- Moves an issue from source track to destination track (two writes).
- Issue not in source → error, rc 1.
- Cross-repo guard → error, rc 1.
- Same-track no-op → rc 0, message.
- Already in destination → remove from source only, rc 0.
- Public repo confirm gate → prints needs_confirm JSON, rc 0.
- Public repo with valid --confirm=<token> → writes, rc 0.
- Bad args → rc 2.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import move
from lib.write_guard import make_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _track(*, name, repo="ok/repo", issues=None, status="active"):
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake/{name}.md"),
        body="# fake",
        meta={
            "track": name,
            "status": status,
            "github": {"repo": repo, "issues": list(issues or [])},
        },
        has_frontmatter=True,
        repo=repo,
    )


def _drive(args, tracks=None, vis="PRIVATE"):
    """Run move.run(args) with all external I/O mocked."""
    if tracks is None:
        tracks = [
            _track(name="alpha", issues=[42]),
            _track(name="beta", issues=[]),
        ]
    cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/repo"}}}

    with patch("commands.move.load_config", return_value=cfg), \
         patch("commands.move.discover_tracks", return_value=tracks), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("commands.move.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = move.run(args)
    return rc, mw, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class MoveBasicTest(unittest.TestCase):

    def test_moves_issue_from_source_to_destination(self):
        """Move #42 from alpha to beta: both tracks written."""
        tracks = [
            _track(name="alpha", issues=[42, 99]),
            _track(name="beta", issues=[7]),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 0)
        self.assertIn("Removed #42 from 'alpha'", out)
        self.assertIn("Added #42 to 'beta'", out)
        # Two writes: source then destination
        self.assertEqual(mw.call_count, 2)

        # Source: 42 removed, 99 remains
        source_call = mw.call_args_list[0]
        source_issues = source_call[0][1]["github"]["issues"]
        self.assertNotIn(42, source_issues)
        self.assertIn(99, source_issues)

        # Destination: 42 added, 7 remains, sorted
        dest_call = mw.call_args_list[1]
        dest_issues = dest_call[0][1]["github"]["issues"]
        self.assertIn(42, dest_issues)
        self.assertIn(7, dest_issues)
        self.assertEqual(dest_issues, sorted(dest_issues))

    def test_issue_not_in_source_errors(self):
        """#999 is not in alpha → rc 1, error message."""
        tracks = [
            _track(name="alpha", issues=[42]),
            _track(name="beta", issues=[]),
        ]
        rc, mw, out = _drive(["999", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 1)
        self.assertIn("not in track", out)
        mw.assert_not_called()

    def test_cross_repo_move_errors(self):
        """Moving between different repos is rejected."""
        tracks = [
            _track(name="alpha", repo="ok/repo", issues=[42]),
            _track(name="beta", repo="other/repo", issues=[]),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 1)
        self.assertIn("cross-repo", out)
        mw.assert_not_called()

    def test_same_track_noop(self):
        """Moving to the same track is a no-op."""
        tracks = [
            _track(name="alpha", issues=[42]),
            _track(name="beta", issues=[]),
        ]
        rc, mw, out = _drive(["42", "alpha", "alpha"], tracks=tracks)
        self.assertEqual(rc, 0)
        self.assertIn("already in track", out)
        mw.assert_not_called()

    def test_already_in_destination_removes_from_source_only(self):
        """#42 already in beta → remove from alpha, don't re-add to beta."""
        tracks = [
            _track(name="alpha", issues=[42, 99]),
            _track(name="beta", issues=[42, 7]),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 0)
        self.assertIn("already in track 'beta'", out)
        self.assertIn("Removed #42 from 'alpha'", out)
        # Only one write (source only, dest unchanged)
        self.assertEqual(mw.call_count, 1)

        call = mw.call_args_list[0]
        source_issues = call[0][1]["github"]["issues"]
        self.assertNotIn(42, source_issues)
        self.assertIn(99, source_issues)

    def test_bad_args_usage(self):
        """Less than 3 positional args → rc 2."""
        rc, mw, out = _drive(["42", "alpha"])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", out)
        mw.assert_not_called()

    def test_non_numeric_issue_errors(self):
        """Non-numeric issue number → rc 2."""
        rc, mw, out = _drive(["abc", "alpha", "beta"])
        self.assertEqual(rc, 2)
        self.assertIn("not an issue number", out)
        mw.assert_not_called()


class MovePublicRepoTest(unittest.TestCase):

    def test_public_repo_prints_needs_confirm(self):
        """Public repo without --confirm prints needs_confirm JSON."""
        tracks = [
            _track(name="alpha", repo="ok/repo", issues=[42]),
            _track(name="beta", repo="ok/repo", issues=[]),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks, vis="PUBLIC")
        self.assertEqual(rc, 0)
        self.assertIn('"needs_confirm": true', out)
        self.assertIn('"token":', out)
        mw.assert_not_called()

    def test_public_repo_with_valid_confirm_writes(self):
        """Public repo with valid --confirm=<token> writes successfully."""
        tracks = [
            _track(name="alpha", repo="ok/repo", issues=[42]),
            _track(name="beta", repo="ok/repo", issues=[]),
        ]
        token = make_token("ok/repo", "beta")
        rc, mw, out = _drive(
            ["42", "alpha", "beta", f"--confirm={token}"],
            tracks=tracks,
            vis="PUBLIC",
        )
        self.assertEqual(rc, 0)
        self.assertIn("Removed #42 from 'alpha'", out)
        self.assertIn("Added #42 to 'beta'", out)
        self.assertEqual(mw.call_count, 2)

    def test_private_repo_no_token_writes_directly(self):
        """Private repo writes without any confirm gate."""
        tracks = [
            _track(name="alpha", issues=[42]),
            _track(name="beta", issues=[]),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 0)
        self.assertIn("Removed", out)
        self.assertIn("Added", out)
        self.assertEqual(mw.call_count, 2)


class MoveTrackResolutionTest(unittest.TestCase):

    def test_no_active_track_matching(self):
        """Inactive or nonexistent source track → rc 1."""
        tracks = [
            _track(name="alpha", issues=[42], status="shipped"),
            _track(name="beta", issues=[]),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 1)
        self.assertIn("No active track matching", out)

    def test_no_active_destination(self):
        """Inactive destination track → rc 1."""
        tracks = [
            _track(name="alpha", issues=[42]),
            _track(name="beta", issues=[], status="shipped"),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 1)
        self.assertIn("No active track matching", out)

    def test_issue_already_in_archived_track(self):
        """Moving from an active track even if issue is also in a shipped track."""
        tracks = [
            _track(name="alpha", issues=[42]),
            _track(name="beta", issues=[]),
        ]
        rc, mw, out = _drive(["42", "alpha", "beta"], tracks=tracks)
        self.assertEqual(rc, 0)
        self.assertIn("Removed", out)
        self.assertIn("Added", out)
        self.assertEqual(mw.call_count, 2)
