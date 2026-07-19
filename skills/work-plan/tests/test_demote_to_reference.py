"""Tests for `demote-to-reference` — migrate a track's github.issues entries
to github.references when a specialist track already owns them (#462).

Covers:
- Successful conversion (other active owner exists) → issues→references write.
- Refusal when ANY issue has no other owner → target left completely unchanged
  (all-or-nothing preflight).
- Idempotent rerun (already referenced, no longer owned) → no-op, rc 0.
- Existing references + unrelated issues preserved in sorted order.
- Unrelated frontmatter/body preserved; other owning tracks never written.
- --expect CAS staleness → aborts with {stale} JSON, no write.
- Public-repo confirm-token gate (mirrors slot/batch-slot).
- Usage / not-found error cases.
- Composition with export_model: a demoted issue renders under references,
  not owner-track rollup/next-up (#462 requirement 6).
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

from commands import demote_to_reference
from lib.membership_guard import demote_fingerprint
from lib.write_guard import make_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _track(*, name, repo="ok/repo", issues=None, references=None, status="active"):
    meta = {
        "track": name,
        "status": status,
        "github": {"repo": repo, "issues": list(issues or [])},
    }
    if references is not None:
        meta["github"]["references"] = list(references)
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake/{name}.md"),
        body="# fake",
        meta=meta,
        has_frontmatter=True,
        repo=repo,
    )


def _drive(args, tracks=None, vis="PRIVATE"):
    """Run demote_to_reference.run(args) with all external I/O mocked."""
    if tracks is None:
        tracks = [_track(name="mvp", repo="ok/repo", issues=[])]
    cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/repo"}}}
    by_path = {str(t.path): t for t in tracks}

    def fake_parse(p):
        t = by_path[str(p)]
        return (t.meta, t.body)

    with patch("commands.demote_to_reference.load_config", return_value=cfg), \
         patch("commands.demote_to_reference.discover_tracks", return_value=tracks), \
         patch("lib.write_guard.repo_visibility", return_value=vis), \
         patch("lib.membership_guard.parse_file", side_effect=fake_parse), \
         patch("lib.membership_guard.write_file") as mw:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = demote_to_reference.run(args)
    return rc, mw, buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class DemoteToReferenceTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # Successful conversion
    # ------------------------------------------------------------------

    def test_demotes_issue_with_other_active_owner(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()  # only target written — specialist untouched
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["issues"], [])
        self.assertEqual(written_meta["github"]["references"], [42])
        self.assertIn("Demoted", out)
        self.assertIn("42", out)

    def test_demotes_multiple_issues_in_one_write(self):
        target = _track(name="mvp", repo="ok/repo", issues=[10, 20, 30])
        specialist = _track(name="specialist", repo="ok/repo", issues=[10, 20])
        rc, mw, out = _drive(["10", "20", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["issues"], [30])
        self.assertEqual(written_meta["github"]["references"], [10, 20])

    # ------------------------------------------------------------------
    # Refusal — orphan / not-owned (all-or-nothing)
    # ------------------------------------------------------------------

    def test_refuses_orphaned_issue_and_leaves_target_unchanged(self):
        """One issue (20) has no other owner → the WHOLE batch is refused,
        including issue 10 which would otherwise be a valid demotion."""
        target = _track(name="mvp", repo="ok/repo", issues=[10, 20])
        specialist = _track(name="specialist", repo="ok/repo", issues=[10])  # owns 10 only
        rc, mw, out = _drive(["10", "20", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        self.assertEqual(target.meta["github"]["issues"], [10, 20])  # unchanged
        self.assertIn("Refused", out)
        self.assertIn("20", out)
        self.assertIn("no other active owning track", out)

    def test_refuses_issue_not_owned_by_target(self):
        target = _track(name="mvp", repo="ok/repo", issues=[10])
        rc, mw, out = _drive(["999", "mvp"], tracks=[target], vis="PRIVATE")
        self.assertEqual(rc, 1)
        mw.assert_not_called()
        self.assertIn("not currently owned", out)

    def test_only_active_owner_counts_not_parked(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        parked = _track(name="old", repo="ok/repo", issues=[42], status="parked")
        rc, mw, out = _drive(["42", "mvp"], tracks=[target, parked], vis="PRIVATE")
        self.assertEqual(rc, 1)
        mw.assert_not_called()

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def test_idempotent_rerun_is_a_noop(self):
        """Issue already demoted (in references, not issues) → skipped, no write."""
        target = _track(name="mvp", repo="ok/repo", issues=[], references=[42])
        rc, mw, out = _drive(["42", "mvp"], tracks=[target], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        self.assertIn("already referenced", out)

    def test_idempotent_rerun_mixed_with_new_demotion(self):
        """42 already demoted, 10 is a fresh valid demotion → only 10 written,
        42 reported as already-referenced, no refusal."""
        target = _track(name="mvp", repo="ok/repo", issues=[10], references=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[10])
        rc, mw, out = _drive(["10", "42", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["issues"], [])
        self.assertEqual(written_meta["github"]["references"], [10, 42])
        self.assertIn("Already referenced", out)

    # ------------------------------------------------------------------
    # Existing references + ordering preserved
    # ------------------------------------------------------------------

    def test_preserves_existing_references_and_sorts(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42, 50], references=[5, 99])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 0)
        written_meta = mw.call_args[0][1]
        self.assertEqual(written_meta["github"]["issues"], [50])
        self.assertEqual(written_meta["github"]["references"], [5, 42, 99])

    def test_preserves_unrelated_frontmatter_and_body(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        target.meta["next_up"] = [42]
        target.meta["launch_priority"] = "P1"
        target.body = "# MVP\n\nSome narrative body content.\n"
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 0)
        written_meta = mw.call_args[0][1]
        written_body = mw.call_args[0][2]
        self.assertEqual(written_meta["launch_priority"], "P1")
        self.assertEqual(written_body, "# MVP\n\nSome narrative body content.\n")
        # specialist track (the other owner) was never written
        self.assertEqual(specialist.meta["github"]["issues"], [42])

    # ------------------------------------------------------------------
    # CAS staleness
    # ------------------------------------------------------------------

    def test_stale_expect_aborts_with_json_no_write(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        stale_fp = demote_fingerprint({"github": {"issues": [], "references": []}})
        rc, mw, out = _drive(
            ["42", "mvp", f"--expect={stale_fp}"],
            tracks=[target, specialist], vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["stale"])

    def test_matching_expect_proceeds(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        fp = demote_fingerprint(target.meta)
        rc, mw, out = _drive(
            ["42", "mvp", f"--expect={fp}"],
            tracks=[target, specialist], vis="PRIVATE",
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    # ------------------------------------------------------------------
    # Public-repo confirm gate
    # ------------------------------------------------------------------

    def test_public_repo_no_token_returns_needs_confirm(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "mvp"], tracks=[target, specialist], vis="PUBLIC")
        self.assertEqual(rc, 0)
        mw.assert_not_called()
        data = json.loads(out.strip())
        self.assertTrue(data["needs_confirm"])
        self.assertEqual(data["token"], make_token("ok/repo", "mvp"))

    def test_public_repo_with_valid_token_proceeds(self):
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        tok = make_token("ok/repo", "mvp")
        rc, mw, out = _drive(
            ["42", "mvp", f"--confirm={tok}"],
            tracks=[target, specialist], vis="PUBLIC",
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()

    # ------------------------------------------------------------------
    # Usage / not-found
    # ------------------------------------------------------------------

    def test_less_than_two_positionals_returns_rc2(self):
        rc, mw, out = _drive(["42"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_bad_issue_number_returns_rc2(self):
        rc, mw, out = _drive(["notanumber", "mvp"])
        self.assertEqual(rc, 2)
        mw.assert_not_called()

    def test_unknown_track_returns_rc1(self):
        rc, mw, out = _drive(["42", "nonexistent"])
        self.assertEqual(rc, 1)
        mw.assert_not_called()

    def test_no_input_called(self):
        """Never prompts — pure non-interactive path."""
        target = _track(name="mvp", repo="ok/repo", issues=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])

        def _raise(*a, **kw):
            raise AssertionError("input() must not be called")

        with patch("builtins.input", side_effect=_raise):
            rc, mw, out = _drive(["42", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 0)

    # ------------------------------------------------------------------
    # Composition with export_model (#462 requirement 6) — a demoted issue
    # renders under references, not owner-track progress/next-up.
    # ------------------------------------------------------------------

    def test_demoted_issue_excluded_from_export_rollup_and_next_up(self):
        from lib.export_model import build_export

        target = _track(name="mvp", repo="ok/repo", issues=[42])
        specialist = _track(name="specialist", repo="ok/repo", issues=[42])
        rc, mw, out = _drive(["42", "mvp"], tracks=[target, specialist], vis="PRIVATE")
        self.assertEqual(rc, 0)
        written_meta = mw.call_args[0][1]
        target.meta = written_meta  # simulate the on-disk write landing

        issue_row = {"number": 42, "state": "OPEN", "labels": [], "assignees": []}
        export = build_export(
            [target], issues_by_track={}, visibility={},
            now="2026-07-19T00:00:00Z",
            references_by_track={("ok/repo", "mvp"): [issue_row]},
        )
        track_export = export["tracks"][0]
        self.assertEqual(track_export["rollup"], {"open": 0, "closed": 0})
        self.assertEqual(track_export["reference_rollup"], {"open": 1, "closed": 0})
        self.assertEqual([i["number"] for i in track_export["references"]], [42])
        self.assertEqual(track_export["issues"], [])
        self.assertEqual(track_export["next_up"], [])  # nothing owned to suggest


if __name__ == "__main__":
    unittest.main()
