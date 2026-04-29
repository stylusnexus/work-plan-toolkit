"""Tests for the redesigned `where-was-i` / `orient` paste-block output.

The contract: ~15 lines total, header rule + meta + Track/Local paths +
last session timestamp+summary + next pick + behind-it (optional) +
local git (optional) + new-issues (optional) + bottom rule. NEVER a
dump of all open/closed issues.
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

from commands import where_was_i
from lib.frontmatter import write_file


def _make_track_file(dir_path: Path, slug: str = "demo-track",
                     *, with_session: bool = True,
                     next_up: list[int] | None = None,
                     last_handoff: str | None = "2026-04-28T19:36") -> Path:
    """Build a minimal track .md the where-was-i command can resolve."""
    meta = {
        "track": slug,
        "status": "active",
        "launch_priority": "P0",
        "milestone_alignment": "v0.4.0",
        "github": {
            "repo": "stylusnexus/Demo",
            "issues": [4167, 4148, 4149, 4150],
            "branches": [],
        },
        "next_up": next_up if next_up is not None else [4167, 4148, 4149, 4150],
        "last_touched": "2026-04-28T19:36",
        "last_handoff": last_handoff,
    }
    body_parts = ["", "# Demo track", ""]
    if with_session:
        body_parts.extend([
            "### Session — 2026-04-28 19:36",
            "",
            "- Touched: (no git activity attributed; 32 open from GitHub)",
            "- Next: #4167",
            "",
        ])
    body = "\n".join(body_parts)
    path = dir_path / f"{slug}.md"
    write_file(path, meta, body)
    return path


def _fake_issues(nums: list[int]) -> list[dict]:
    titles = {
        4167: "feat(library): Armory Slice 3 — ArmoryCard + data-source cutover",
        4148: "fix(dashboard): CreditsPill shows '0 left' for super admin",
        4149: "fix(dashboard): Studio tier should show 'Unlimited'",
        4150: "fix(error): /contact 404 — replace with form",
    }
    return [{"number": n, "title": titles.get(n, f"issue {n}"), "state": "OPEN",
             "labels": [], "milestone": None, "url": "", "closedAt": None,
             "body": ""} for n in nums]


class WhereWasIBaseCase(unittest.TestCase):
    """Default fixture: full output with all sections present."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)
        self.track_path = _make_track_file(self.repo_dir)

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }
        self._patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues",
                       side_effect=lambda repo, nums: _fake_issues(list(nums))),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks",
                       return_value={}),
            # No local clone in test fixtures — make git helpers no-op cleanly.
            mock.patch("commands.where_was_i.current_branch", return_value=None),
            mock.patch("commands.where_was_i.commits_ahead", return_value=0),
            mock.patch("commands.where_was_i.uncommitted_file_count", return_value=0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _run(self, args=None) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = where_was_i.run(args or ["demo-track"])
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_full_output_contains_all_required_sections(self):
        out = self._run()
        # Header rule + slug
        self.assertIn("─── demo-track ", out)
        # Meta line
        self.assertIn("Priority: P0", out)
        self.assertIn("Milestone: v0.4.0", out)
        self.assertIn("Repo: stylusnexus/Demo", out)
        # Track path
        self.assertIn("Track:  ", out)
        self.assertIn("demo-track.md", out)
        # Last session — timestamp + summary line
        self.assertIn("Last session (2026-04-28 19:36):", out)
        self.assertIn("(no git activity attributed; 32 open from GitHub)", out)
        # Next pick
        self.assertIn("Next pick: #4167", out)
        self.assertIn("Armory Slice 3", out)
        # Behind it (3 items)
        self.assertIn("Behind it:", out)
        self.assertIn("#4148", out)
        self.assertIn("#4149", out)
        self.assertIn("#4150", out)

    def test_output_is_under_25_lines(self):
        """Paste-block contract: tight summary, not a dump."""
        out = self._run()
        line_count = len(out.splitlines())
        self.assertLess(line_count, 25,
                        f"output should be a tight paste block; got {line_count} lines:\n{out}")

    def test_output_has_no_closed_issue_dump(self):
        """The whole point of the redesign — no 'Current issue state' section."""
        out = self._run()
        self.assertNotIn("Current issue state", out)
        self.assertNotIn("closed", out.lower())
        self.assertNotIn("merged", out.lower())


class WhereWasIEmptyNextUpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)
        self.track_path = _make_track_file(self.repo_dir, next_up=[])

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }
        self._patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues", return_value=[]),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks",
                       return_value={}),
            mock.patch("commands.where_was_i.current_branch", return_value=None),
            mock.patch("commands.where_was_i.commits_ahead", return_value=0),
            mock.patch("commands.where_was_i.uncommitted_file_count", return_value=0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_empty_next_up_shows_helpful_prompt(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = where_was_i.run(["demo-track"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Next pick: (none set", out)
        # Should NOT show "Behind it:" when next_up is empty
        self.assertNotIn("Behind it:", out)


class WhereWasINoLocalPathCase(unittest.TestCase):
    """Track resolves but has no local clone — Local: line should be omitted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)
        self.track_path = _make_track_file(self.repo_dir)

        # No `local:` configured for the demo repo — track.local_path is None.
        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }
        self._patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues",
                       side_effect=lambda repo, nums: _fake_issues(list(nums))),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks",
                       return_value={}),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_no_local_path_omits_local_lines(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = where_was_i.run(["demo-track"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        # The "Local: <path>" header line should NOT appear
        self.assertNotIn("Local:  /", out)
        # Nor the local-git status footer ("Local: on <branch>")
        self.assertNotIn("Local: on ", out)


class WhereWasINoSessionLogCase(unittest.TestCase):
    """No prior `### Session — …` block — print '(none yet)' fallback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)
        self.track_path = _make_track_file(self.repo_dir, with_session=False,
                                           last_handoff=None)

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }
        self._patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues",
                       side_effect=lambda repo, nums: _fake_issues(list(nums))),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks",
                       return_value={}),
            mock.patch("commands.where_was_i.current_branch", return_value=None),
            mock.patch("commands.where_was_i.commits_ahead", return_value=0),
            mock.patch("commands.where_was_i.uncommitted_file_count", return_value=0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def test_no_session_log_says_none_yet(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = where_was_i.run(["demo-track"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Last session: (none yet)", out)


if __name__ == "__main__":
    unittest.main()
