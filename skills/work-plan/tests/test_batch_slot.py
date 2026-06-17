"""Tests for the non-interactive batch-slot command (issue #140).

Covers:
- Slots multiple new issues into a private-repo track → write_file called once, rc 0.
- Some issues already present → skipped with note, others slotted.
- All issues already present → no write, prints skip message.
- Public repo, no token → prints needs_confirm JSON, write_file NOT called, rc 0.
- Public repo with valid --confirm=<token> → write_file called, rc 0.
- --move with prior owners → removes issues from sources (consolidated writes).
- Default / --no-move with prior owners → prior owners NOT modified, note printed.
- Bad issue number / < 2 positionals → rc 2.
- Mutually exclusive --move + --no-move → rc 2.
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

from commands import batch_slot
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
    """Run batch_slot.run(args) with all external I/O mocked."""
    if tracks is None:
        tracks = [_track(name="alpha", repo="ok/repo", issues=[])]
    cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/repo"}}}
    gh_proc = MagicMock(returncode=0, stdout="{}", stderr="")

    # Writes go through lib.membership_guard (re-read via parse_file, write via
    # write_file). Returning each track's own meta/body lets the guard mutate
    # them in place, so assertions on track.meta still observe the merge.
    by_path = {str(t.path): t for t in tracks}

    def fake_parse(p):
        t = by_path[str(p)]
        return (t.meta, t.body)

    with patch("commands.batch_slot.load_config", return_value=cfg), \
         patch("commands.batch_slot.discover_tracks", return_value=tracks), \
         patch("commands.batch_slot.subprocess.run", return_value=gh_proc), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("lib.membership_guard.parse_file", side_effect=fake_parse), \
         patch("lib.membership_guard.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = batch_slot.run(args)
    return rc, mw, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class BatchSlotTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # Basic batch slot (private repo)
    # ------------------------------------------------------------------

    def test_slots_multiple_new_issues(self):
        """Slots multiple new issues into a private-repo track → write_file called, rc 0."""
        track = _track(name="alpha", repo="ok/repo", issues=[10])
        rc, mw, out = _drive(["30", "40", "alpha"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()  # target written once
        written_meta = mw.call_args[0][1]
        self.assertIn(10, written_meta["github"]["issues"])
        self.assertIn(30, written_meta["github"]["issues"])
        self.assertIn(40, written_meta["github"]["issues"])
        self.assertEqual(sorted(written_meta["github"]["issues"]),
                         written_meta["github"]["issues"])

    def test_skips_already_present_issues(self):
        """Some issues already present → skipped with note, others slotted."""
        track = _track(name="alpha", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "99", "alpha"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertIn(42, written_meta["github"]["issues"])
        self.assertIn(99, written_meta["github"]["issues"])
        self.assertIn("Skipped", out)
        self.assertIn("42", out)
        self.assertIn("Slotted", out)
        self.assertIn("99", out)

    def test_all_already_present_no_write(self):
        """All issues already present → no write, prints skip message."""
        track = _track(name="alpha", repo="ok/repo", issues=[42, 99])
        rc, mw, out = _drive(["42", "99", "alpha"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("already in track", out)

    # ------------------------------------------------------------------
    # Confirm-token gate (public repo)
    # ------------------------------------------------------------------

    def test_public_repo_no_token_returns_needs_confirm_json(self):
        """Public repo, no token → prints needs_confirm JSON, write_file NOT called."""
        import json
        track = _track(name="alpha", repo="ok/repo", issues=[])
        rc, mw, out = _drive(["99", "100", "alpha"], tracks=[track], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])
        self.assertEqual(data["token"], make_token("ok/repo", "alpha"))

    def test_public_repo_with_valid_confirm_performs_write(self):
        """Public repo with valid --confirm=<token> → write_file called."""
        track = _track(name="alpha", repo="ok/repo", issues=[])
        tok = make_token("ok/repo", "alpha")
        rc, mw, out = _drive(
            ["99", "100", "alpha", f"--confirm={tok}"],
            tracks=[track], vis="PUBLIC",
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    def test_public_repo_with_wrong_token_blocks_write(self):
        """Public repo with wrong confirm token → blocked, no write."""
        import json
        track = _track(name="alpha", repo="ok/repo", issues=[])
        rc, mw, out = _drive(
            ["99", "alpha", "--confirm=badtoken"],
            tracks=[track], vis="PUBLIC",
        )
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])

    # ------------------------------------------------------------------
    # --move / --no-move flags
    # ------------------------------------------------------------------

    def test_move_removes_issues_from_prior_owners(self):
        """--move with prior owners → removes issues from sources, writes all."""
        source = _track(name="alpha", repo="ok/repo", issues=[42, 77])
        target = _track(name="beta", repo="ok/repo", issues=[])
        rc, mw, out = _drive(
            ["42", "77", "beta", "--move"],
            tracks=[source, target], vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        # source + target both written
        self.assertEqual(2, mw.call_count)
        self.assertEqual([], source.meta["github"]["issues"])
        self.assertIn(42, target.meta["github"]["issues"])
        self.assertIn(77, target.meta["github"]["issues"])

    def test_move_consolidates_multi_source_removals(self):
        """Multiple issues from same prior owner → source written once."""
        source = _track(name="alpha", repo="ok/repo", issues=[42, 77])
        target = _track(name="beta", repo="ok/repo", issues=[])
        rc, mw, out = _drive(
            ["42", "77", "beta", "--move"],
            tracks=[source, target], vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(2, mw.call_count)  # source + target, NOT 3
        # Issues sorted are maintained
        self.assertEqual(sorted(source.meta["github"]["issues"]),
                         source.meta["github"]["issues"])
        self.assertEqual(sorted(target.meta["github"]["issues"]),
                         target.meta["github"]["issues"])

    def test_default_no_move_preserves_prior_owners(self):
        """Default (no --move) → prior owners NOT modified; note printed."""
        source = _track(name="alpha", repo="ok/repo", issues=[42])
        target = _track(name="beta", repo="ok/repo", issues=[])
        rc, mw, out = _drive(
            ["42", "beta"], tracks=[source, target], vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()  # only target written
        self.assertIn(42, source.meta["github"]["issues"])
        self.assertIn(42, target.meta["github"]["issues"])
        self.assertIn("--move", out)

    def test_explicit_no_move_preserves_prior_owners(self):
        """Explicit --no-move behaves same as default."""
        source = _track(name="alpha", repo="ok/repo", issues=[42])
        target = _track(name="beta", repo="ok/repo", issues=[])
        rc, mw, out = _drive(
            ["42", "beta", "--no-move"],
            tracks=[source, target], vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertIn(42, source.meta["github"]["issues"])
        self.assertIn("--move", out)

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_less_than_two_positionals_returns_rc2(self):
        """Fewer than 2 positional args (need at least 1 issue + 1 track) → rc 2."""
        rc, mw, out = _drive(["42"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_no_args_returns_rc2(self):
        """No positional arguments → rc 2."""
        rc, mw, out = _drive([])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_bad_issue_number_returns_rc2(self):
        """Non-integer in issue position → rc 2."""
        rc, mw, out = _drive(["notanumber", "alpha"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_move_and_no_move_together_returns_rc2(self):
        """Both --move and --no-move → rc 2."""
        track = _track(name="alpha", repo="ok/repo", issues=[])
        rc, mw, out = _drive(
            ["42", "alpha", "--move", "--no-move"],
            tracks=[track], vis="PRIVATE",
        )
        self.assertEqual(rc, 2)
        mw.assert_not_called()
        self.assertIn("mutually exclusive", out)

    def test_unknown_track_returns_rc1(self):
        """Track not found → rc 1."""
        rc, mw, out = _drive(["42", "nonexistent"])
        self.assertEqual(rc, 1)
        mw.assert_not_called()

    # ------------------------------------------------------------------
    # Single issue (degenerate case)
    # ------------------------------------------------------------------

    def test_single_issue_works_like_slot(self):
        """A single issue in batch-slot behaves like regular slot."""
        track = _track(name="alpha", repo="ok/repo", issues=[10])
        rc, mw, out = _drive(["42", "alpha"], tracks=[track], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertIn(42, written_meta["github"]["issues"])

    # ------------------------------------------------------------------
    # No input() on non-interactive paths
    # ------------------------------------------------------------------

    def test_no_input_called_on_flagged_paths(self):
        """Flagged paths (issue + track given) never call input()."""
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
            with patch("commands.batch_slot.load_config", return_value=cfg), \
                 patch("commands.batch_slot.discover_tracks", return_value=[source, target]), \
                 patch("commands.batch_slot.subprocess.run", return_value=gh_proc), \
                 patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
                 patch("lib.membership_guard.parse_file", side_effect=fake_parse), \
                 patch("lib.membership_guard.write_file"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = batch_slot.run(["42", "beta", "--move"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
