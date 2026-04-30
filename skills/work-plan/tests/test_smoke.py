"""Smoke test: importable + main() exists."""
import io
import unittest
import sys
from contextlib import redirect_stderr, redirect_stdout
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
                out_buf = io.StringIO()
                err_buf = io.StringIO()
                with redirect_stdout(out_buf), redirect_stderr(err_buf):
                    rc = work_plan.main(["work_plan.py", flag])
                out = out_buf.getvalue().strip()
                err = err_buf.getvalue()
                self.assertEqual(rc, 0)
                self.assertTrue(out, f"{flag} produced empty stdout")
                self.assertIn(work_plan.VERSION, out)
                self.assertEqual(err, "", f"{flag} wrote to stderr: {err!r}")


if __name__ == "__main__":
    unittest.main()
