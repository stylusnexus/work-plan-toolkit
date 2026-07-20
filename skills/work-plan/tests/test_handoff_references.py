"""Tests for convergence-track references in `handoff`.

A convergence track carries `github.issues: []` and lists cross-track scope in
`github.references`. Those issues are owned by specialist tracks; the
convergence track references them to surface the release scope. `handoff` must:

  1. Fetch live GitHub state for referenced issues (not just owned `issues`),
     so "WHAT'S STILL OPEN" reflects open references instead of claiming the
     track is ready to close.
  2. NOT prompt "Apply anyway?" when `--set-next` lists a referenced issue that
     is (naturally) already next_up on its owning specialist track — a
     reference is legitimate cross-track scope, not a duplicate-membership
     collision. This makes `--set-next` usable non-interactively on a
     convergence track.
  3. NOT write referenced issues into the track's owned `github.issues` list or
     its canonical body table (ownership stays with the specialist tracks).
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
                issues=None, references=None, next_up=None) -> Path:
    github = {"repo": repo, "issues": list(issues or []), "branches": []}
    if references is not None:
        github["references"] = list(references)
    meta = {
        "track": slug,
        "status": status,
        "launch_priority": "P1",
        "github": github,
        "next_up": list(next_up or []),
    }
    body = f"\n# {slug}\n\nBody.\n"
    path = dir_path / f"{slug}.md"
    write_file(path, meta, body)
    return path


def _issue(num, state="OPEN", title=None):
    return {"number": num, "title": title or f"issue {num}", "state": state,
            "milestone": None, "assignees": []}


class HandoffReferencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes_root = Path(self.tmp.name) / "notes_root"
        self.repo_dir = self.notes_root / "sound"
        self.repo_dir.mkdir(parents=True)
        self.cfg = {
            "notes_root": str(self.notes_root),
            "repos": {"sound": {"github": "evemcgivern/soundstellation"}},
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

    # --- bug 1: references surface in "WHAT'S STILL OPEN" -----------------

    def test_open_references_shown_as_still_open(self):
        """Convergence track (issues:[], open references) must show the open
        references under WHAT'S STILL OPEN — not 'no open items'."""
        _make_track(self.repo_dir, "mvp", repo="evemcgivern/soundstellation",
                    issues=[], references=[165, 166, 18], next_up=[165])
        fetched = [_issue(165, "OPEN", "release blocker"),
                   _issue(166, "CLOSED", "shipped"),
                   _issue(18, "OPEN", "polish")]
        with mock.patch("commands.handoff.fetch_issues", return_value=fetched):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = handoff.run(["mvp"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertNotIn("no open items", out)
        self.assertIn("#165", out)
        self.assertIn("#18", out)

    def test_references_are_fetched_for_live_state(self):
        """fetch_issues must be asked for the referenced numbers even though
        github.issues is empty."""
        _make_track(self.repo_dir, "mvp", repo="evemcgivern/soundstellation",
                    issues=[], references=[165, 166], next_up=[165])
        with mock.patch("commands.handoff.fetch_issues",
                        return_value=[_issue(165), _issue(166)]) as m:
            buf = io.StringIO()
            with redirect_stdout(buf):
                handoff.run(["mvp"])
        # The scope passed to fetch must include the references.
        requested = set(m.call_args[0][1])
        self.assertEqual(requested, {165, 166})

    # --- bug 2: no collision prompt for the track's own references -------

    def test_set_next_reference_does_not_prompt(self):
        """A referenced issue that is next_up on its OWNING specialist track
        must not trigger the collision prompt on the convergence track."""
        _make_track(self.repo_dir, "mvp", repo="evemcgivern/soundstellation",
                    issues=[], references=[165, 166, 18])
        # Owning specialist track: owns + queues #165 and #18.
        _make_track(self.repo_dir, "specialist",
                    repo="evemcgivern/soundstellation",
                    issues=[165, 18], next_up=[165, 18])

        target = self.repo_dir / "mvp.md"
        with mock.patch("commands.handoff.fetch_issues", return_value=[]), \
             mock.patch("commands.handoff.prompt_input") as mock_prompt:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = handoff.run(["mvp", "--set-next", "165,18,166"])
        self.assertEqual(rc, 0)
        mock_prompt.assert_not_called()
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [165, 18, 166])

    def test_non_reference_collision_still_prompts(self):
        """Ordinary duplicate protection is unchanged: a proposed number that is
        NOT one of the track's references but IS next_up on a sibling still
        prompts (and 'n' skips)."""
        # mvp references 165 only; 999 is neither owned nor referenced here.
        _make_track(self.repo_dir, "mvp", repo="evemcgivern/soundstellation",
                    issues=[], references=[165], next_up=[])
        _make_track(self.repo_dir, "specialist",
                    repo="evemcgivern/soundstellation",
                    issues=[999], next_up=[999])

        target = self.repo_dir / "mvp.md"
        with mock.patch("commands.handoff.fetch_issues", return_value=[]), \
             mock.patch("commands.handoff.prompt_input", return_value="n") as mock_prompt:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = handoff.run(["mvp", "--set-next", "165,999"])
        self.assertEqual(rc, 0)
        mock_prompt.assert_called_once()  # 999 still flagged
        meta, _ = parse_file(target)
        self.assertEqual(meta["next_up"], [])  # declined → unchanged

    # --- ownership is not silently rewritten ----------------------------

    def test_references_not_promoted_to_owned_issues(self):
        """--set-next on a convergence track must leave github.issues empty and
        github.references intact — no silent ownership promotion."""
        _make_track(self.repo_dir, "mvp", repo="evemcgivern/soundstellation",
                    issues=[], references=[165, 166])
        target = self.repo_dir / "mvp.md"
        with mock.patch("commands.handoff.fetch_issues", return_value=[]), \
             mock.patch("commands.handoff.prompt_input"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                handoff.run(["mvp", "--set-next", "165,166"])
        meta, _ = parse_file(target)
        self.assertEqual(meta["github"]["issues"], [])
        self.assertEqual(meta["github"]["references"], [165, 166])

    def test_references_not_appended_to_canonical_body_table(self):
        """A full derived handoff must not inject referenced issues as owned
        rows in the track's canonical status table (that would claim
        ownership in the body)."""
        _make_track(self.repo_dir, "mvp", repo="evemcgivern/soundstellation",
                    issues=[], references=[165], next_up=[165])
        target = self.repo_dir / "mvp.md"
        with mock.patch("commands.handoff.fetch_issues",
                        return_value=[_issue(165, "OPEN")]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                handoff.run(["mvp"])
        _, body = parse_file(target)
        # sync_missing_rows is owned-scoped, so #165 must not appear as a body
        # table row (the body had no table and none should be synthesized for a
        # reference).
        self.assertNotIn("| #165", body)
        self.assertNotIn("| 165", body)


if __name__ == "__main__":
    unittest.main()
