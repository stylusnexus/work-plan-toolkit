"""A plan whose declared files live outside the repo -> foreign verdict."""
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

# All declared paths are ~/-rooted -> outside this repo.
FOREIGN_PLAN = (
    "# Daily Work Planner\n\n"
    "- Create: `~/.claude/skills/work-plan/work_plan.py`\n"
    "- Create: `~/.claude/skills/work-plan/SKILL.md`\n"
)
# Declares in-repo src/ paths -> a real (partial) plan, NOT foreign.
LOCAL_PLAN = "# Real\n\n- Create: `src/here.ts`\n- Create: `src/gone.ts`\n"


class ForeignTest(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        (root / "docs/superpowers/plans").mkdir(parents=True)
        (root / "docs/superpowers/plans/2026-04-28-daily-work-planner.md").write_text(FOREIGN_PLAN)
        (root / "docs/superpowers/plans/2026-05-01-real.md").write_text(LOCAL_PLAN)
        (root / "src").mkdir()
        (root / "src/here.ts").write_text("x")
        return root

    def _json(self, root):
        with mock.patch("commands.plan_status.git_state.path_last_commit_date",
                        return_value=None), \
             mock.patch("commands.plan_status.Path.cwd", return_value=root):
            buf = io.StringIO()
            with redirect_stdout(buf):
                plan_status.run(["--json"])
        return {r["rel"].split("/")[-1]: r for r in json.loads(buf.getvalue())["docs"]}

    def test_out_of_tree_plan_is_foreign_local_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            rows = self._json(self._repo(d))
            self.assertEqual(rows["2026-04-28-daily-work-planner.md"]["verdict"], "foreign")
            self.assertEqual(rows["2026-04-28-daily-work-planner.md"]["glyph"], "🧳")
            # the in-repo plan is partial (1/2), not foreign
            self.assertEqual(rows["2026-05-01-real.md"]["verdict"], "partial")


if __name__ == "__main__":
    unittest.main()
