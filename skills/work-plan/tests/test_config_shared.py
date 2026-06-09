"""Tests for is_valid_git_repo() in lib/config."""
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.config import is_valid_git_repo


class IsValidGitRepoTest(unittest.TestCase):
    def test_returns_true_for_dir_with_dot_git(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / ".git").mkdir()
            self.assertTrue(is_valid_git_repo(base))

    def test_dot_git_can_be_a_file_worktree(self):
        """Worktrees have .git as a file, not a dir — still truthy via .exists()."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / ".git").write_text("gitdir: ../.git/worktrees/foo\n", encoding="utf-8")
            self.assertTrue(is_valid_git_repo(base))

    def test_returns_false_for_nonexistent_path(self):
        self.assertFalse(is_valid_git_repo(Path("/tmp/nonexistent_12345")))

    def test_returns_false_for_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "not_a_dir.txt"
            f.write_text("hello", encoding="utf-8")
            self.assertFalse(is_valid_git_repo(f))

    def test_returns_false_for_dir_without_dot_git(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "plain_dir"
            base.mkdir()
            self.assertFalse(is_valid_git_repo(base))

    def test_accepts_path_object(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / ".git").mkdir()
            self.assertTrue(is_valid_git_repo(Path(d)))

    def test_accepts_string_path(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / ".git").mkdir()
            # is_valid_git_repo coerces to Path internally
            self.assertTrue(is_valid_git_repo(d))


if __name__ == "__main__":
    unittest.main()
