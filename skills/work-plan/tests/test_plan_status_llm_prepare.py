"""--llm step 1: writes a batch of candidate docs + prints a prompt."""
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

PROSE = "# Design Doc\n\nProse only, no file manifest here.\n"


class LlmPrepareTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/specs").mkdir(parents=True)
        (root / "docs/superpowers/specs/2026-03-16-x-design.md").write_text(PROSE)
        return root

    def test_prepare_writes_batch_of_candidates(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root = self._repo(d)
            cache_file = Path(cache) / "plan_status.json"
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root), \
                 mock.patch("commands.plan_status.cache_dir", return_value=Path(cache)):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run(["--llm"])
            self.assertEqual(rc, 0)
            self.assertTrue(cache_file.exists())
            batch = json.loads(cache_file.read_text())
            self.assertEqual(batch["repo_root"], str(root))
            rels = [d["rel"] for d in batch["docs"]]
            self.assertIn("docs/superpowers/specs/2026-03-16-x-design.md", rels)
            out = buf.getvalue()
            self.assertIn("plan_status.answers.json", out)

    def test_prepare_reports_when_no_candidates(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as cache:
            root = Path(d)
            (root / "docs/superpowers/plans").mkdir(parents=True)
            (root / "docs/superpowers/plans/2026-01-01-done.md").write_text(
                "# Done\n- Create: `src/a.py`\n")
            (root / "src").mkdir()
            (root / "src/a.py").write_text("x")
            with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                            return_value=None), \
                 mock.patch("commands.plan_status.Path.cwd", return_value=root), \
                 mock.patch("commands.plan_status.cache_dir", return_value=Path(cache)):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run(["--llm"])
            self.assertEqual(rc, 0)
            self.assertIn("no docs need an llm verdict", buf.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
