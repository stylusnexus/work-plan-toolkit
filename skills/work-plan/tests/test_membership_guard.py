"""Tests for lib.membership_guard — the compare-and-swap guard (#241).

Covers:
- issues_fingerprint is order-independent and stable, and ignores non-issue
  frontmatter (last_touched / body differences don't change it).
- guarded_membership_write merges add/remove onto the FRESH on-disk frontmatter.
- A concurrent body-only edit is preserved (the fresh body is written back).
- expect-match writes; expect-mismatch returns {stale} and does NOT write.
- expect=None never aborts (the manual single-writer path).

All file I/O is exercised against a real temp file (no yq mock needed — these go
through lib.frontmatter end to end), so the round-trip is real.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.frontmatter import parse_file, write_file
from lib.membership_guard import (
    issues_fingerprint,
    references_fingerprint,
    guarded_membership_write,
    guarded_reference_write,
)


def _meta(issues, repo="ok/repo", references=None, **extra):
    m = {"track": "alpha", "status": "active", "github": {"repo": repo, "issues": list(issues)}}
    if references is not None:
        m["github"]["references"] = list(references)
    m.update(extra)
    return m


class FingerprintTest(unittest.TestCase):

    def test_order_independent(self):
        self.assertEqual(
            issues_fingerprint(_meta([3, 1, 2])),
            issues_fingerprint(_meta([1, 2, 3])),
        )

    def test_changes_when_membership_changes(self):
        self.assertNotEqual(
            issues_fingerprint(_meta([1, 2])),
            issues_fingerprint(_meta([1, 2, 3])),
        )

    def test_ignores_non_issue_frontmatter(self):
        """last_touched / other fields must not affect the fingerprint, else the
        guard would abort on unrelated concurrent edits."""
        self.assertEqual(
            issues_fingerprint(_meta([1, 2], last_touched="2026-01-01")),
            issues_fingerprint(_meta([1, 2], last_touched="2026-06-17")),
        )

    def test_empty_and_missing_github_are_stable(self):
        self.assertEqual(issues_fingerprint({}), issues_fingerprint(_meta([])))


class GuardedWriteTest(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "alpha.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self, issues, body="# body\n"):
        write_file(self.path, _meta(issues), body)

    def test_add_merges_onto_disk(self):
        self._seed([10, 20])
        res = guarded_membership_write(self.path, add_nums=[30])
        self.assertEqual(res, {"written": [10, 20, 30]})
        meta, _ = parse_file(self.path)
        self.assertEqual(meta["github"]["issues"], [10, 20, 30])

    def test_remove_merges_onto_disk(self):
        self._seed([10, 20, 30])
        res = guarded_membership_write(self.path, remove_nums=[20])
        self.assertEqual(res, {"written": [10, 30]})

    def test_preserves_concurrent_body_edit(self):
        """Re-reads body at write time, so a body change made after the caller's
        snapshot is preserved rather than clobbered."""
        self._seed([10], body="# original\n")
        # Simulate another process rewriting ONLY the body (e.g. handoff).
        meta, _ = parse_file(self.path)
        write_file(self.path, meta, "# rewritten by another writer\n")
        guarded_membership_write(self.path, add_nums=[20])
        _, body = parse_file(self.path)
        self.assertIn("rewritten by another writer", body)

    def test_expect_match_writes(self):
        self._seed([10, 20])
        fp = issues_fingerprint(_meta([10, 20]))
        res = guarded_membership_write(self.path, add_nums=[30], expect=fp)
        self.assertEqual(res, {"written": [10, 20, 30]})

    def test_expect_mismatch_aborts_without_writing(self):
        self._seed([10, 20])
        stale_fp = issues_fingerprint(_meta([10]))  # what the caller THOUGHT it saw
        res = guarded_membership_write(self.path, add_nums=[30], expect=stale_fp)
        self.assertTrue(res["stale"])
        self.assertEqual(res["current"], [10, 20])
        # Nothing was written — disk is unchanged.
        meta, _ = parse_file(self.path)
        self.assertEqual(meta["github"]["issues"], [10, 20])

    def test_expect_none_never_aborts(self):
        self._seed([10, 20])
        res = guarded_membership_write(self.path, add_nums=[30], expect=None)
        self.assertIn("written", res)


class ReferenceFingerprintTest(unittest.TestCase):

    def test_order_independent(self):
        self.assertEqual(
            references_fingerprint(_meta([], references=[3, 1, 2])),
            references_fingerprint(_meta([], references=[1, 2, 3])),
        )

    def test_changes_when_references_change(self):
        self.assertNotEqual(
            references_fingerprint(_meta([], references=[1, 2])),
            references_fingerprint(_meta([], references=[1, 2, 3])),
        )

    def test_ignores_issues_list(self):
        """The references fingerprint must be independent of github.issues —
        an owned-issue add/remove must not stale-out a pending reference write."""
        self.assertEqual(
            references_fingerprint(_meta([1, 2], references=[9])),
            references_fingerprint(_meta([1, 2, 3], references=[9])),
        )

    def test_empty_and_missing_github_are_stable(self):
        self.assertEqual(references_fingerprint({}), references_fingerprint(_meta([], references=[])))


class GuardedReferenceWriteTest(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "alpha.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self, issues=(), references=(), body="# body\n"):
        write_file(self.path, _meta(issues, references=references), body)

    def test_add_merges_onto_disk(self):
        self._seed(references=[10, 20])
        res = guarded_reference_write(self.path, add_nums=[30])
        self.assertEqual(res, {"written": [10, 20, 30]})
        meta, _ = parse_file(self.path)
        self.assertEqual(meta["github"]["references"], [10, 20, 30])

    def test_preserves_concurrent_body_edit(self):
        self._seed(references=[10], body="# original\n")
        meta, _ = parse_file(self.path)
        write_file(self.path, meta, "# rewritten by another writer\n")
        guarded_reference_write(self.path, add_nums=[20])
        _, body = parse_file(self.path)
        self.assertIn("rewritten by another writer", body)

    def test_expect_match_writes(self):
        self._seed(references=[10, 20])
        fp = references_fingerprint(_meta([], references=[10, 20]))
        res = guarded_reference_write(self.path, add_nums=[30], expect=fp)
        self.assertEqual(res, {"written": [10, 20, 30]})

    def test_expect_mismatch_aborts_without_writing(self):
        self._seed(references=[10, 20])
        stale_fp = references_fingerprint(_meta([], references=[10]))
        res = guarded_reference_write(self.path, add_nums=[30], expect=stale_fp)
        self.assertTrue(res["stale"])
        self.assertEqual(res["current"], [10, 20])
        meta, _ = parse_file(self.path)
        self.assertEqual(meta["github"]["references"], [10, 20])

    def test_expect_none_never_aborts(self):
        self._seed(references=[10, 20])
        res = guarded_reference_write(self.path, add_nums=[30], expect=None)
        self.assertIn("written", res)


if __name__ == "__main__":
    unittest.main()
