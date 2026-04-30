"""Regression tests for the /tmp planting hardening (#18).

Covers:
- lib.scratch.cache_dir() creates ~/.claude/work-plan/cache/ with mode 0700.
- commands.group._apply() rejects a batch whose `folder` is not in cfg.
- commands.suggest_priorities._apply() rejects a batch whose `repo` is not in cfg.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import scratch
from commands import group, suggest_priorities


# POSIX file mode bits aren't honored on Windows NTFS — os.chmod(0o700) is a
# no-op for directories there and stat.S_IMODE reports 0o777 regardless. The
# /tmp planting hardening these tests cover is itself a POSIX concern.
_POSIX_MODE_ONLY = unittest.skipIf(
    sys.platform == "win32", "POSIX file mode bits not honored on Windows"
)


class CacheDirTest(unittest.TestCase):
    @_POSIX_MODE_ONLY
    def test_creates_with_mode_0700(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(scratch.Path, "home", return_value=Path(td)):
                p = scratch.cache_dir()
            self.assertTrue(p.is_dir())
            self.assertEqual(p, Path(td) / ".claude" / "work-plan" / "cache")
            mode = stat.S_IMODE(os.stat(p).st_mode)
            self.assertEqual(mode, 0o700)

    @_POSIX_MODE_ONLY
    def test_tightens_existing_loose_perms(self):
        with tempfile.TemporaryDirectory() as td:
            existing = Path(td) / ".claude" / "work-plan" / "cache"
            existing.mkdir(parents=True, mode=0o755)
            self.assertEqual(stat.S_IMODE(os.stat(existing).st_mode), 0o755)
            with mock.patch.object(scratch.Path, "home", return_value=Path(td)):
                scratch.cache_dir()
            self.assertEqual(stat.S_IMODE(os.stat(existing).st_mode), 0o700)


class GroupApplyValidationTest(unittest.TestCase):
    def test_rejects_folder_not_in_cfg(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            cache.mkdir()
            (cache / "groups.json").write_text(json.dumps({
                "repo": "x/y", "folder": "../../etc",
                "milestone": "v1", "issues": [],
            }))
            (cache / "groups.answers.json").write_text("[]")
            with mock.patch.object(group, "_batch_path", return_value=cache / "groups.json"), \
                 mock.patch.object(group, "_answers_path", return_value=cache / "groups.answers.json"):
                cfg = {"notes_root": td, "repos": {"legitrepo": {"github": "ok/ok"}}}
                rc = group._apply(cfg)
            self.assertEqual(rc, 1)

    def test_accepts_folder_in_cfg(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            cache.mkdir()
            notes = Path(td) / "notes"
            (notes / "legitrepo").mkdir(parents=True)
            (cache / "groups.json").write_text(json.dumps({
                "repo": "ok/ok", "folder": "legitrepo",
                "milestone": "v1", "issues": [],
            }))
            (cache / "groups.answers.json").write_text("[]")
            with mock.patch.object(group, "_batch_path", return_value=cache / "groups.json"), \
                 mock.patch.object(group, "_answers_path", return_value=cache / "groups.answers.json"):
                cfg = {"notes_root": str(notes), "repos": {"legitrepo": {"github": "ok/ok"}}}
                rc = group._apply(cfg)
            self.assertEqual(rc, 0)


class SuggestPrioritiesApplyValidationTest(unittest.TestCase):
    def test_rejects_repo_not_in_cfg(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            cache.mkdir()
            (cache / "priorities.json").write_text(json.dumps({
                "repo": "attacker/target", "issues": [],
            }))
            (cache / "priorities.answers.json").write_text("[]")
            with mock.patch.object(suggest_priorities, "_batch_path", return_value=cache / "priorities.json"):
                cfg = {"repos": {"legitrepo": {"github": "ok/ok"}}}
                rc = suggest_priorities._apply(cfg)
            self.assertEqual(rc, 1)

    def test_accepts_repo_in_cfg(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "cache"
            cache.mkdir()
            (cache / "priorities.json").write_text(json.dumps({
                "repo": "ok/ok", "issues": [],
            }))
            (cache / "priorities.answers.json").write_text("[]")
            with mock.patch.object(suggest_priorities, "_batch_path", return_value=cache / "priorities.json"):
                cfg = {"repos": {"legitrepo": {"github": "ok/ok"}}}
                rc = suggest_priorities._apply(cfg)
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
