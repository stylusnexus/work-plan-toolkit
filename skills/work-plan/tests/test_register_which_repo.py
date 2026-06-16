"""which-repo is dispatchable + documented (#358/#357 Phase 1)."""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan


class RegisterWhichRepoTest(unittest.TestCase):
    def test_in_subcommands(self):
        self.assertEqual(work_plan.SUBCOMMANDS["which-repo"], "commands.which_repo")

    def test_in_descriptions(self):
        names = {row[0] for row in work_plan.DESCRIPTIONS}
        self.assertIn("which-repo", names)


if __name__ == "__main__":
    unittest.main()
