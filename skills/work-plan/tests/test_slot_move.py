"""Tests for slot's prior-ownership detection (issue #62).

Before #62, `slot` was add-only — running `slot 4562 chat-nlu` while #4562 was
already listed in `ai-generators.md` frontmatter would leave the issue in BOTH
tracks. The only fix was hand-editing YAML, which SKILL.md explicitly warns
against. These tests pin the new behavior: detect prior ownership, prompt to
move, and only mutate source frontmatter on explicit 'y' so non-interactive
runs preserve the pre-#62 add-only semantics.
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
    def _drive(self, *, tracks, args, user_choice=""):
        cfg = {"notes_root": "/tmp/fake-notes",
               "repos": {"ok": {"github": "ok/ok"}}}
        gh_proc = MagicMock(returncode=0, stdout="{}", stderr="")
        with patch("commands.slot.subprocess.run", return_value=gh_proc), \
             patch("commands.slot.load_config", return_value=cfg), \
             patch("commands.slot.discover_tracks", return_value=tracks), \
             patch("commands.slot.prompt_input", return_value=user_choice) as mp, \
             patch("commands.slot.write_file") as mw:
            rc = slot.run(args)
        return rc, mw, mp

    def test_no_prior_ownership_writes_only_target(self):
        target = _track(name="alpha", repo="ok/ok", issues=[])
        rc, mw, mp = self._drive(tracks=[target], args=["100", "alpha"])
        self.assertEqual(rc, 0)
        mp.assert_not_called()
        mw.assert_called_once()
        self.assertEqual(100, target.meta["github"]["issues"][0])

    def test_prior_ownership_with_yes_removes_from_source(self):
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw, mp = self._drive(
            tracks=[source, target], args=["42", "beta"], user_choice="y",
        )
        self.assertEqual(rc, 0)
        mp.assert_called_once()
        self.assertEqual(2, mw.call_count, "source + target should both be written")
        self.assertEqual([], source.meta["github"]["issues"])
        self.assertEqual([42], target.meta["github"]["issues"])

    def test_prior_ownership_with_no_preserves_add_only(self):
        # User declines the move → pre-#62 behavior: target gets the issue,
        # source is untouched (duplicated state that reconcile can later FLAG).
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw, mp = self._drive(
            tracks=[source, target], args=["42", "beta"], user_choice="n",
        )
        self.assertEqual(rc, 0)
        mp.assert_called_once()
        mw.assert_called_once()
        self.assertEqual([42], source.meta["github"]["issues"])
        self.assertEqual([42], target.meta["github"]["issues"])

    def test_non_interactive_eof_preserves_add_only(self):
        # prompt_input returns "" on EOF. ""→"" is not "y" so the move is
        # declined and the pre-#62 add-only behavior holds. This is the
        # safe-by-default contract scripts can rely on.
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw, _ = self._drive(
            tracks=[source, target], args=["42", "beta"], user_choice="",
        )
        self.assertEqual(rc, 0)
        mw.assert_called_once()
        self.assertEqual([42], source.meta["github"]["issues"])

    def test_already_in_target_short_circuits(self):
        # Issue already listed in target → no prompt, no write.
        source = _track(name="alpha", repo="ok/ok", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[42])
        rc, mw, mp = self._drive(
            tracks=[source, target], args=["42", "beta"], user_choice="y",
        )
        self.assertEqual(rc, 0)
        mp.assert_not_called()
        mw.assert_not_called()

    def test_cross_repo_issue_not_detected_as_prior_owner(self):
        # Same number in a different repo is a different issue. The prior-
        # owner sweep MUST filter by track.repo or it will spuriously offer
        # to move unrelated issues across repos.
        other_repo = _track(name="alpha", repo="other/repo", issues=[42])
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, mw, mp = self._drive(
            tracks=[other_repo, target], args=["42", "beta"], user_choice="y",
        )
        self.assertEqual(rc, 0)
        mp.assert_not_called()
        mw.assert_called_once()
        self.assertEqual([42], other_repo.meta["github"]["issues"])

    def test_inactive_source_not_detected_as_prior_owner(self):
        # Archived/parked tracks shouldn't be candidates — moving FROM a
        # closed track is the wrong mental model; that's a reopen, not a slot.
        parked = _track(name="alpha", repo="ok/ok", issues=[42], status="parked")
        target = _track(name="beta", repo="ok/ok", issues=[])
        rc, _, mp = self._drive(
            tracks=[parked, target], args=["42", "beta"], user_choice="y",
        )
        self.assertEqual(rc, 0)
        mp.assert_not_called()
        self.assertEqual([42], parked.meta["github"]["issues"])


if __name__ == "__main__":
    unittest.main()
