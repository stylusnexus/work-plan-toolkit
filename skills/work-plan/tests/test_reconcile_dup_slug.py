"""Cross-repo duplicate-slug isolation in reconcile (#255).

Identical track slugs in DIFFERENT repos are explicitly supported. Reconcile's
in-flight state must be keyed by a per-track identity (repo, path), not by slug
— otherwise a later same-slug track's fetch overwrites the earlier one's, and
under `--all --yes` issues from one repo get written into the same-named track
in ANOTHER repo (membership corruption).

All gh calls are mocked; tests run offline. The fake `gh` here is REPO-AWARE
(unlike the shared move harness) so two same-slug tracks in different repos can
return different labeled issues.
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


def _track(*, slug, repo, issues=None):
    # Path embeds the repo so two same-slug tracks have distinct file paths,
    # mirroring how discover_tracks lays out per-repo note dirs.
    safe_repo = repo.replace("/", "_")
    return SimpleNamespace(
        name=slug,
        path=Path(f"/tmp/fake/{safe_repo}/{slug}.md"),
        body="# fake",
        meta={"track": slug, "status": "active",
              "github": {"repo": repo, "issues": list(issues or [])}},
        has_frontmatter=True,
        repo=repo,
    )


class _RepoAwareHarness:
    """Drives reconcile --all where labeled issues depend on BOTH repo and label.

    `labeled` maps (repo, label) -> list of issue dicts that
    `gh issue/pr list --repo <repo> --label <label>` should return.
    """

    def __init__(self, tracks, labeled):
        self.tracks = tracks
        self.labeled = labeled
        self.writes = []  # (path_str, issues) per write_file call

    def _fake_run(self, argv, *a, **kw):
        out = []
        if "--label" in argv and argv[1] == "issue":  # count issues once, not PRs
            repo = argv[argv.index("--repo") + 1]
            lab = argv[argv.index("--label") + 1]
            out = self.labeled.get((repo, lab), [])
        return MagicMock(returncode=0, stdout=json.dumps(out), stderr="")

    def _fake_write(self, path, meta, body):
        self.writes.append((str(path), list(meta.get("github", {}).get("issues") or [])))

    def run(self, extra_args=None):
        cfg = {"notes_root": "/tmp/n"}
        with patch("commands.reconcile.subprocess.run", side_effect=self._fake_run), \
             patch("commands.reconcile.load_config", return_value=cfg), \
             patch("commands.reconcile.discover_tracks", return_value=self.tracks), \
             patch("commands.reconcile.needs_confirm", return_value=False), \
             patch("commands.reconcile.write_file", side_effect=self._fake_write), \
             patch("commands.reconcile.prompt_input", return_value="y"):
            rc = reconcile.run(["--all"] + (extra_args or []))
        return rc


class DupSlugCrossRepoTest(unittest.TestCase):
    def test_adds_land_in_the_correct_repo_track(self):
        """Two tracks share slug 'core' across repos o/a and o/b. Each repo
        labels a DIFFERENT issue. Under --all --yes, each issue must land in
        its OWN repo's track — never bleed into the same-named sibling."""
        a = _track(slug="core", repo="o/a", issues=[])
        b = _track(slug="core", repo="o/b", issues=[])
        labeled = {
            ("o/a", "track/core"): [{"number": 11, "title": "a-issue", "state": "OPEN"}],
            ("o/b", "track/core"): [{"number": 22, "title": "b-issue", "state": "OPEN"}],
        }
        h = _RepoAwareHarness([a, b], labeled)
        rc = h.run(extra_args=["--yes"])
        self.assertEqual(rc, 0)
        writes = dict(h.writes)
        # Key off each track's real Path string (backslashes on Windows), not a
        # hardcoded POSIX literal — the collision is the slug, not the path.
        self.assertEqual(writes[str(a.path)], [11])
        self.assertEqual(writes[str(b.path)], [22])

    def test_failed_fetch_does_not_corrupt_same_slug_sibling(self):
        """If repo o/a's fetch is intact but o/b's is independent, the second
        track's results must not overwrite the first's. Here o/a adds #11 and
        o/b adds #22; pre-fix, the shared 'core' key meant the second fetch
        clobbered the first and #11 was lost / mis-routed."""
        a = _track(slug="core", repo="o/a", issues=[11])  # already has #11
        b = _track(slug="core", repo="o/b", issues=[])
        labeled = {
            # o/a still labels #11 (no change → no write expected for a)
            ("o/a", "track/core"): [{"number": 11, "title": "a", "state": "OPEN"}],
            # o/b newly labels #99
            ("o/b", "track/core"): [{"number": 99, "title": "b", "state": "OPEN"}],
        }
        h = _RepoAwareHarness([a, b], labeled)
        rc = h.run(extra_args=["--yes"])
        self.assertEqual(rc, 0)
        writes = dict(h.writes)
        # o/a unchanged → not written. o/b gains #99 only — NOT #11.
        self.assertNotIn(str(a.path), writes)
        self.assertEqual(writes[str(b.path)], [99])

    def test_no_cross_repo_move_between_same_slug_tracks(self):
        """A move only fires within ONE repo. #50 sits in o/a's 'core'
        frontmatter and is labeled for o/b's 'core' — different repos, so it
        must stay a FLAG on o/a, not move across the repo boundary."""
        a = _track(slug="core", repo="o/a", issues=[50])
        b = _track(slug="core", repo="o/b", issues=[])
        labeled = {
            ("o/a", "track/core"): [],  # #50 lost its label in o/a
            ("o/b", "track/core"): [{"number": 50, "title": "x", "state": "OPEN"}],
        }
        h = _RepoAwareHarness([a, b], labeled)
        rc = h.run(extra_args=["--yes"])
        self.assertEqual(rc, 0)
        writes = dict(h.writes)
        # o/a keeps #50 (no same-repo move target) → not rewritten.
        self.assertNotIn(str(a.path), writes)
        # o/b ADDs #50 because it now carries o/b's label — legitimate, in-repo.
        self.assertEqual(writes.get(str(b.path)), [50])


if __name__ == "__main__":
    unittest.main()
