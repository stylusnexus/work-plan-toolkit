"""Tests for the dedupe-tiers command and its tracks.py helpers (#359)."""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import dedupe_tiers
from lib import tracks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _track(*, name, repo="org/repo", folder="repo", issues=None, references=None, body="",
           path=None, tier="private"):
    meta = {"track": name, "github": {"repo": repo}}
    if issues is not None:
        meta["github"]["issues"] = issues
    if references is not None:
        meta["github"]["references"] = references
    return SimpleNamespace(
        name=name,
        path=Path(path) if path else Path(f"/tmp/notes/{folder}/{name}.md"),
        repo=repo,
        folder=folder,
        meta=meta,
        body=body,
        tier=tier,
    )


def _drive(args, pairs, *, notes_root="/tmp/notes"):
    cfg = {"notes_root": notes_root, "repos": {"repo": {"github": "org/repo"}}}
    buf = io.StringIO()
    with patch("commands.dedupe_tiers.load_config", return_value=cfg), \
         patch("commands.dedupe_tiers.find_tier_duplicates", return_value=pairs), \
         redirect_stdout(buf):
        rc = dedupe_tiers.run(args)
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# issue_refs
# ---------------------------------------------------------------------------

class TestIssueRefs(unittest.TestCase):
    def test_unions_frontmatter_and_body(self):
        t = _track(name="a", issues=[10, 20], body="see #20 and #30 here")
        self.assertEqual(tracks.issue_refs(t), {10, 20, 30})

    def test_empty_when_no_refs(self):
        t = _track(name="a", issues=None, body="no refs at all")
        self.assertEqual(tracks.issue_refs(t), set())

    def test_ignores_non_int_frontmatter(self):
        t = _track(name="a", issues=[1, "oops", None], body="")
        self.assertEqual(tracks.issue_refs(t), {1})

    def test_unions_cross_track_references(self):
        t = _track(name="a", issues=[10], references=[40, 50], body="")
        self.assertEqual(tracks.issue_refs(t), {10, 40, 50})

    def test_references_only_track_not_empty(self):
        t = _track(name="a", issues=None, references=[99], body="")
        self.assertEqual(tracks.issue_refs(t), {99})


# ---------------------------------------------------------------------------
# find_tier_duplicates pairing (helpers patched)
# ---------------------------------------------------------------------------

class TestFindTierDuplicates(unittest.TestCase):
    def test_pairs_only_colliding_active_tracks(self):
        shared = [_track(name="dup", tier="shared"), _track(name="only-shared", tier="shared")]
        private = [_track(name="dup"), _track(name="only-private")]
        cfg = {"notes_root": "/tmp/does-not-exist-xyz", "repos": {}}
        with patch.object(tracks, "_discover_shared_tracks") as ds, \
             patch.object(tracks, "_discover_private_tracks", return_value=private):
            # active call returns `shared`; archive-only call returns []
            ds.side_effect = lambda cfg, include_archive=False, archive_only=False: (
                [] if archive_only else shared)
            pairs = tracks.find_tier_duplicates(cfg)
        names = [(s.name, p.name) for (s, p) in pairs]
        self.assertEqual(names, [("dup", "dup")])


# ---------------------------------------------------------------------------
# command: report / apply / safety
# ---------------------------------------------------------------------------

class TestDedupeCommand(unittest.TestCase):
    def test_no_pairs_reports_nothing(self):
        rc, out = _drive([], [])
        self.assertEqual(rc, 0)
        self.assertIn("Nothing to dedupe", out)

    def test_dry_run_removes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            pf = Path(d) / "dup.md"
            pf.write_text("# dup\n")
            shared = _track(name="dup", issues=[1, 2], tier="shared")
            private = _track(name="dup", issues=[1], path=str(pf))
            rc, out = _drive([], [(shared, private)])
            self.assertTrue(pf.exists(), "dry run must not delete")
        self.assertEqual(rc, 0)
        self.assertIn("Dry run", out)
        self.assertIn("--apply", out)

    def test_apply_removes_subset_orphan(self):
        with tempfile.TemporaryDirectory() as d:
            pf = Path(d) / "dup.md"
            pf.write_text("# dup\n")
            shared = _track(name="dup", issues=[1, 2, 3], tier="shared")
            private = _track(name="dup", issues=[1, 3], path=str(pf))
            rc, out = _drive(["--apply"], [(shared, private)])
            self.assertEqual(rc, 0)
            self.assertFalse(pf.exists(), "subset orphan must be removed on --apply")
        self.assertIn("Removed 1 private orphan", out)

    def test_apply_keeps_diverged_orphan(self):
        with tempfile.TemporaryDirectory() as d:
            pf = Path(d) / "dup.md"
            pf.write_text("# dup\n")
            # private references #99 which the shared twin lacks → must be kept
            shared = _track(name="dup", issues=[1, 2], tier="shared")
            private = _track(name="dup", issues=[1], body="leftover #99", path=str(pf))
            rc, out = _drive(["--apply"], [(shared, private)])
            self.assertEqual(rc, 0)
            self.assertTrue(pf.exists(), "diverged orphan must NOT be removed")
        self.assertIn("#99", out)
        self.assertIn("manual review", out)

    def test_apply_keeps_orphan_whose_only_content_is_references(self):
        with tempfile.TemporaryDirectory() as d:
            pf = Path(d) / "dup.md"
            pf.write_text("# dup\n")
            # private has no owned issues/body mentions but DOES hold a cross-track
            # reference the shared twin lacks — issue_refs() must see it or this
            # data silently vanishes on --apply (#458 regression).
            shared = _track(name="dup", issues=[1, 2], tier="shared")
            private = _track(name="dup", issues=None, references=[99], path=str(pf))
            rc, out = _drive(["--apply"], [(shared, private)])
            self.assertEqual(rc, 0)
            self.assertTrue(pf.exists(), "reference-only orphan must NOT be removed")
        self.assertIn("#99", out)
        self.assertIn("manual review", out)

    def test_repo_filter_scopes_pairs(self):
        a_shared = _track(name="a", repo="org/a", folder="a", issues=[1], tier="shared")
        a_priv = _track(name="a", repo="org/a", folder="a", issues=[1])
        b_shared = _track(name="b", repo="org/b", folder="b", issues=[1], tier="shared")
        b_priv = _track(name="b", repo="org/b", folder="b", issues=[1])
        rc, out = _drive(["--repo=a"], [(a_shared, a_priv), (b_shared, b_priv)])
        self.assertEqual(rc, 0)
        self.assertIn("a  (repo org/a)", out)
        self.assertNotIn("org/b", out)

    def test_repo_flag_without_value_is_usage_error(self):
        rc, _ = _drive(["--repo"], [])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
