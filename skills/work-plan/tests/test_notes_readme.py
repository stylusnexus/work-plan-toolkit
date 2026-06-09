"""Tests for lib/notes_readme.py — seed_readme."""
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.notes_readme import seed_readme, README_CONTENT


class SeedReadmeTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work_plan_dir = Path(self._tmp.name) / ".work-plan"
        self.work_plan_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_readme_when_absent_returns_true(self):
        """seed_readme writes README.md when it doesn't exist; returns True."""
        result = seed_readme(self.work_plan_dir)
        self.assertTrue(result)
        readme = self.work_plan_dir / "README.md"
        self.assertTrue(readme.exists())

    def test_idempotent_existing_readme_returns_false(self):
        """seed_readme skips when README.md already exists; returns False."""
        readme = self.work_plan_dir / "README.md"
        readme.write_text("existing content", encoding="utf-8")
        result = seed_readme(self.work_plan_dir)
        self.assertFalse(result)
        # Content not overwritten
        self.assertEqual(readme.read_text(encoding="utf-8"), "existing content")

    def test_idempotent_second_call_returns_false(self):
        """Calling seed_readme twice: first call True, second call False."""
        first = seed_readme(self.work_plan_dir)
        second = seed_readme(self.work_plan_dir)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_readme_content_contains_shared_tier(self):
        """Written README contains 'shared tier'."""
        seed_readme(self.work_plan_dir)
        content = (self.work_plan_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("shared tier", content)

    def test_readme_content_contains_private_flag(self):
        """Written README mentions '--private'."""
        seed_readme(self.work_plan_dir)
        content = (self.work_plan_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("--private", content)

    def test_readme_content_contains_work_plan_toolkit(self):
        """Written README references 'work-plan-toolkit'."""
        seed_readme(self.work_plan_dir)
        content = (self.work_plan_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("work-plan-toolkit", content)

    def test_absent_readme_in_existing_folder_is_written(self):
        """Caller's responsibility: seed_readme writes when README absent,
        regardless of whether the dir is 'new' or 'existing'.
        (The deletion-as-opt-out contract is enforced by callers who only
        call seed_readme when creating a new directory, not by the function.)
        """
        # Simulate an existing dir that lost its README (from the function's POV,
        # the file is just absent → it writes)
        result = seed_readme(self.work_plan_dir)
        self.assertTrue(result)
        self.assertTrue((self.work_plan_dir / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
