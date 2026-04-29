"""Smoke test: importable + main() exists."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan


class SmokeTest(unittest.TestCase):
    def test_main_exists(self):
        self.assertTrue(callable(work_plan.main))

    def test_main_no_args_returns_2(self):
        self.assertEqual(work_plan.main(["work_plan.py"]), 2)


if __name__ == "__main__":
    unittest.main()
