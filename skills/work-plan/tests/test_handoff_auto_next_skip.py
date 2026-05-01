"""Tests for --auto-next sibling-claim filtering (#50 corrected scope).

`handoff --auto-next` is non-interactive on collisions: when the suggester
returns issues already next_up on a sibling active track in the same repo,
those issues are dropped silently (with a transparent "↷ skipped" line),
NOT prompted. The edit branch falls back to --set-next-style warn/confirm
because the user is explicit there.
"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import handoff
from lib.frontmatter import parse_file, write_file


def _make_track(dir_path: Path, slug: str, *, repo: str, status: str = "active",
                next_up=None, issues=None) -> Path:
    meta = {
        "track": slug,
        "status": status,
        "launch_priority": "P1",
        "github": {
            "repo": repo,
            "issues": list(issues or [100, 200, 300, 400]),
            "branches": [],
        },
        "next_up": list(next_up or []),
    }
    body = f"\n# {slug}\n\nBody.\n"
    path = dir_path / f"{slug}.md"
    write_file(path, meta, body)
    return path


def _open_issue(num: int, *, priority: str = "P1") -> dict:
    return {
        "number": num,
        "title": f"issue-{num}",
        "state": "OPEN",
        "labels": [{"name": f"priority/{priority}"}],
        "updatedAt": "2026-04-30T00:00:00Z",
    }


class AutoNextSkipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }

        self._patches = [
            mock.patch("commands.handoff.load_config", return_value=self.cfg),
            mock.patch("commands.handoff.has_uncommitted", return_value=False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _run_auto_next(self, track_name: str, *, issues_response, prompt_answer="y"):
        """Run handoff --auto-next with mocked fetch_issues + prompt_input."""
        buf = io.StringIO()
        with mock.patch("commands.handoff.fetch_issues", return_value=issues_response), \
             mock.patch("commands.handoff.prompt_input", return_value=prompt_answer), \
             redirect_stdout(buf):
            rc = handoff.run([track_name, "--auto-next"])
        return rc, buf.getvalue()

    def test_no_collisions_passes_through_full_suggestion(self):
        """Sibling has nothing in next_up → suggestion is unchanged."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200])
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo", next_up=[])

        rc, out = self._run_auto_next("track-a",
                                      issues_response=[_open_issue(100), _open_issue(200)])

        self.assertEqual(rc, 0)
        self.assertNotIn("↷ skipped", out)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100, 200])

    def test_sibling_claimed_issue_is_skipped_with_transparent_line(self):
        """Sibling has #100 → #100 is dropped from suggestion, message printed."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200])
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo", next_up=[100])

        rc, out = self._run_auto_next("track-a",
                                      issues_response=[_open_issue(100), _open_issue(200)])

        self.assertEqual(rc, 0)
        self.assertIn("↷ skipped #100 (already next_up on 'track-b')", out)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [200])  # #100 dropped

    def test_all_suggestions_claimed_returns_zero_unchanged(self):
        """Every suggested issue is sibling-claimed → next_up unchanged, rc 0."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200], next_up=[42])
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo",
                    next_up=[100, 200])

        rc, out = self._run_auto_next("track-a",
                                      issues_response=[_open_issue(100), _open_issue(200)])

        self.assertEqual(rc, 0)
        self.assertIn("All suggested issues are already next_up on sibling tracks", out)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [42])  # original list intact

    def test_parked_sibling_does_not_filter(self):
        """Parked sibling holding #100 should NOT trigger a skip — parked
        tracks don't compete for attention."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200])
        _make_track(self.repo_dir, "track-parked", repo="stylusnexus/Demo",
                    status="parked", next_up=[100])

        rc, out = self._run_auto_next("track-a",
                                      issues_response=[_open_issue(100), _open_issue(200)])

        self.assertEqual(rc, 0)
        self.assertNotIn("↷ skipped", out)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100, 200])

    def test_cross_repo_sibling_does_not_filter(self):
        """Sibling in a different repo holding the same issue number should
        NOT trigger a skip — issue numbers are repo-scoped."""
        other_dir = self.notes_root / "other"
        other_dir.mkdir(parents=True)
        self.cfg["repos"]["other"] = {"github": "stylusnexus/Other"}

        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200])
        _make_track(other_dir, "track-other", repo="stylusnexus/Other",
                    next_up=[100])

        rc, out = self._run_auto_next("track-a",
                                      issues_response=[_open_issue(100), _open_issue(200)])

        self.assertEqual(rc, 0)
        self.assertNotIn("↷ skipped", out)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [100, 200])

    def test_user_decline_at_apply_prompt_keeps_skipped_record(self):
        """User picks 'n' at the apply prompt → next_up unchanged, but skip
        line was still printed (the filter ran before the prompt)."""
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200], next_up=[7])
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo", next_up=[100])

        rc, out = self._run_auto_next("track-a",
                                      issues_response=[_open_issue(100), _open_issue(200)],
                                      prompt_answer="n")

        self.assertEqual(rc, 0)
        self.assertIn("↷ skipped #100", out)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [7])  # decline preserved


if __name__ == "__main__":
    unittest.main()
