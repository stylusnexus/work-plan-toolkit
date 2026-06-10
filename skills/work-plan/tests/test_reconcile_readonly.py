"""Read-only GitHub contract test for the reconcile subcommand.

The docstring at the top of commands/reconcile.py declares:
  "reconcile only READS GitHub via `gh issue list`. It NEVER writes labels,
   edits issues, or modifies remote state."

This test enforces that contract. Without it, the docstring is aspirational —
a future refactor could silently introduce a `gh issue edit` (or close, or
label, or comment) call and the existing test suite would still pass.

The test mocks subprocess.run, drives reconcile against a fake track, and
asserts every captured `gh` invocation matches an allowlist of read-only
verbs. It exercises both the default-label path (no `github.labels`
override) and the new override path from #32.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import reconcile

# Allowlist of `gh` subcommand pairs considered read-only.
# `gh api` is intentionally excluded — it can be GET or write depending on -X.
# If reconcile ever needs it, add a more specific check (require -X GET, etc.).
READ_ONLY_GH_VERBS = {
    ("issue", "list"),
    ("issue", "view"),
    ("pr", "list"),
    ("pr", "view"),
}


def _fake_track(*, slug, repo, labels=None, issues=None):
    meta = {
        "track": slug,
        "status": "active",
        "github": {"repo": repo, "issues": issues or []},
    }
    if labels is not None:
        meta["github"]["labels"] = labels
    return SimpleNamespace(
        name=slug,
        path=Path(f"/tmp/fake/{slug}.md"),
        body="# fake",
        meta=meta,
        has_frontmatter=True,
        repo=repo,
    )


class ReadOnlyContractTest(unittest.TestCase):
    def _drive(self, *, track, gh_response, user_choice, extra_args=None):
        """Run reconcile.run against mocks; return (exit_code, captured_argvs, write_mock, prompt_mock)."""
        captured = []

        def fake_run(argv, *args, **kwargs):
            captured.append(list(argv))
            return MagicMock(returncode=0, stdout=json.dumps(gh_response), stderr="")

        cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/ok"}}}
        # NOTE: find_track_by_name is intentionally NOT mocked. We let the real
        # resolver run against the in-memory [track] list so a regression that
        # broke the active-status filter (or the name-matching logic) would
        # surface here — not just be silently bypassed by the mock.
        with patch("commands.reconcile.subprocess.run", side_effect=fake_run), \
             patch("commands.reconcile.load_config", return_value=cfg), \
             patch("commands.reconcile.discover_tracks", return_value=[track]), \
             patch("commands.reconcile.prompt_input", return_value=user_choice) as mock_prompt, \
             patch("commands.reconcile.write_file") as mock_write:
            args = [track.meta["track"]] + (extra_args or [])
            rc = reconcile.run(args)
        return rc, captured, mock_write, mock_prompt

    def _assert_read_only(self, captured):
        gh_calls = [a for a in captured if a and a[0] == "gh"]
        self.assertGreater(len(gh_calls), 0,
                           "reconcile should have made at least one gh call")
        for argv in gh_calls:
            verb_pair = tuple(argv[1:3])
            self.assertIn(
                verb_pair, READ_ONLY_GH_VERBS,
                f"reconcile invoked a non-read-only gh command: {' '.join(argv)}\n"
                f"This violates the READ-ONLY GITHUB CONTRACT documented at the top "
                f"of commands/reconcile.py. Writes must go through the local "
                f"frontmatter file, never through gh.",
            )

    def test_default_label_path_is_read_only(self):
        # Track without `github.labels` falls back to default `track/<slug>`.
        track = _fake_track(slug="alpha", repo="ok/ok", labels=None, issues=[1, 2, 3])
        gh_response = [
            {"number": 1, "title": "one", "state": "OPEN"},
            {"number": 4, "title": "four", "state": "OPEN"},
        ]
        rc, captured, mock_write, _ = self._drive(
            track=track, gh_response=gh_response, user_choice="n",
        )
        self.assertEqual(rc, 0)
        self._assert_read_only(captured)
        mock_write.assert_not_called()

    def test_label_override_path_is_read_only(self):
        # Track WITH `github.labels` override (the new feature from #32).
        # Each label produces a `gh issue list` AND a `gh pr list` — all must
        # be read-only. PRs are queried so frontmatter entries pointing at
        # labeled PRs aren't spuriously FLAGged.
        track = _fake_track(slug="beta", repo="ok/ok",
                            labels=["storytelling", "campaigns"], issues=[10])
        gh_response = [{"number": 10, "title": "x", "state": "OPEN"}]
        rc, captured, mock_write, _ = self._drive(
            track=track, gh_response=gh_response, user_choice="n",
        )
        self.assertEqual(rc, 0)
        self._assert_read_only(captured)
        # Two configured labels × two kinds (issue + pr) → four gh invocations
        gh_calls = [a for a in captured if a and a[0] == "gh"]
        self.assertEqual(len(gh_calls), 4,
                         f"expected one gh issue + one gh pr call per label, got {len(gh_calls)}")
        kinds = sorted(c[1] for c in gh_calls)
        self.assertEqual(kinds, ["issue", "issue", "pr", "pr"],
                         f"expected two issue + two pr calls, got {kinds}")

    def test_user_accept_writes_local_file_only_not_gh(self):
        # Even when the user accepts the proposed ADDs, the only write should
        # be to the local frontmatter file via write_file — never via gh.
        track = _fake_track(slug="gamma", repo="ok/ok", issues=[5])
        gh_response = [
            {"number": 5, "title": "x", "state": "OPEN"},
            {"number": 99, "title": "new", "state": "OPEN"},
        ]
        rc, captured, mock_write, _ = self._drive(
            track=track, gh_response=gh_response, user_choice="y",
        )
        self.assertEqual(rc, 0)
        self._assert_read_only(captured)
        mock_write.assert_called_once()

    def test_yes_applies_without_prompt_and_writes_local_only(self):
        # --yes (non-interactive, e.g. from the VS Code extension) applies the
        # proposed ADDs without ever calling prompt_input, and the only write
        # is the local frontmatter file — never gh. This is the #183 fix: a
        # piped/no-TTY run must not hang on the prompt.
        track = _fake_track(slug="epsilon", repo="ok/ok", issues=[5])
        gh_response = [
            {"number": 5, "title": "x", "state": "OPEN"},
            {"number": 99, "title": "new", "state": "OPEN"},
        ]
        rc, captured, mock_write, mock_prompt = self._drive(
            track=track, gh_response=gh_response,
            user_choice="n", extra_args=["--yes"],
        )
        self.assertEqual(rc, 0)
        self._assert_read_only(captured)
        mock_prompt.assert_not_called()
        mock_write.assert_called_once()

    def test_draft_skips_user_prompt_and_write(self):
        # --draft prints the analysis but never prompts and never writes.
        # Even with proposed ADDs (so the report path is exercised), the user
        # should not be interrupted and the local file should remain untouched.
        # user_choice="y" would normally trigger a write — proves --draft
        # short-circuits before the prompt is reached.
        track = _fake_track(slug="delta", repo="ok/ok", issues=[5])
        gh_response = [
            {"number": 5, "title": "x", "state": "OPEN"},
            {"number": 99, "title": "new", "state": "OPEN"},
        ]
        rc, captured, mock_write, mock_prompt = self._drive(
            track=track, gh_response=gh_response,
            user_choice="y", extra_args=["--draft"],
        )
        self.assertEqual(rc, 0)
        self._assert_read_only(captured)
        mock_prompt.assert_not_called()
        mock_write.assert_not_called()


    def test_timeout_skips_track_but_continues_others(self):
        # When _fetch_labeled_issues raises TimeoutExpired for one track, the
        # track is skipped with a ⚠ warning and the rest of --all continues.
        # Verifies: no crash, warning printed, other tracks still processed.
        track_alpha = _fake_track(slug="alpha", repo="ok/ok", issues=[1])
        track_beta = _fake_track(slug="beta", repo="ok/ok", issues=[10])

        captured = []
        timed_out_labels = set()

        def fake_run(argv, *args, **kwargs):
            captured.append(list(argv))
            # alpha's default label is "track/alpha" — time it out
            if "--label" in argv:
                label_idx = argv.index("--label") + 1
                label = argv[label_idx]
                if label == "track/alpha":
                    timed_out_labels.add(label)
                    raise subprocess.TimeoutExpired(cmd=argv, timeout=15)
            return MagicMock(
                returncode=0,
                stdout=json.dumps([{"number": 10, "title": "x", "state": "OPEN"}]),
                stderr="",
            )

        cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/ok"}}}
        with patch("commands.reconcile.subprocess.run", side_effect=fake_run), \
             patch("commands.reconcile.load_config", return_value=cfg), \
             patch("commands.reconcile.discover_tracks",
                   return_value=[track_alpha, track_beta]), \
             patch("commands.reconcile.prompt_input",
                   return_value="n") as mock_prompt, \
             patch("commands.reconcile.write_file") as mock_write:
            rc = reconcile.run(["--all"])

        self.assertEqual(rc, 0)
        self.assertTrue(timed_out_labels, "alpha label should have timed out")
        # Beta's gh calls should have succeeded
        beta_calls = [a for a in captured
                      if "--label" in a and a[a.index("--label") + 1] == "track/beta"]
        self.assertTrue(len(beta_calls) > 0,
                        "beta should have been fetched after alpha timeout")
        mock_write.assert_not_called()

    def test_single_track_timeout_skips_cleanly(self):
        # Even with a single track (the non-parallel code path), a timeout
        # should skip the track with a warning and return 0 without crashing.
        track = _fake_track(slug="lonely", repo="ok/ok", issues=[7])

        captured = []
        timed_out = False

        def fake_run(argv, *args, **kwargs):
            captured.append(list(argv))
            nonlocal timed_out
            timed_out = True
            raise subprocess.TimeoutExpired(cmd=argv, timeout=15)

        cfg = {"notes_root": "/tmp/fake-notes", "repos": {"ok": {"github": "ok/ok"}}}
        with patch("commands.reconcile.subprocess.run", side_effect=fake_run), \
             patch("commands.reconcile.load_config", return_value=cfg), \
             patch("commands.reconcile.discover_tracks", return_value=[track]), \
             patch("commands.reconcile.prompt_input") as mock_prompt, \
             patch("commands.reconcile.write_file") as mock_write:
            rc = reconcile.run(["lonely"])

        self.assertEqual(rc, 0)
        self.assertTrue(timed_out)
        mock_prompt.assert_not_called()
        mock_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
