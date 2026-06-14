"""in-progress is dispatchable + documented (#271)."""
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan


class RegisterInProgressTest(unittest.TestCase):
    def test_in_subcommands(self):
        self.assertEqual(work_plan.SUBCOMMANDS["in-progress"], "commands.in_progress")

    def test_in_descriptions(self):
        names = {row[0] for row in work_plan.DESCRIPTIONS}
        self.assertIn("in-progress", names)


if __name__ == "__main__":
    unittest.main()
