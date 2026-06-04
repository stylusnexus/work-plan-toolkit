"""Tests for manifest parsing + scoring."""
import unittest
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.manifest import (
    DeclaredPath, strip_range, parse_declared_paths,
    count_checkboxes, plan_date_from_filename,
    ManifestScore, score_manifest,
    is_in_tree, out_of_tree_ratio,
)


class InTreeTest(unittest.TestCase):
    ROOT = Path("/repo")

    def test_relative_is_in_tree(self):
        self.assertTrue(is_in_tree("src/foo.ts", self.ROOT))

    def test_tilde_is_out_of_tree(self):
        self.assertFalse(is_in_tree("~/.claude/skills/x.py", self.ROOT))

    def test_absolute_elsewhere_is_out_of_tree(self):
        self.assertFalse(is_in_tree("/Applications/other/x.ts", self.ROOT))

    def test_absolute_under_root_is_in_tree(self):
        self.assertTrue(is_in_tree("/repo/src/x.ts", self.ROOT))

    def test_dotdot_escape_is_out_of_tree(self):
        self.assertFalse(is_in_tree("../sibling/x.ts", self.ROOT))


class OutOfTreeRatioTest(unittest.TestCase):
    def test_all_foreign(self):
        decls = [DeclaredPath("create", "~/.claude/a.py"),
                 DeclaredPath("create", "/Applications/other/b.ts")]
        self.assertEqual(out_of_tree_ratio(decls, Path("/repo")), 1.0)

    def test_mixed(self):
        decls = [DeclaredPath("create", "src/a.ts"),
                 DeclaredPath("create", "~/b.py")]
        self.assertEqual(out_of_tree_ratio(decls, Path("/repo")), 0.5)

    def test_empty_is_zero(self):
        self.assertEqual(out_of_tree_ratio([], Path("/repo")), 0.0)


class StripRangeTest(unittest.TestCase):
    def test_strips_line_range(self):
        self.assertEqual(strip_range("src/foo.ts:120-145"), "src/foo.ts")

    def test_strips_single_line(self):
        self.assertEqual(strip_range("src/foo.ts:12"), "src/foo.ts")

    def test_strips_multi_range(self):
        self.assertEqual(strip_range("src/foo.tsx:104-115,217-247"), "src/foo.tsx")

    def test_leaves_bare_path(self):
        self.assertEqual(strip_range("src/foo.ts"), "src/foo.ts")


class ParseDeclaredPathsTest(unittest.TestCase):
    SAMPLE = (
        "**Files:**\n"
        "- Create: `src/lib/idea.ts`\n"
        "- Modify: `src/app/route.ts:10-22`\n"
        "- Test: `tests/idea.test.ts`\n"
        "Run: `npm test`\n"            # not a declared path (no Create/Modify/Test)
        "See `SomeType` for details\n"  # not a path
    )

    def test_extracts_three_kinds(self):
        decls = parse_declared_paths(self.SAMPLE)
        kinds = {d.kind for d in decls}
        self.assertEqual(kinds, {"create", "modify", "test"})

    def test_strips_range_on_modify(self):
        decls = parse_declared_paths(self.SAMPLE)
        modify = [d for d in decls if d.kind == "modify"][0]
        self.assertEqual(modify.path, "src/app/route.ts")

    def test_ignores_non_declaration_backticks(self):
        decls = parse_declared_paths(self.SAMPLE)
        paths = {d.path for d in decls}
        self.assertNotIn("npm test", paths)
        self.assertNotIn("SomeType", paths)

    def test_dedupes_first_kind_wins(self):
        text = "- Create: `a/b.ts`\n- Modify: `a/b.ts`\n"
        decls = parse_declared_paths(text)
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0].kind, "create")


class CountCheckboxesTest(unittest.TestCase):
    def test_counts_done_and_total_multiline(self):
        text = "- [x] one\n- [ ] two\n  - [X] three\n- [ ] four\n"
        done, total = count_checkboxes(text)
        self.assertEqual((done, total), (2, 4))

    def test_no_checkboxes(self):
        self.assertEqual(count_checkboxes("plain prose"), (0, 0))


class PlanDateTest(unittest.TestCase):
    def test_extracts_iso_prefix(self):
        self.assertEqual(plan_date_from_filename("2026-03-16-idea-mode-ui.md"),
                         date(2026, 3, 16))

    def test_returns_none_without_date(self):
        self.assertIsNone(plan_date_from_filename("idea-mode-ui.md"))


class ScoreManifestTest(unittest.TestCase):
    def _decls(self):
        return [
            DeclaredPath("create", "src/new.ts"),
            DeclaredPath("create", "src/missing.ts"),
            DeclaredPath("modify", "src/existing.ts"),
            DeclaredPath("test", "tests/new.test.ts"),
        ]

    def test_scores_with_injected_predicates(self):
        present = {"src/new.ts", "tests/new.test.ts", "src/existing.ts"}
        committed = {"src/existing.ts"}
        score = score_manifest(
            self._decls(), Path("/repo"), date(2026, 3, 1),
            exists=lambda rel: rel in present,
            committed_since=lambda rel: rel in committed,
        )
        # create: new.ts present(yes), missing.ts(no) -> 1/2
        # modify: existing.ts committed-since(yes) -> 1/1
        # test:   new.test.ts present(yes) -> 1/1
        self.assertEqual(score.total, 4)
        self.assertEqual(score.satisfied, 3)
        self.assertEqual(score.by_kind["create"], (1, 2))
        self.assertEqual(score.by_kind["modify"], (1, 1))
        self.assertEqual(score.by_kind["test"], (1, 1))
        self.assertAlmostEqual(score.pct, 75.0)

    def test_modify_existing_but_not_committed_is_unsatisfied(self):
        score = score_manifest(
            [DeclaredPath("modify", "src/old.ts")], Path("/repo"), date(2026, 3, 1),
            exists=lambda rel: True,             # file exists...
            committed_since=lambda rel: False,   # ...but untouched since plan date
        )
        self.assertEqual(score.satisfied, 0)

    def test_empty_manifest_pct_none(self):
        score = score_manifest([], Path("/repo"), None,
                               exists=lambda rel: False,
                               committed_since=lambda rel: False)
        self.assertEqual(score.total, 0)
        self.assertIsNone(score.pct)


if __name__ == "__main__":
    unittest.main()
