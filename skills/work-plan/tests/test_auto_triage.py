"""Tests for the auto-triage subcommand."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import auto_triage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(folder="myrepo", github="org/myrepo"):
    return {
        "notes_root": "/tmp/notes",
        "repos": {folder: {"github": github, "local": f"/tmp/{folder}"}},
    }


def _make_track(name, repo, issue_nums, status="active", slug=None):
    return SimpleNamespace(
        name=name,
        repo=repo,
        has_frontmatter=True,
        path=Path(f"/tmp/notes/{name}.md"),
        body="",
        meta={
            "track": slug or name,
            "status": status,
            "launch_priority": "P2",
            "milestone_alignment": "v1",
            "github": {"repo": repo, "issues": list(issue_nums)},
        },
    )


def _open_issues(*numbers):
    return [{"number": n, "title": f"Issue {n}", "state": "OPEN",
             "milestone": None, "labels": []} for n in numbers]


def _drive_prepare(args, *, cfg, tracks, open_issues):
    buf = io.StringIO()
    with patch("commands.auto_triage.load_config", return_value=cfg), \
         patch("commands.auto_triage.discover_tracks", return_value=tracks), \
         patch("commands.auto_triage.fetch_open_issues", return_value=open_issues), \
         patch("commands.auto_triage._batch_path") as mbatch, \
         patch("commands.auto_triage._answers_path"):
        # Use a real temp file so write_text works
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            mbatch.return_value = Path(f.name)
        with redirect_stdout(buf):
            rc = auto_triage.run(args)
    return rc, buf.getvalue(), mbatch.return_value


def _drive_apply(*, cfg, tracks, batch, answers):
    """Run auto_triage._apply with mocked filesystem and frontmatter calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        batch_file = Path(tmpdir) / "auto_triage.json"
        answers_file = Path(tmpdir) / "auto_triage.answers.json"
        batch_file.write_text(json.dumps(batch), encoding="utf-8")
        answers_file.write_text(json.dumps(answers), encoding="utf-8")

        with patch("commands.auto_triage._batch_path", return_value=batch_file), \
             patch("commands.auto_triage._answers_path", return_value=answers_file), \
             patch("commands.auto_triage.load_config", return_value=cfg), \
             patch("commands.auto_triage.discover_tracks", return_value=tracks), \
             patch("commands.auto_triage.parse_file",
                   side_effect=lambda p: (tracks[0].meta.copy()
                                         if tracks else {}, "")) as mparse, \
             patch("commands.auto_triage.write_file") as mwrite:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = auto_triage._apply(cfg)
        return rc, mwrite, buf.getvalue()


# ---------------------------------------------------------------------------
# Prepare step tests
# ---------------------------------------------------------------------------

