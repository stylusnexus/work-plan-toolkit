"""Smoke test: importable + main() exists."""
import io
import unittest
import sys
from contextlib import redirect_stdout
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan


class SmokeTest(unittest.TestCase):
    def test_main_exists(self):
        self.assertTrue(callable(work_plan.main))

    def test_main_no_args_returns_2(self):
        self.assertEqual(work_plan.main(["work_plan.py"]), 2)

    def test_version_flag_prints_and_exits_zero(self):
        for flag in ("--version", "-v"):
            with self.subTest(flag=flag):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = work_plan.main(["work_plan.py", flag])
                out = buf.getvalue().strip()
                self.assertEqual(rc, 0)
                self.assertTrue(out, f"{flag} produced empty output")
                self.assertIn(work_plan.VERSION, out)


if __name__ == "__main__":
    unittest.main()
