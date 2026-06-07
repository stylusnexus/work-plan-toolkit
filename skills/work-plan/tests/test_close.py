"""Tests for the non-interactive close command (issue #87, Phase 3a).

Covers:
- close <track> --state=parked on a PRIVATE repo → status set to parked,
  write_file called, shutil.move NOT called (stays in place), rc 0.
- --state=shipped on a private repo → status shipped, write_file called,
  shutil.move called to archive/shipped/, rc 0.
- --state=abandoned → moves to archive/abandoned/.
- Missing --state → rc 2, no write.
- Invalid --state=bogus → rc 2, no write.
- --note="wrapped up" → the body passed to write_file contains the ## Wrap-up
  section with the note.
- Public repo, no token → prints needs_confirm JSON, no write/move, rc 0;
  token equals make_token(repo, track.name).
- Public repo with valid --confirm=<token> → performs the close (write/move
  happen), rc 0.
- No input()/prompt_input is reached on the flagged path (patch them to raise).
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import close
from lib.write_guard import make_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _track(*, name="alpha", repo="ok/repo", status="active"):
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake/{name}.md"),
        body="# fake body",
        meta={
            "track": name,
            "status": status,
            "github": {"repo": repo},
        },
        has_frontmatter=True,
        repo=repo,
    )


def _drive(args, track=None, vis="PRIVATE"):
    """Run close.run(args) with all external I/O mocked.

    vis controls what repo_visibility returns (used by needs_confirm).
    track defaults to a single private-repo track named 'alpha'.
    """
    if track is None:
        track = _track()
    # notes_root must be a parent of the track path so relative_to() works
    cfg = {"notes_root": "/tmp/fake", "repos": {"ok": {"github": "ok/repo"}}}

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
# Test cases
# ---------------------------------------------------------------------------

class CloseNonInteractiveTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # State: parked (stays in place)
    # ------------------------------------------------------------------

    def test_parked_private_write_no_move(self):
        """close <track> --state=parked on PRIVATE repo → write_file called,
        shutil.move NOT called, rc 0."""
        rc, mw, ms, out = _drive(["alpha", "--state=parked"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        # status updated to parked
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["status"], "parked")
        # move must NOT be called for parked
        ms.move.assert_not_called()
        self.assertIn("parked", out)

    # ------------------------------------------------------------------
    # State: shipped (moves to archive/shipped/)
    # ------------------------------------------------------------------

    def test_shipped_private_write_and_move(self):
        """--state=shipped on private repo → write_file called, shutil.move
        called to archive/shipped/, rc 0."""
        rc, mw, ms, out = _drive(["alpha", "--state=shipped"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["status"], "shipped")
        ms.move.assert_called_once()
        # Destination path should contain archive/shipped
        dest_arg = ms.move.call_args[0][1]
        self.assertIn("archive", dest_arg)
        self.assertIn("shipped", dest_arg)

    # ------------------------------------------------------------------
    # State: abandoned (moves to archive/abandoned/)
    # ------------------------------------------------------------------

    def test_abandoned_private_write_and_move(self):
        """--state=abandoned → moves to archive/abandoned/."""
        rc, mw, ms, out = _drive(["alpha", "--state=abandoned"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["status"], "abandoned")
        ms.move.assert_called_once()
        dest_arg = ms.move.call_args[0][1]
        self.assertIn("archive", dest_arg)
        self.assertIn("abandoned", dest_arg)

    # ------------------------------------------------------------------
    # Missing / invalid --state
    # ------------------------------------------------------------------

    def test_missing_state_returns_rc2(self):
        """Missing --state → rc 2, no write."""
        rc, mw, ms, out = _drive(["alpha"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()
        ms.move.assert_not_called()

    def test_invalid_state_returns_rc2(self):
        """Invalid --state=bogus → rc 2, no write."""
        rc, mw, ms, out = _drive(["alpha", "--state=bogus"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()
        ms.move.assert_not_called()

    def test_missing_track_name_returns_rc2(self):
        """No positional args at all → rc 2 (usage error)."""
        rc, mw, ms, out = _drive([])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    # ------------------------------------------------------------------
    # --note flag
    # ------------------------------------------------------------------

    def test_note_appended_to_body(self):
        """--note='wrapped up' → body passed to write_file contains
        ## Wrap-up section with the note."""
        rc, mw, ms, out = _drive(["alpha", "--state=parked", "--note=wrapped up"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_body = mw.call_args[0][2]
        self.assertIn("## Wrap-up", written_body)
        self.assertIn("wrapped up", written_body)

    def test_no_note_no_wrap_up_section(self):
        """No --note flag → body does NOT contain ## Wrap-up section."""
        rc, mw, ms, out = _drive(["alpha", "--state=parked"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_body = mw.call_args[0][2]
        self.assertNotIn("## Wrap-up", written_body)

    # ------------------------------------------------------------------
    # Confirm-token gate (public repo)
    # ------------------------------------------------------------------

    def test_public_repo_no_token_returns_needs_confirm_json(self):
        """Public repo, no token → prints needs_confirm JSON, no write/move,
        rc 0; token equals make_token(repo, track.name)."""
        track = _track(name="alpha", repo="ok/repo")
        rc, mw, ms, out = _drive(["alpha", "--state=shipped"], track=track, vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        ms.move.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])
        self.assertEqual(data["token"], make_token("ok/repo", "alpha"))

    def test_public_repo_unknown_visibility_returns_needs_confirm(self):
        """Unknown visibility (None) → also requires confirm."""
        track = _track(name="alpha", repo="ok/repo")
        rc, mw, ms, out = _drive(["alpha", "--state=parked"], track=track, vis=None)
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    def test_public_repo_with_valid_confirm_performs_close(self):
        """Public repo with valid --confirm=<token> → performs the close
        (write_file called), rc 0."""
        track = _track(name="alpha", repo="ok/repo")
        tok = make_token("ok/repo", "alpha")
        rc, mw, ms, out = _drive(
            ["alpha", "--state=parked", f"--confirm={tok}"],
            track=track, vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    def test_public_repo_with_valid_confirm_shipped_moves(self):
        """Public repo with valid --confirm=<token> + --state=shipped →
        write_file AND shutil.move both called, rc 0."""
        track = _track(name="alpha", repo="ok/repo")
        tok = make_token("ok/repo", "alpha")
        rc, mw, ms, out = _drive(
            ["alpha", "--state=shipped", f"--confirm={tok}"],
            track=track, vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        ms.move.assert_called_once()

    def test_public_repo_wrong_token_blocks_write(self):
        """Public repo with wrong confirm token → blocked, no write, rc 0."""
        track = _track(name="alpha", repo="ok/repo")
        rc, mw, ms, out = _drive(
            ["alpha", "--state=shipped", "--confirm=wrongtoken"],
            track=track, vis="PUBLIC"
        )
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    # ------------------------------------------------------------------
    # No input() on non-interactive path
    # ------------------------------------------------------------------

    def test_no_input_called_on_flagged_path(self):
        """Flagged paths never call input() or prompt_input, even when
        --state/--note are provided and the repo is private."""
        track = _track(name="alpha", repo="ok/repo")

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called on non-interactive path")

        cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/repo"}}}

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise):
            with patch("commands.close.load_config", return_value=cfg), \
                 patch("commands.close.discover_tracks", return_value=[track]), \
                 patch("commands.close.find_track_by_name", return_value=track), \
                 patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
                 patch("commands.close.write_file"), \
                 patch("commands.close.shutil"), \
                 patch("pathlib.Path.mkdir"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = close.run(["alpha", "--state=parked", "--note=done"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