class AutoTriagePrepareTest(unittest.TestCase):

    def test_prints_prompt_with_tracks_and_issues(self):
        cfg = _make_cfg()
        tracks = [_make_track("auth-flow", "org/myrepo", [1, 2])]
        rc, out, _ = _drive_prepare([], cfg=cfg, tracks=tracks,
                                    open_issues=_open_issues(1, 2, 3, 4))
        self.assertEqual(rc, 0)
        self.assertIn("auth-flow", out)
        self.assertIn("Issue 3", out)
        self.assertIn("Issue 4", out)
        # tracked issues should NOT appear in untracked list
        self.assertNotIn("Issue 1", out)
        self.assertNotIn("Issue 2", out)

    def test_no_untracked_issues_exits_clean(self):
        cfg = _make_cfg()
        tracks = [_make_track("auth-flow", "org/myrepo", [1, 2])]
        rc, out, _ = _drive_prepare([], cfg=cfg, tracks=tracks,
                                    open_issues=_open_issues(1, 2))
        self.assertEqual(rc, 0)
        self.assertIn("full coverage", out)

    def test_no_active_tracks_exits_with_guidance(self):
        cfg = _make_cfg()
        parked = _make_track("old-track", "org/myrepo", [1], status="parked")
        rc, out, _ = _drive_prepare([], cfg=cfg, tracks=[parked],
                                    open_issues=_open_issues(1, 2))
        self.assertEqual(rc, 0)
        self.assertIn("group", out)

    def test_multiple_repos_requires_repo_flag(self):
        cfg = {"notes_root": "/tmp", "repos": {
            "repoA": {"github": "org/repoA"},
            "repoB": {"github": "org/repoB"},
        }}
        rc, out, _ = _drive_prepare([], cfg=cfg, tracks=[],
                                    open_issues=[])
        self.assertEqual(rc, 1)
        self.assertIn("Specify with --repo", out)

    def test_repo_flag_filters_to_one_repo(self):
        cfg = {"notes_root": "/tmp", "repos": {
            "repoA": {"github": "org/repoA"},
            "repoB": {"github": "org/repoB"},
        }}
        tracks = [_make_track("t1", "org/repoA", [1])]
        rc, out, _ = _drive_prepare(["--repo=repoA"], cfg=cfg, tracks=tracks,
                                    open_issues=_open_issues(1, 2))
        self.assertEqual(rc, 0)
        self.assertIn("repoA", out)

    def test_unknown_repo_flag_returns_error(self):
        cfg = _make_cfg()
        rc, out, _ = _drive_prepare(["--repo=nope"], cfg=cfg, tracks=[],
                                    open_issues=[])
        self.assertEqual(rc, 1)
        self.assertIn("ERROR", out)

    def test_batch_file_written_with_correct_fields(self):
        cfg = _make_cfg()
        tracks = [_make_track("auth-flow", "org/myrepo", [1])]
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_file = Path(tmpdir) / "auto_triage.json"
            buf = io.StringIO()
            with patch("commands.auto_triage.load_config", return_value=cfg), \
                 patch("commands.auto_triage.discover_tracks", return_value=tracks), \
                 patch("commands.auto_triage.fetch_open_issues",
                       return_value=_open_issues(1, 2, 3)), \
                 patch("commands.auto_triage._batch_path", return_value=batch_file), \
                 patch("commands.auto_triage._answers_path",
                       return_value=Path(tmpdir) / "answers.json"), \
                 redirect_stdout(buf):
                auto_triage.run([])
            stored = json.loads(batch_file.read_text())
        self.assertEqual(stored["repo"], "org/myrepo")
        self.assertEqual(stored["folder"], "myrepo")
        self.assertEqual(len(stored["untracked"]), 2)  # 1 is tracked
        self.assertEqual(len(stored["tracks"]), 1)
        self.assertEqual(stored["tracks"][0]["slug"], "auth-flow")

    def test_limit_truncates_with_more_issues(self):
        """When untracked count exceeds --limit, show first N + truncation hint."""
        cfg = _make_cfg()
        tracks = [_make_track("auth-flow", "org/myrepo", [])]
        issues = _open_issues(*range(1, 110))  # 109 untracked
        rc, out, _ = _drive_prepare(["--limit=10"], cfg=cfg, tracks=tracks,
                                    open_issues=issues)
        self.assertEqual(rc, 0)
        self.assertIn("Issue 1", out)
        self.assertIn("Issue 10", out)
        self.assertNotIn("Issue 11", out)
        self.assertIn("and 99 more", out)
        self.assertIn("--limit", out)

    def test_limit_at_or_below_count_shows_all(self):
        """When untracked count is within --limit, show all with no truncation."""
        cfg = _make_cfg()
        tracks = [_make_track("auth-flow", "org/myrepo", [])]
        issues = _open_issues(1, 2, 3)
        rc, out, _ = _drive_prepare([], cfg=cfg, tracks=tracks,
                                    open_issues=issues)
        self.assertEqual(rc, 0)
        self.assertIn("Issue 1", out)
        self.assertIn("Issue 2", out)
        self.assertIn("Issue 3", out)
        self.assertNotIn("more issues", out)


# ---------------------------------------------------------------------------
# Apply step tests
# ---------------------------------------------------------------------------

