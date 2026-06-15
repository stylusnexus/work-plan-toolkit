"""Tests for `handoff --suggest-next` — the read-only JSON suggestion mode (#274).

The VS Code native auto-next picker needs the algorithmic next_up suggestion
WITHOUT a write or a TTY prompt (the CLI's prompt helpers no-op under VS Code's
non-TTY stdin). `--suggest-next` computes the same sibling-filtered suggestion as
`--auto-next` and prints it as JSON; the extension renders + confirms it and
writes back via `--set-next`. These tests assert: valid JSON shape, sibling-claim
skips surface in `skipped` (not written), no frontmatter is mutated, and the
soft-error payloads (no repo / no issues) stay parseable with exit 0.
"""
import io
import json
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
        "github": {"repo": repo,
                   "issues": list([100, 200] if issues is None else issues),
                   "branches": []},
        "next_up": list(next_up or []),
    }
    path = dir_path / f"{slug}.md"
    write_file(path, meta, f"\n# {slug}\n\nBody.\n")
    return path


def _open_issue(num: int, *, priority: str = "P1", milestone=None) -> dict:
    return {
        "number": num,
        "title": f"issue-{num}",
        "state": "OPEN",
        "labels": [{"name": f"priority/{priority}"}],
        "updatedAt": "2026-04-30T00:00:00Z",
        "milestone": milestone,
    }


class SuggestNextJsonTest(unittest.TestCase):
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

    def _run(self, track_name, *, issues_response):
        buf = io.StringIO()
        with mock.patch("commands.handoff.fetch_issues", return_value=issues_response), \
             redirect_stdout(buf):
            rc = handoff.run([track_name, "--suggest-next"])
        return rc, buf.getvalue()

    def test_emits_valid_json_with_decorated_suggestions(self):
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200])
        rc, out = self._run("track-a",
                            issues_response=[_open_issue(100, milestone={"title": "v1.0.0"}),
                                             _open_issue(200)])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["track"], "track-a")
        self.assertEqual(payload["repo"], "stylusnexus/Demo")
        nums = [s["number"] for s in payload["suggested"]]
        self.assertEqual(sorted(nums), [100, 200])
        first = next(s for s in payload["suggested"] if s["number"] == 100)
        self.assertEqual(first["title"], "issue-100")
        self.assertEqual(first["priority"], "P1")
        self.assertEqual(first["milestone"], "v1.0.0")

    def test_read_only_does_not_write_next_up(self):
        target = _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo",
                             issues=[100, 200], next_up=[7])
        rc, out = self._run("track-a",
                            issues_response=[_open_issue(100), _open_issue(200)])
        self.assertEqual(rc, 0)
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [7])  # untouched by a read-only suggest

    def test_sibling_claimed_issue_lands_in_skipped_not_suggested(self):
        _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo", issues=[100, 200])
        _make_track(self.repo_dir, "track-b", repo="stylusnexus/Demo", next_up=[100])
        rc, out = self._run("track-a",
                            issues_response=[_open_issue(100), _open_issue(200)])
        payload = json.loads(out)
        self.assertEqual([s["number"] for s in payload["suggested"]], [200])
        self.assertEqual(payload["skipped"], [{"number": 100, "claimed_by": "track-b"}])

    def test_no_issues_attached_is_soft_error_with_empty_suggested(self):
        _make_track(self.repo_dir, "track-a", repo="stylusnexus/Demo", issues=[])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = handoff.run(["track-a", "--suggest-next"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["suggested"], [])
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
