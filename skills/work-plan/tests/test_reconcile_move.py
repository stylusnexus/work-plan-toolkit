"""Cross-track auto-move detection in reconcile (#163).

When an issue sits in track A's frontmatter but is now labeled for exactly one
OTHER active track B in the same repo (a relabel), reconcile proposes a MOVE:
remove from A, add to B — instead of leaving it as a dangling FLAG on A and a
fresh ADD on B (which would duplicate it across both tracks).

All gh calls are mocked; tests run offline. needs_confirm is patched so the
public-repo gate is exercised without a real `gh repo view`.
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import reconcile


def _track(*, slug, repo="ok/ok", issues=None):
    return SimpleNamespace(
        name=slug,
        path=Path(f"/tmp/fake/{slug}.md"),
        body="# fake",
        meta={"track": slug, "status": "active",
              "github": {"repo": repo, "issues": list(issues or [])}},
        has_frontmatter=True,
        repo=repo,
    )


class _Harness:
    """Drives reconcile --all over a set of tracks with a label→issues map.

    `labeled` maps a GitHub label string to the list of issue dicts that
    `gh issue/pr list --label <label>` should return.
    """

    def __init__(self, tracks, labeled, *, private=True):
        self.tracks = tracks
        self.labeled = labeled
        self.private = private
        self.writes = []  # (path_name, issues) per write_file call

    def _fake_run(self, argv, *a, **kw):
        out = []
        if "--label" in argv and argv[1] == "issue":  # only count issues once
            lab = argv[argv.index("--label") + 1]
            out = self.labeled.get(lab, [])
        return MagicMock(returncode=0, stdout=json.dumps(out), stderr="")

    def _fake_write(self, path, meta, body):
        self.writes.append((path.name, list(meta.get("github", {}).get("issues") or [])))

    def run(self, extra_args=None):
        cfg = {"notes_root": "/tmp/n", "repos": {"ok": {"github": "ok/ok"}}}
        with patch("commands.reconcile.subprocess.run", side_effect=self._fake_run), \
             patch("commands.reconcile.load_config", return_value=cfg), \
             patch("commands.reconcile.discover_tracks", return_value=self.tracks), \
             patch("commands.reconcile.needs_confirm", return_value=not self.private), \
             patch("commands.reconcile.write_file", side_effect=self._fake_write), \
             patch("commands.reconcile.prompt_input", return_value="y"):
            rc = reconcile.run(["--all"] + (extra_args or []))
        return rc


class AutoMoveTest(unittest.TestCase):
    def test_relabel_moves_issue_from_a_to_b(self):
        # #50 is in alpha's frontmatter but now carries only track/beta.
        alpha = _track(slug="alpha", issues=[50])
        beta = _track(slug="beta", issues=[])
        labeled = {
            "track/alpha": [],
            "track/beta": [{"number": 50, "title": "moved", "state": "OPEN"}],
        }
        h = _Harness([alpha, beta], labeled)
        rc = h.run(extra_args=["--yes"])
        self.assertEqual(rc, 0)
        writes = dict(h.writes)
        self.assertEqual(writes["alpha.md"], [])      # removed from source
        self.assertEqual(writes["beta.md"], [50])     # added to destination
        self.assertEqual(len(h.writes), 2)            # each side written once

    def test_ambiguous_target_is_not_moved_out_of_source(self):
        # #50 lost alpha's label and is labeled for BOTH beta and gamma →
        # ambiguous target, so reconcile must NOT move it out of alpha. (beta
        # and gamma each legitimately ADD it, since it carries both labels —
        # that's normal membership-follows-labels behaviour, not a move.) The
        # point of this test: alpha keeps #50, the move logic does not fire.
        alpha = _track(slug="alpha", issues=[50])
        beta = _track(slug="beta", issues=[])
        gamma = _track(slug="gamma", issues=[])
        labeled = {
            "track/alpha": [],
            "track/beta": [{"number": 50, "title": "x", "state": "OPEN"}],
            "track/gamma": [{"number": 50, "title": "x", "state": "OPEN"}],
        }
        h = _Harness([alpha, beta, gamma], labeled)
        rc = h.run(extra_args=["--yes"])
        self.assertEqual(rc, 0)
        writes = dict(h.writes)
        # alpha must NOT be rewritten — #50 stays (no unambiguous move target).
        self.assertNotIn("alpha.md", writes)
        # beta and gamma each ADD #50 (it is labeled for both).
        self.assertEqual(writes.get("beta.md"), [50])
        self.assertEqual(writes.get("gamma.md"), [50])

    def test_draft_reports_move_but_writes_nothing(self):
        alpha = _track(slug="alpha", issues=[50])
        beta = _track(slug="beta", issues=[])
        labeled = {
            "track/alpha": [],
            "track/beta": [{"number": 50, "title": "moved", "state": "OPEN"}],
        }
        h = _Harness([alpha, beta], labeled)
        rc = h.run(extra_args=["--draft"])
        self.assertEqual(rc, 0)
        self.assertEqual(h.writes, [])

    def test_public_destination_skipped_under_yes(self):
        # Destination is PUBLIC → under --yes the move is skipped (no silent
        # membership write to a shared track); source is left untouched too.
        alpha = _track(slug="alpha", issues=[50])
        beta = _track(slug="beta", issues=[])
        labeled = {
            "track/alpha": [],
            "track/beta": [{"number": 50, "title": "moved", "state": "OPEN"}],
        }
        h = _Harness([alpha, beta], labeled, private=False)
        rc = h.run(extra_args=["--yes"])
        self.assertEqual(rc, 0)
        self.assertEqual(h.writes, [])  # nothing written when dst is public

    def test_move_does_not_duplicate_as_add_on_destination(self):
        # The destination must NOT also try to ADD #50 (which would be the
        # naive behaviour); it arrives exactly once, via the move.
        alpha = _track(slug="alpha", issues=[50])
        beta = _track(slug="beta", issues=[])
        labeled = {
            "track/alpha": [],
            "track/beta": [{"number": 50, "title": "moved", "state": "OPEN"}],
        }
        h = _Harness([alpha, beta], labeled)
        h.run(extra_args=["--yes"])
        writes = dict(h.writes)
        self.assertEqual(writes["beta.md"].count(50), 1)


if __name__ == "__main__":
    unittest.main()
