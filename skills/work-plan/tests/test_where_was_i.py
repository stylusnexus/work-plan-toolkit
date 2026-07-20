"""Tests for the redesigned `where-was-i` / `orient` paste-block output.

The contract: ~15 lines total, header rule + meta + Track/Local paths +
last session timestamp+summary + next pick + behind-it (optional) +
local git (optional) + new-issues (optional) + bottom rule. NEVER a
dump of all open/closed issues.
"""
from __future__ import annotations

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


def _fake_issues(nums: list[int], milestone: str | None = None) -> list[dict]:
    titles = {
        4167: "feat(library): Armory Slice 3 — ArmoryCard + data-source cutover",
        4148: "fix(dashboard): CreditsPill shows '0 left' for super admin",
        4149: "fix(dashboard): Studio tier should show 'Unlimited'",
        4150: "fix(error): /contact 404 — replace with form",
    }
    ms_obj = {"title": milestone} if milestone else None
    return [{"number": n, "title": titles.get(n, f"issue {n}"), "state": "OPEN",
             "labels": [], "milestone": ms_obj, "url": "", "closedAt": None,
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


class WhereWasIClosedNextUpCase(unittest.TestCase):
    """next_up references issues that have shipped — orient must surface (closed)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)
        self.track_path = _make_track_file(self.repo_dir, next_up=[4348, 4349])

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }

        def _closed_issues(repo, nums):
            return [{"number": n, "title": f"shipped spec {n}", "state": "CLOSED",
                     "labels": [], "milestone": None, "url": "", "closedAt": "2026-05-02",
                     "body": ""} for n in nums]

        self._patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues", side_effect=_closed_issues),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks", return_value={}),
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

    def test_closed_next_up_annotated_inline(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = where_was_i.run(["demo-track"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Next pick: #4348", out)
        self.assertIn("(closed)", out)
        # Behind-it line should also pick up state.
        self.assertIn("#4349", out)
        self.assertEqual(out.count("(closed)"), 2)

    def test_closed_next_pick_shows_rotate_hint(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            where_was_i.run(["demo-track"])
        out = buf.getvalue()
        self.assertIn("next_up:[0] has shipped", out)
        self.assertIn("/work-plan handoff demo-track", out)


class WhereWasIMilestoneTagCase(unittest.TestCase):
    """next_up issues with milestones — orient must surface [vX.Y.Z] inline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "demo"
        self.repo_dir.mkdir(parents=True)
        self.track_path = _make_track_file(self.repo_dir, next_up=[4167, 4148])

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"demo": {"github": "stylusnexus/Demo"}},
        }

        def _milestoned(repo, nums):
            issues = _fake_issues(list(nums))
            for i in issues:
                if i["number"] == 4167:
                    i["milestone"] = {"title": "v0.4.0 — MVP Go-Live Gate"}
                elif i["number"] == 4148:
                    i["milestone"] = {"title": "v2.0.0 — Post-Launch"}
            return issues

        self._patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues", side_effect=_milestoned),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks", return_value={}),
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

    def test_milestone_prefix_on_next_pick_and_behind_it(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = where_was_i.run(["demo-track"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("Next pick: #4167  [v0.4.0]", out)
        self.assertIn("#4148  [v2.0.0]", out)


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


class OrientRepoFlagTest(unittest.TestCase):
    """orient command --repo=<key> and track@repo disambiguation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.notes_root.mkdir(parents=True)
        # Create two tracks with the same slug in different repos
        for folder in ("repo-a", "repo-b"):
            repo_dir = self.notes_root / folder
            repo_dir.mkdir(parents=True)
            _make_track_file(repo_dir, slug="feat-x")

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {
                "repo-a": {"github": "org/repo-a"},
                "repo-b": {"github": "org/repo-b"},
            },
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _drive(self, args, *, find_result=None):
        """Drive orient.run() with load_config mocked. If find_result is None
        (the normal case), discover_tracks runs for real against tmp files.
        When find_result is an Exception, we mock find_track_by_name."""
        patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues", return_value=[]),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks",
                       return_value={}),
            mock.patch("commands.where_was_i.current_branch", return_value=None),
            mock.patch("commands.where_was_i.commits_ahead", return_value=0),
            mock.patch("commands.where_was_i.uncommitted_file_count", return_value=0),
        ]
        if find_result is not None:
            patches.append(
                mock.patch("commands.where_was_i.find_track_by_name",
                           side_effect=find_result
                           if isinstance(find_result, Exception)
                           else None,
                           return_value=find_result
                           if not isinstance(find_result, Exception)
                           else None)
            )

        for p in patches:
            p.start()

        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = where_was_i.run(args)
            return rc, buf.getvalue()
        finally:
            for p in patches:
                p.stop()

    def test_repo_flag_passed_to_find_track(self):
        """--repo=<key> is passed as repo= kwarg to find_track_by_name."""
        find_mock = mock.MagicMock()
        find_mock.return_value = None  # We just care about how it was called

        patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.find_track_by_name", find_mock),
            mock.patch("commands.where_was_i.discover_tracks", return_value=[]),
            mock.patch("commands.where_was_i.fetch_issues", return_value=[]),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks",
                       return_value={}),
            mock.patch("commands.where_was_i.current_branch", return_value=None),
            mock.patch("commands.where_was_i.commits_ahead", return_value=0),
            mock.patch("commands.where_was_i.uncommitted_file_count", return_value=0),
        ]
        for p in patches:
            p.start()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                where_was_i.run(["feat-x", "--repo=repo-a"])
        finally:
            for p in patches:
                p.stop()

        call_kwargs = find_mock.call_args.kwargs
        self.assertEqual(call_kwargs.get("repo"), "repo-a")

    def test_at_syntax_passed_to_find_track(self):
        """feat-x@repo-a positional → repo='repo-a' passed to find_track_by_name."""
        find_mock = mock.MagicMock()
        find_mock.return_value = None

        patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.find_track_by_name", find_mock),
            mock.patch("commands.where_was_i.discover_tracks", return_value=[]),
            mock.patch("commands.where_was_i.fetch_issues", return_value=[]),
            mock.patch("commands.where_was_i.find_new_issues_for_tracks",
                       return_value={}),
            mock.patch("commands.where_was_i.current_branch", return_value=None),
            mock.patch("commands.where_was_i.commits_ahead", return_value=0),
            mock.patch("commands.where_was_i.uncommitted_file_count", return_value=0),
        ]
        for p in patches:
            p.start()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                where_was_i.run(["feat-x@repo-a"])
        finally:
            for p in patches:
                p.stop()

        call_kwargs = find_mock.call_args.kwargs
        self.assertEqual(call_kwargs.get("repo"), "repo-a")

    def test_ambiguous_error_returns_rc1(self):
        """AmbiguousTrackError → prints message, returns 1."""
        from lib.tracks import Track, AmbiguousTrackError

        t1 = Track(path=Path("/tmp/fake/repo-a/feat-x.md"), name="feat-x",
                   has_frontmatter=True, needs_init=False, needs_filing=False,
                   repo="org/a", folder="repo-a", meta={"track": "feat-x", "status": "active"})
        t2 = Track(path=Path("/tmp/fake/repo-b/feat-x.md"), name="feat-x",
                   has_frontmatter=True, needs_init=False, needs_filing=False,
                   repo="org/b", folder="repo-b", meta={"track": "feat-x", "status": "active"})
        err = AmbiguousTrackError("feat-x", [t1, t2])

        rc, out = self._drive(["feat-x"], find_result=err)
        self.assertEqual(rc, 1)
        self.assertIn("ambiguous", out.lower())


class OrientInProgressTest(unittest.TestCase):
    def test_next_pick_marked_in_progress(self):
        from types import SimpleNamespace
        track = SimpleNamespace(
            name="alpha", repo="o/r", local_path=Path("/repo"), path=Path("/n/alpha.md"),
            body="", meta={"track": "alpha", "launch_priority": "P1",
                           "milestone_alignment": "—",
                           "github": {"issues": [271]}, "next_up": [271]})
        issue = {"number": 271, "title": "x", "state": "open", "labels": [], "milestone": None}
        with mock.patch("commands.where_was_i.fetch_issues", return_value=[issue]), \
             mock.patch("commands.where_was_i.hot_issue_numbers", return_value={271}), \
             mock.patch("commands.where_was_i.current_branch", return_value=None), \
             mock.patch("commands.where_was_i.find_new_issues_for_tracks", return_value={}):
            out = io.StringIO()
            with redirect_stdout(out):
                where_was_i._orient_track(track)
        self.assertIn("in-progress", out.getvalue())


class OrientBlockedByTest(unittest.TestCase):
    def test_next_pick_shows_blocked_by(self):
        from types import SimpleNamespace
        track = SimpleNamespace(name="alpha", repo="o/r", local_path=None,
                                path=Path("/n/alpha.md"), body="",
                                meta={"track": "alpha", "launch_priority": "P1",
                                      "milestone_alignment": "—",
                                      "github": {"issues": [5]}, "next_up": [5], "blockers": []})
        issue = {"number": 5, "title": "x", "state": "open", "labels": [],
                 "blocked_by": [{"number": 9, "repo": "o/r", "title": "dep"}], "blocking": []}
        with mock.patch("commands.where_was_i.fetch_issues", return_value=[issue]), \
             mock.patch("commands.where_was_i.hot_issue_numbers", return_value=set()), \
             mock.patch("commands.where_was_i.current_branch", return_value=None), \
             mock.patch("commands.where_was_i.find_new_issues_for_tracks", return_value={}):
            out = io.StringIO()
            with redirect_stdout(out):
                from commands import where_was_i
                where_was_i._orient_track(track)
        self.assertIn("blocked by #9", out.getvalue())

    def _orient_with_blocked_by(self, blocked_by, blockers):
        from types import SimpleNamespace
        track = SimpleNamespace(name="alpha", repo="o/r", local_path=None,
                                path=Path("/n/alpha.md"), body="",
                                meta={"track": "alpha", "launch_priority": "P1",
                                      "milestone_alignment": "—",
                                      "github": {"issues": [5]}, "next_up": [5],
                                      "blockers": blockers})
        issue = {"number": 5, "title": "x", "state": "open", "labels": [],
                 "blocked_by": blocked_by, "blocking": []}
        with mock.patch("commands.where_was_i.fetch_issues", return_value=[issue]), \
             mock.patch("commands.where_was_i.hot_issue_numbers", return_value=set()), \
             mock.patch("commands.where_was_i.current_branch", return_value=None), \
             mock.patch("commands.where_was_i.find_new_issues_for_tracks", return_value={}):
            out = io.StringIO()
            with redirect_stdout(out):
                from commands import where_was_i
                where_was_i._orient_track(track)
        return out.getvalue()

    def test_cross_repo_blocked_by_shows_qualified_ref(self):
        # A cross-repo edge renders owner/repo#N, not a bare #N.
        out = self._orient_with_blocked_by(
            [{"number": 9, "repo": "other/repo", "title": "dep"}], [])
        self.assertIn("blocked by other/repo#9", out)

    def test_same_repo_edge_in_manual_blockers_is_suppressed(self):
        # A same-repo edge whose number is a manual blocker is owned by the
        # "Blocker:" line, so it is not re-annotated.
        out = self._orient_with_blocked_by(
            [{"number": 9, "repo": "o/r", "title": "dep"}], [9])
        self.assertNotIn("blocked by", out)

    def test_cross_repo_edge_not_suppressed_by_same_number_blocker(self):
        # A manual blocker #9 means o/r#9; a cross-repo other/repo#9 is a
        # different issue and must still be annotated.
        out = self._orient_with_blocked_by(
            [{"number": 9, "repo": "other/repo", "title": "dep"}], [9])
        self.assertIn("blocked by other/repo#9", out)


class WhereWasIConvergenceReferenceCase(unittest.TestCase):
    """A convergence track (github.issues: []) whose next_up holds a
    cross-track reference must still show that reference as the next pick with
    live GitHub state — orient fetches the next_up numbers directly, so it is
    reference-aware without needing them in github.issues."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "sound"
        self.repo_dir.mkdir(parents=True)

        meta = {
            "track": "mvp",
            "status": "active",
            "launch_priority": "P0",
            "milestone_alignment": "mvp",
            "github": {
                "repo": "evemcgivern/soundstellation",
                "issues": [],
                "references": [165, 166, 18],
                "branches": [],
            },
            "next_up": [165, 166],
            "last_touched": "2026-04-28T19:36",
        }
        self.track_path = self.repo_dir / "mvp.md"
        write_file(self.track_path, meta, "\n# MVP convergence\n\nBody.\n")

        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"sound": {"github": "evemcgivern/soundstellation"}},
        }

        def _fetch(repo, nums):
            titles = {165: "release blocker", 166: "cutover", 18: "polish"}
            return [{"number": n, "title": titles.get(n, f"issue {n}"),
                     "state": "OPEN", "labels": [], "milestone": None,
                     "url": "", "closedAt": None, "body": ""} for n in nums]

        self._patches = [
            mock.patch("commands.where_was_i.load_config", return_value=self.cfg),
            mock.patch("commands.where_was_i.fetch_issues", side_effect=_fetch),
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

    def test_referenced_next_up_shown_as_next_pick_with_live_state(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = where_was_i.run(["mvp"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Next pick: #165", out)
        self.assertIn("release blocker", out)
        self.assertIn("Behind it:", out)
        self.assertIn("#166", out)
        self.assertNotIn("(none set", out)


if __name__ == "__main__":
    unittest.main()
