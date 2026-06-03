"""--llm --apply: validates provenance, merges verdicts, optionally stamps."""
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

PROSE = "# Design Doc\n\nProse only.\n"


class LlmApplyTest(unittest.TestCase):
    def _setup(self, d, cache, answers):
        root = Path(d)
        (root / "docs/superpowers/specs").mkdir(parents=True)
        rel = "docs/superpowers/specs/2026-03-16-x-design.md"
        (root / rel).write_text(PROSE)
        batch = {"repo_root": str(root), "docs": [{"rel": rel}]}
        (Path(cache) / "plan_status.json").write_text(json.dumps(batch))
        (Path(cache) / "plan_status.answers.json").write_text(json.dumps(answers))
        return root, rel

    def _run(self, root, cache, args):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root), \
             mock.patch("commands.plan_status.cache_dir", return_value=Path(cache)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = plan_status.run(args)
        return rc, buf.getvalue()

    def test_merges_verdict_into_report(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            rel = "docs/superpowers/specs/2026-03-16-x-design.md"
            root, _ = self._setup(d, cache, [
                {"rel": rel, "verdict": "shipped", "confidence": 0.9, "rationale": "done"}
            ])
            rc, out = self._run(root, cache, ["--llm", "--apply"])
            self.assertEqual(rc, 0)
            self.assertIn("shipped", out)
            self.assertIn("done", out)

    def test_rejects_rel_not_in_batch(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root, rel = self._setup(d, cache, [
                {"rel": "../evil.md", "verdict": "shipped", "confidence": 1, "rationale": "x"}
            ])
            rc, out = self._run(root, cache, ["--llm", "--apply"])
            self.assertIn("skip", out.lower())

    def test_rejects_repo_root_mismatch(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root, rel = self._setup(d, cache, [])
            bp = Path(cache) / "plan_status.json"
            b = json.loads(bp.read_text()); b["repo_root"] = "/somewhere/else"
            bp.write_text(json.dumps(b))
            rc, out = self._run(root, cache, ["--llm", "--apply"])
            self.assertEqual(rc, 1)
            self.assertIn("repo_root", out.lower())


if __name__ == "__main__":
    unittest.main()
