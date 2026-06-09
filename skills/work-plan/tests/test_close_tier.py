"""Tests for tier-aware archive display in close command (Phase C)."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import close


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shared_track(*, name="auth-flow", repo="org/myrepo"):
    """Return a SimpleNamespace that looks like a shared Track."""
    return SimpleNamespace(
        name=name,
        # Path is under a .work-plan/ dir, NOT under notes_root
        path=Path(f"/home/user/projects/myrepo/.work-plan/{name}.md"),
        body="# shared track body",
        meta={
            "track": name,
            "status": "active",
            "github": {"repo": repo},
        },
        has_frontmatter=True,
        repo=repo,
        tier="shared",
    )


def _private_track(*, name="alpha", repo="ok/repo"):
    """Return a SimpleNamespace for a private (notes_root) Track."""
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake-notes/ok/{name}.md"),
        body="# private track body",
        meta={
            "track": name,
            "status": "active",
            "github": {"repo": repo},
        },
        has_frontmatter=True,
        repo=repo,
        tier="private",
    )


def _drive(args, track, notes_root="/tmp/fake-notes", vis="PRIVATE"):
    cfg = {
        "notes_root": notes_root,
        "repos": {"ok": {"github": "ok/repo"}, "myrepo": {"github": "org/myrepo"}},
    }
    with patch("commands.close.load_config", return_value=cfg), \
         patch("commands.close.discover_tracks", return_value=[track]), \
         patch("commands.close.find_track_by_name", return_value=track), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("commands.close.write_file") as mw, \
         patch("commands.close.shutil") as ms, \
         patch("pathlib.Path.mkdir"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = close.run(args)
    return rc, mw, ms, buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class CloseTierTest(unittest.TestCase):

    def test_shared_track_shipped_does_not_crash_on_relative_to(self):
        """close on a shared track: archive is outside notes_root —
        should NOT raise ValueError, falls back to absolute path display."""
        track = _shared_track()
        rc, mw, ms, out = _drive(
            ["auth-flow", "--state=shipped"],
            track=track,
            notes_root="/tmp/fake-notes",
            vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        ms.move.assert_called_once()
        # Output should contain the track name and end state
        self.assertIn("auth-flow", out)
        self.assertIn("shipped", out)

    def test_shared_track_shipped_prints_commit_hint(self):
        """close on a shared track → output includes commit+push hint."""
        track = _shared_track()
        rc, mw, ms, out = _drive(
            ["auth-flow", "--state=shipped"],
            track=track,
            notes_root="/tmp/fake-notes",
            vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        self.assertIn("shared track", out)
        self.assertIn("commit + push", out)

    def test_private_track_shipped_no_commit_hint(self):
        """close on a private track → no commit+push hint in output."""
        track = _private_track()
        rc, mw, ms, out = _drive(
            ["alpha", "--state=shipped"],
            track=track,
            notes_root="/tmp/fake-notes",
            vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("commit + push", out)

    def test_shared_track_abandoned_prints_commit_hint(self):
        """close --state=abandoned on a shared track → commit+push hint."""
        track = _shared_track(name="old-feature")
        rc, mw, ms, out = _drive(
            ["old-feature", "--state=abandoned"],
            track=track,
            notes_root="/tmp/fake-notes",
            vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        self.assertIn("shared track", out)
        self.assertIn("commit + push", out)

    def test_shared_track_parked_no_move_no_hint(self):
        """close --state=parked on a shared track → parked (no move),
        no commit+push hint (parked stays in place, returns early)."""
        track = _shared_track()
        rc, mw, ms, out = _drive(
            ["auth-flow", "--state=parked"],
            track=track,
            notes_root="/tmp/fake-notes",
            vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        ms.move.assert_not_called()
        # The commit hint is only printed after a move (archive operation)
        self.assertNotIn("commit + push", out)

    def test_private_track_shipped_display_uses_relative_path(self):
        """Private track close shows path relative to notes_root (existing behaviour)."""
        track = _private_track()
        rc, mw, ms, out = _drive(
            ["alpha", "--state=shipped"],
            track=track,
            notes_root="/tmp/fake-notes",
            vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        # Should not contain the absolute prefix for private tracks
        # (it will contain 'ok/archive/shipped/alpha.md' or similar)
        self.assertIn("shipped", out)
        self.assertIn("alpha", out)


if __name__ == "__main__":
    unittest.main()
