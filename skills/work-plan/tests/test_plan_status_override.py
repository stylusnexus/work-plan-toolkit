"""verdict_override (#286): a frontmatter override pins the verdict and silences
the lie-gap on plan-status. Offline — frontmatter parse shells to real yq."""
import io
import json
import unittest
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_status

# A plan whose ONE declared file exists (→ mechanical "shipped", file score 100%)
# but whose two phase checkboxes are unticked → the classic lie-gap shape.
BODY = (
    "# Idea Mode UI\n\n"
    "**Files:**\n"
    "- Create: `src/new.ts`\n"
    "- [ ] Step 1: do the thing\n"
    "- [ ] Step 2: do the other thing\n"
)


def _frontmattered(override: str) -> str:
    return f"---\nverdict_override: {override}\n---\n{BODY}"


def _frontmattered_kv(key: str, value: str) -> str:
    return f"---\n{key}: {value}\n---\n{BODY}"


class OverrideTest(unittest.TestCase):
    def _row(self, root):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(["--json"])
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())["docs"][0]

    def _repo(self, d, doc_text):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / "docs/superpowers/plans/p.md").write_text(doc_text)
        (root / "src").mkdir()
        (root / "src/new.ts").write_text("export const x = 1")  # 1/1 declared present
        return root

    def test_baseline_lie_gap_without_override(self):
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(d, BODY))
            self.assertEqual(row["verdict"], "shipped")
            self.assertTrue(row["lie_gap"])      # 0/2 boxes -> lie-gap fires
            self.assertIsNone(row["override"])

    def test_override_shipped_silences_lie_gap(self):
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(d, _frontmattered("shipped")))
            self.assertEqual(row["verdict"], "shipped")
            self.assertEqual(row["override"], "shipped")
            self.assertFalse(row["lie_gap"])     # human-confirmed -> no longer a lie
            self.assertIn("human-confirmed", row["rationale"])

    def test_override_pins_verdict_over_mechanical(self):
        # Declared file MISSING -> mechanical would be partial; override pins dead.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs/superpowers/plans").mkdir(parents=True)
            (root / "docs/superpowers/plans/p.md").write_text(_frontmattered("dead"))
            # no src/new.ts -> 0/1 files
            row = self._row(root)
            self.assertEqual(row["verdict"], "dead")
            self.assertEqual(row["override"], "dead")
            self.assertEqual(row["glyph"], "💀")

    def test_invalid_override_value_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(d, _frontmattered("done")))  # not a valid verdict
            self.assertIsNone(row["override"])
            self.assertTrue(row["lie_gap"])      # falls back to mechanical

    def test_acknowledged_frontmatter_emitted(self):
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(d, f"---\nacknowledged: true\n---\n{BODY}"))
            self.assertTrue(row["acknowledged"])

    def test_acknowledged_false_without_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(d, BODY))
            self.assertFalse(row["acknowledged"])

    def test_baseline_matching_live_verdict_no_drift(self):
        # File present → live "shipped"; baseline shipped → no drift.
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(d, _frontmattered_kv("verdict_baseline", "shipped")))
            self.assertEqual(row["verdict_baseline"], "shipped")
            self.assertFalse(row["verdict_drift"])

    def test_baseline_diverged_flags_drift(self):
        # File MISSING → live "partial"; baseline shipped → drift (regressed).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs/superpowers/plans").mkdir(parents=True)
            (root / "docs/superpowers/plans/p.md").write_text(
                f"---\nverdict_baseline: shipped\n---\n{BODY}")  # no src/new.ts
            row = self._row(root)
            self.assertEqual(row["verdict"], "partial")
            self.assertTrue(row["verdict_drift"])

    def test_override_suppresses_drift(self):
        # baseline partial, but a human override pins shipped → drift suppressed.
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(
                d, "---\nverdict_baseline: partial\nverdict_override: shipped\n---\n" + BODY))
            self.assertEqual(row["verdict"], "shipped")
            self.assertFalse(row["verdict_drift"])

    def test_no_baseline_no_drift(self):
        with tempfile.TemporaryDirectory() as d:
            row = self._row(self._repo(d, BODY))
            self.assertIsNone(row["verdict_baseline"])
            self.assertFalse(row["verdict_drift"])


if __name__ == "__main__":
    unittest.main()