class AutoTriageApplyTest(unittest.TestCase):

    def _simple_batch(self):
        return {
            "repo": "org/myrepo",
            "folder": "myrepo",
            "untracked": [{"number": 3, "title": "Issue 3"},
                          {"number": 4, "title": "Issue 4"}],
            "tracks": [{"slug": "auth-flow"}],
        }

    def test_apply_slots_issues_into_track(self):
        cfg = _make_cfg()
        track = _make_track("auth-flow", "org/myrepo", [1, 2])
        answers = [{"track": "auth-flow", "issues": [3, 4]}]

        with tempfile.TemporaryDirectory() as tmpdir:
            batch_file = Path(tmpdir) / "auto_triage.json"
            answers_file = Path(tmpdir) / "auto_triage.answers.json"
            batch_file.write_text(json.dumps(self._simple_batch()))
            answers_file.write_text(json.dumps(answers))

            with patch("commands.auto_triage._batch_path", return_value=batch_file), \
                 patch("commands.auto_triage._answers_path", return_value=answers_file), \
                 patch("commands.auto_triage.load_config", return_value=cfg), \
                 patch("commands.auto_triage.discover_tracks", return_value=[track]), \
                 patch("commands.auto_triage.parse_file",
                       return_value=(track.meta.copy(), "")) as mparse, \
                 patch("commands.auto_triage.write_file") as mwrite:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = auto_triage._apply(cfg)

        self.assertEqual(rc, 0)
        mwrite.assert_called_once()
        written_meta = mwrite.call_args[0][1]
        self.assertIn(3, written_meta["github"]["issues"])
        self.assertIn(4, written_meta["github"]["issues"])

    def test_apply_skips_already_tracked_issues(self):
        cfg = _make_cfg()
        track = _make_track("auth-flow", "org/myrepo", [1, 2, 3])  # 3 already there
        answers = [{"track": "auth-flow", "issues": [3, 4]}]  # 3 dup, 4 new

        batch = {
            "repo": "org/myrepo", "folder": "myrepo",
            "untracked": [{"number": 4, "title": "Issue 4"}],
            "tracks": [{"slug": "auth-flow"}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            batch_file = Path(tmpdir) / "b.json"
            answers_file = Path(tmpdir) / "a.json"
            batch_file.write_text(json.dumps(batch))
            answers_file.write_text(json.dumps(answers))

            with patch("commands.auto_triage._batch_path", return_value=batch_file), \
                 patch("commands.auto_triage._answers_path", return_value=answers_file), \
                 patch("commands.auto_triage.load_config", return_value=cfg), \
                 patch("commands.auto_triage.discover_tracks", return_value=[track]), \
                 patch("commands.auto_triage.parse_file",
                       return_value=(track.meta.copy(), "")), \
                 patch("commands.auto_triage.write_file") as mwrite:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = auto_triage._apply(cfg)

        self.assertEqual(rc, 0)
        # write_file called once for issue 4 (issue 3 not in batch untracked → no write)
        # Actually 4 is new, so write_file should be called
        mwrite.assert_called_once()
        out = buf.getvalue()
        self.assertIn("already present", out)  # note about #3

    def test_apply_unknown_track_in_answers_warns_and_skips(self):
        cfg = _make_cfg()
        track = _make_track("auth-flow", "org/myrepo", [1])
        answers = [{"track": "nonexistent-track", "issues": [3]}]

        batch = {
            "repo": "org/myrepo", "folder": "myrepo",
            "untracked": [{"number": 3, "title": "Issue 3"}],
            "tracks": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            batch_file = Path(tmpdir) / "b.json"
            answers_file = Path(tmpdir) / "a.json"
            batch_file.write_text(json.dumps(batch))
            answers_file.write_text(json.dumps(answers))

            with patch("commands.auto_triage._batch_path", return_value=batch_file), \
                 patch("commands.auto_triage._answers_path", return_value=answers_file), \
                 patch("commands.auto_triage.load_config", return_value=cfg), \
                 patch("commands.auto_triage.discover_tracks", return_value=[track]), \
                 patch("commands.auto_triage.parse_file", return_value=({}, "")), \
                 patch("commands.auto_triage.write_file") as mwrite:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = auto_triage._apply(cfg)

        self.assertEqual(rc, 0)
        mwrite.assert_not_called()
        self.assertIn("WARN", buf.getvalue())

    def test_apply_missing_answers_file_returns_error(self):
        cfg = _make_cfg()
        with patch("commands.auto_triage._answers_path",
                   return_value=Path("/nonexistent/answers.json")), \
             patch("commands.auto_triage._batch_path",
                   return_value=Path("/nonexistent/batch.json")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = auto_triage._apply(cfg)
        self.assertEqual(rc, 1)
        self.assertIn("ERROR", buf.getvalue())

    def test_apply_empty_answers_does_nothing(self):
        cfg = _make_cfg()
        track = _make_track("auth-flow", "org/myrepo", [1])
        batch = {
            "repo": "org/myrepo", "folder": "myrepo",
            "untracked": [{"number": 3, "title": "Issue 3"}],
            "tracks": [{"slug": "auth-flow"}],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_file = Path(tmpdir) / "b.json"
            answers_file = Path(tmpdir) / "a.json"
            batch_file.write_text(json.dumps(batch))
            answers_file.write_text(json.dumps([]))

            with patch("commands.auto_triage._batch_path", return_value=batch_file), \
                 patch("commands.auto_triage._answers_path", return_value=answers_file), \
                 patch("commands.auto_triage.load_config", return_value=cfg), \
                 patch("commands.auto_triage.discover_tracks", return_value=[track]), \
                 patch("commands.auto_triage.write_file") as mwrite:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = auto_triage._apply(cfg)

        self.assertEqual(rc, 0)
        mwrite.assert_not_called()
        self.assertIn("0 issue(s) assigned", buf.getvalue())


class AutoTriageJsonScanTest(unittest.TestCase):
    """--json scan mode (#241): emit a machine batch with a batch_id."""

    def test_json_mode_emits_batch_with_id_and_prompt(self):
        cfg = _make_cfg()
        tracks = [_make_track("auth-flow", "org/myrepo", [])]
        rc, out, _ = _drive_prepare(["--json"], cfg=cfg, tracks=tracks,
                                    open_issues=_open_issues(4501, 4502))
        self.assertEqual(rc, 0)
        data = json.loads(out.strip())  # stdout is a single JSON object
        self.assertIn("batch_id", data)
        self.assertTrue(data["batch_id"])
        self.assertEqual({i["number"] for i in data["untracked"]}, {4501, 4502})
        self.assertIn("prompt", data)
        self.assertIn("answers_path", data)
        # Track entries carry scope text for grounded matching.
        self.assertIn("scope", data["tracks"][0])


class AutoTriageV2AnswersTest(unittest.TestCase):
    """v2 abstain-first answers schema (#241) + back-compat with v1."""

    def _batch(self, nums, batch_id="abc123"):
        return {"batch_id": batch_id, "repo": "org/myrepo", "folder": "myrepo",
                "untracked": [{"number": n} for n in nums]}

    def test_v2_applies_only_clear_suggestions(self):
        cfg = _make_cfg()
        track = _make_track("auth-flow", "org/myrepo", [], slug="auth-flow")
        answers = {"version": 2, "batch_id": "abc123", "suggestions": [
            {"issue": 4501, "verdict": "suggest", "track": "auth-flow",
             "margin": "clear", "confidence": 0.9, "rationale": "label area/auth"},
            {"issue": 4502, "verdict": "suggest", "track": "auth-flow",
             "margin": "narrow", "confidence": 0.55, "rationale": "maybe"},
            {"issue": 4507, "verdict": "abstain", "rationale": "no fit"},
        ]}
        rc, mwrite, out = _drive_apply(cfg=cfg, tracks=[track],
                                       batch=self._batch([4501, 4502, 4507]),
                                       answers=answers)
        self.assertEqual(rc, 0)
        mwrite.assert_called_once()  # only the clear suggestion is written
        written = mwrite.call_args[0][1]["github"]["issues"]
        self.assertIn(4501, written)
        self.assertNotIn(4502, written)  # narrow margin → left untracked
        self.assertNotIn(4507, written)  # abstained → left untracked

    def test_v1_answers_still_apply(self):
        cfg = _make_cfg()
        track = _make_track("auth-flow", "org/myrepo", [], slug="auth-flow")
        answers = [{"track": "auth-flow", "issues": [4501]}]  # legacy shape
        rc, mwrite, out = _drive_apply(cfg=cfg, tracks=[track],
                                       batch=self._batch([4501]), answers=answers)
        self.assertEqual(rc, 0)
        mwrite.assert_called_once()
        self.assertIn(4501, mwrite.call_args[0][1]["github"]["issues"])

    def test_batch_id_mismatch_warns_but_applies(self):
        cfg = _make_cfg()
        track = _make_track("auth-flow", "org/myrepo", [], slug="auth-flow")
        answers = {"version": 2, "batch_id": "STALE", "suggestions": [
            {"issue": 4501, "verdict": "suggest", "track": "auth-flow",
             "margin": "clear", "rationale": "label area/auth"}]}
        rc, mwrite, out = _drive_apply(cfg=cfg, tracks=[track],
                                       batch=self._batch([4501], batch_id="abc123"),
                                       answers=answers)
        self.assertEqual(rc, 0)
        self.assertIn("older scan", out)
        mwrite.assert_called_once()


if __name__ == "__main__":
    unittest.main()
