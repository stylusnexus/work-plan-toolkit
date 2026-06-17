"""Tests for the non-interactive slot command (issue #87, Phase 3a).

Covers:
- Slots a new issue into a private-repo track → write_file called, rc 0.
- Issue already present → no write, rc 0, prints "already in".
- Public repo, no token → prints needs_confirm JSON, write_file NOT called, rc 0.
- Public repo with valid --confirm=<token> → write_file called, rc 0.
- --move with a prior owner → removes issue from prior owner (two writes).
- Default / --no-move with a prior owner → prior owner NOT modified (one write)
  and "still listed … --move" note is printed.
- Bad issue number / no positional → rc 2.
- No input() is reached on the non-interactive flagged paths.
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

from commands import slot
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
    """Run slot.run(args) with all external I/O mocked.

    vis controls what repo_visibility returns (used by needs_confirm).
    tracks defaults to a single empty private-repo track named 'alpha'.
    """
    if tracks is None:
        tracks = [_track(name="alpha", repo="ok/repo", issues=[])]
    cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/repo"}}}
    gh_proc = MagicMock(returncode=0, stdout="{}", stderr="")

    # The write path now goes through lib.membership_guard, which re-reads the
    # file (parse_file) and writes the merged result (write_file). Returning the
    # track's own meta/body objects from parse_file lets the guard mutate them in
    # place, so assertions on track.meta still observe the merge.
    by_path = {str(t.path): t for t in tracks}

    def fake_parse(p):
        t = by_path[str(p)]
        return (t.meta, t.body)

    with patch("commands.slot.load_config", return_value=cfg), \
         patch("commands.slot.discover_tracks", return_value=tracks), \
         patch("commands.slot.subprocess.run", return_value=gh_proc), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("lib.membership_guard.parse_file", side_effect=fake_parse), \
         patch("lib.membership_guard.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = slot.run(args)
    return rc, mw, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class SlotNonInteractiveTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # Basic slot (private repo)
    # ------------------------------------------------------------------

    def test_slots_new_issue_into_private_track(self):
        """Slots a new issue into a private-repo track → write_file called, rc 0."""
        track = _track(name="alpha", repo="ok/repo", issues=[10, 20])
        rc, mw, out = _drive(["30", "alpha"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertIn(30, written_meta["github"]["issues"])
        # Issues are sorted
        self.assertEqual(sorted(written_meta["github"]["issues"]),
                         written_meta["github"]["issues"])

    def test_already_present_no_write(self):
        """Issue already present → no write, rc 0, prints 'already in'."""
        track = _track(name="alpha", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "alpha"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("already in", out)

    # ------------------------------------------------------------------
    # Confirm-token gate (public repo)
    # ------------------------------------------------------------------

    def test_public_repo_no_token_returns_needs_confirm_json(self):
        """Public repo, no token → prints needs_confirm JSON, write_file NOT called, rc 0."""
        import json
        track = _track(name="alpha", repo="ok/repo", issues=[])
        rc, mw, out = _drive(["99", "alpha"], tracks=[track], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        # Output should be parseable JSON with needs_confirm key
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])
        self.assertEqual(data["token"], make_token("ok/repo", "alpha"))

    def test_public_repo_unknown_visibility_returns_needs_confirm_json(self):
        """Unknown visibility (None) → also requires confirm."""
        import json
        track = _track(name="alpha", repo="ok/repo", issues=[])
        rc, mw, out = _drive(["99", "alpha"], tracks=[track], vis=None)
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    def test_public_repo_with_valid_confirm_performs_write(self):
        """Public repo with valid --confirm=<token> → write_file called, rc 0."""
        track = _track(name="alpha", repo="ok/repo", issues=[])
        tok = make_token("ok/repo", "alpha")
        rc, mw, out = _drive(["99", "alpha", f"--confirm={tok}"],
                              tracks=[track], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    def test_public_repo_with_wrong_token_blocks_write(self):
        """Public repo with wrong confirm token → blocked, no write."""
        import json
        track = _track(name="alpha", repo="ok/repo", issues=[])
        rc, mw, out = _drive(["99", "alpha", "--confirm=badtoken"],
                              tracks=[track], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    # ------------------------------------------------------------------
    # --move / --no-move flags
    # ------------------------------------------------------------------

    def test_move_flag_removes_issue_from_prior_owner(self):
        """--move with a prior owner → removes issue from source, writes both."""
        source = _track(name="alpha", repo="ok/repo", issues=[42])
        target = _track(name="beta", repo="ok/repo", issues=[])
        rc, mw, out = _drive(["42", "beta", "--move"],
                              tracks=[source, target], vis="PRIVATE")
        self.assertEqual(rc, 0)
        self.assertEqual(2, mw.call_count,
                         "source + target should both be written with --move")
        self.assertNotIn(42, source.meta["github"]["issues"])
        self.assertIn(42, target.meta["github"]["issues"])

    def test_default_no_move_preserves_prior_owner(self):
        """Default (no flags) with a prior owner → prior owner NOT modified; note printed."""
        source = _track(name="alpha", repo="ok/repo", issues=[42])
        target = _track(name="beta", repo="ok/repo", issues=[])
        rc, mw, out = _drive(["42", "beta"], tracks=[source, target], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()  # only target written
        # Source is untouched
        self.assertIn(42, source.meta["github"]["issues"])
        self.assertIn(42, target.meta["github"]["issues"])
        # Note about --move must be printed
        self.assertIn("--move", out)
        self.assertIn("alpha", out)

    def test_explicit_no_move_preserves_prior_owner(self):
        """Explicit --no-move behaves same as default: prior owner NOT modified."""
        source = _track(name="alpha", repo="ok/repo", issues=[42])
        target = _track(name="beta", repo="ok/repo", issues=[])
        rc, mw, out = _drive(["42", "beta", "--no-move"],
                              tracks=[source, target], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIn(42, source.meta["github"]["issues"])
        self.assertIn(42, target.meta["github"]["issues"])
        self.assertIn("--move", out)

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_no_positional_args_returns_rc2(self):
        """No positional arguments → rc 2 (usage error)."""
        rc, mw, out = _drive([])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_bad_issue_number_returns_rc2(self):
        """Non-integer issue number → rc 2."""
        rc, mw, out = _drive(["notanumber", "alpha"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_move_and_no_move_together_returns_rc2(self):
        """Passing both --move and --no-move → rc 2, write_file NOT called."""
        track = _track(name="alpha", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "alpha", "--move", "--no-move"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 2)
        mw.assert_not_called()
        self.assertIn("ERROR", out)
        self.assertIn("mutually exclusive", out)

    # ------------------------------------------------------------------
    # No input() on non-interactive paths
    # ------------------------------------------------------------------

    def test_no_input_called_on_flagged_paths(self):
        """Flagged paths (issue + track given) never call input() even if
        prior owners exist or a public repo is detected."""
        source = _track(name="alpha", repo="ok/repo", issues=[42])
        target = _track(name="beta", repo="ok/repo", issues=[])

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called on non-interactive path")

        by_path = {str(t.path): t for t in (source, target)}

        def fake_parse(p):
            t = by_path[str(p)]
            return (t.meta, t.body)

        with patch("builtins.input", side_effect=_raise), \
             patch("lib.prompts.prompt_input", side_effect=_raise):
            cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/repo"}}}
            gh_proc = MagicMock(returncode=0, stdout="{}", stderr="")
            with patch("commands.slot.load_config", return_value=cfg), \
                 patch("commands.slot.discover_tracks", return_value=[source, target]), \
                 patch("commands.slot.subprocess.run", return_value=gh_proc), \
                 patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
                 patch("lib.membership_guard.parse_file", side_effect=fake_parse), \
                 patch("lib.membership_guard.write_file"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    # --move (prior owner path) + private repo (no confirm gate)
                    rc = slot.run(["42", "beta", "--move"])
        self.assertEqual(rc, 0)


class SlotExpectGuardTest(unittest.TestCase):
    """--expect compare-and-swap staleness guard (#241)."""

    def test_expect_match_writes(self):
        from lib.membership_guard import issues_fingerprint
        track = _track(name="alpha", repo="ok/repo", issues=[10, 20])
        fp = issues_fingerprint(track.meta)
        rc, mw, out = _drive(["30", "alpha", f"--expect={fp}"],
                             tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIn(30, track.meta["github"]["issues"])

    def test_expect_mismatch_aborts_with_stale_json(self):
        import json
        from lib.membership_guard import issues_fingerprint
        track = _track(name="alpha", repo="ok/repo", issues=[10, 20])
        stale_fp = issues_fingerprint({"github": {"issues": [10]}})  # what we thought
        rc, mw, out = _drive(["30", "alpha", f"--expect={stale_fp}"],
                             tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())  # stdout is pure JSON in --expect mode
        self.assertTrue(data["stale"])
        self.assertEqual(data["current"], [10, 20])
        self.assertEqual(data["track"], "alpha")

    def test_no_expect_never_aborts(self):
        track = _track(name="alpha", repo="ok/repo", issues=[10, 20])
        rc, mw, out = _drive(["30", "alpha"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    def test_confirm_then_stale_order(self):
        """Public repo + valid confirm token + a stale --expect: the confirm gate
        is satisfied first, then the staleness CAS still aborts at write time."""
        import json
        from lib.membership_guard import issues_fingerprint
        track = _track(name="alpha", repo="ok/repo", issues=[10, 20])
        tok = make_token("ok/repo", "alpha")
        stale_fp = issues_fingerprint({"github": {"issues": [10]}})
        rc, mw, out = _drive(["30", "alpha", f"--confirm={tok}", f"--expect={stale_fp}"],
                             tracks=[track], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["stale"])


if __name__ == "__main__":
    unittest.main()
