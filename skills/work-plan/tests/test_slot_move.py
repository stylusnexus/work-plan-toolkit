"""Tests for slot's prior-ownership detection (issue #62).

Before #62, `slot` was add-only — running `slot 4562 chat-nlu` while #4562 was
already listed in `ai-generators.md` frontmatter would leave the issue in BOTH
tracks. The only fix was hand-editing YAML, which SKILL.md explicitly warns
against. These tests pin the non-interactive behavior introduced in #87:
detect prior ownership, and move only on explicit --move so non-interactive
runs preserve add-only semantics by default.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import slot


def _track(*, name, repo, issues, status="active"):
    return SimpleNamespace(
        name=name,
        path=Path(f"/tmp/fake/{name}.md"),
        body="# fake",
        meta={
            "track": name,
            "status": status,
            "github": {"repo": repo, "issues": list(issues)},
        },
        has_frontmatter=True,
        repo=repo,
    )


class SlotMoveTest(unittest.TestCase):
    def _drive(self, *, tracks, args):
        cfg = {"notes_root": "/tmp/fake-notes",
               "repos": {"ok": {"github": "ok/ok"}}}
        gh_proc = MagicMock(returncode=0, stdout="{}", stderr="")
        # Writes go through lib.membership_guard now; return each track's own
        # meta/body from parse_file so the guard mutates them in place.
        by_path = {str(t.path): t for t in tracks}

        def fake_parse(p):
            t = by_path[str(p)]
            return (t.meta, t.body)

        with patch("commands.slot.subprocess.run", return_value=gh_proc), \
             patch("commands.slot.load_config", return_value=cfg), \
             patch("commands.slot.discover_tracks", return_value=tracks), \
             patch("lib.write_guard.repo_visibility", return_value="PRIVATE"), \
             patch("lib.membership_guard.parse_file", side_effect=fake_parse), \
             patch("lib.membership_guard.write_file") as mw:
            rc = slot.run(args)
        return rc, mw

    def test_no_prior_ownership_writes_only_target(self):
        target = _track(name="alpha", repo="ok/ok", issues=[])
        rc, mw = self._drive(tracks=[target], args=["100", "alpha"])
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertEqual(100, target.meta["github"]["issues"][0])

    def test_prior_ownership_with_move_flag_removes_from_source(self):
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw = self._drive(
            tracks=[source, target], args=["42", "beta", "--move"],
        )
        self.assertEqual(rc, 0)
        self.assertEqual(2, mw.call_count, "source + target should both be written")
        self.assertEqual([], source.meta["github"]["issues"])
        self.assertEqual([42], target.meta["github"]["issues"])

    def test_prior_ownership_without_move_flag_preserves_add_only(self):
        # Default (no --move flag) → pre-#62 behavior: target gets the issue,
        # source is untouched (duplicated state that reconcile can later FLAG).
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw = self._drive(
            tracks=[source, target], args=["42", "beta"],
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertEqual([42], source.meta["github"]["issues"])
        self.assertEqual([42], target.meta["github"]["issues"])

    def test_explicit_no_move_flag_preserves_add_only(self):
        # --no-move behaves identically to the default.
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw = self._drive(
            tracks=[source, target], args=["42", "beta", "--no-move"],
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertEqual([42], source.meta["github"]["issues"])

    def test_already_in_target_short_circuits(self):
        # Issue already listed in target → no write.
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[42])
        rc, mw = self._drive(
            tracks=[source, target], args=["42", "beta"],
        )
        self.assertEqual(rc, 0)
        mw.assert_not_called()

    def test_cross_repo_issue_not_detected_as_prior_owner(self):
        # Same number in a different repo is a different issue. The prior-
        # owner sweep MUST filter by track.repo or it will spuriously offer
        # to move unrelated issues across repos.
        other_repo = _track(name="alpha", repo="other/repo", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw = self._drive(
            tracks=[other_repo, target], args=["42", "beta"],
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertEqual([42], other_repo.meta["github"]["issues"])

    def test_inactive_source_not_detected_as_prior_owner(self):
        # Archived/parked tracks shouldn't be candidates — moving FROM a
        # closed track is the wrong mental model; that's a reopen, not a slot.
        parked = _track(name="alpha", repo="ok/ok", issues=[42], status="parked")
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw = self._drive(
            tracks=[parked, target], args=["42", "beta"],
        )
        self.assertEqual(rc, 0)
        self.assertEqual([42], parked.meta["github"]["issues"])


if __name__ == "__main__":
    unittest.main()
