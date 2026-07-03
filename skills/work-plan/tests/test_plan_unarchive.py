"""plan-unarchive: restore an archived plan doc (offline; restore primitive
+ repo-root resolution mocked)."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import plan_unarchive

ARCHIVED = "docs/plans/archive/shipped/p.md"


def _drive(args, outcome="restored", is_file=True):
    with mock.patch("commands.plan_unarchive.plan_status._resolve_repo_root",
                    return_value=Path("/repo")), \
         mock.patch("pathlib.Path.is_file", return_value=is_file), \
         mock.patch("commands.plan_unarchive.archive_lib.restore_from_archive",
                    return_value=outcome) as rs:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan_unarchive.run(args)
    return rc, rs, buf.getvalue()


class PlanUnarchiveTest(unittest.TestCase):
    def test_restores_and_emits_json(self):
        rc, rs, out = _drive(["--repo=r", "--yes", "--json", "--", ARCHIVED])
        self.assertEqual(rc, 0)
        rs.assert_called_once_with(ARCHIVED, Path("/repo"))
        obj = json.loads(out)
        self.assertEqual(obj["action"], "unarchive")
        self.assertEqual(obj["outcome"], "restored")
        # dest strips archive/shipped/ back to the live location.
        self.assertEqual(obj["dest"], "docs/plans/p.md")

    def test_collision_refused(self):
        rc, rs, out = _drive(["--repo=r", "--yes", "--json", "--", ARCHIVED],
                             outcome="skipped_collision")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["outcome"], "skipped_collision")

    def test_restored_local(self):
        rc, rs, out = _drive(["--repo=r", "--yes", "--json", "--", ARCHIVED],
                             outcome="restored_local")
        self.assertEqual(json.loads(out)["outcome"], "restored_local")

    def test_draft_previews_without_moving(self):
        rc, rs, out = _drive(["--repo=r", "--draft", "--", ARCHIVED])
        self.assertEqual(rc, 0)
        rs.assert_not_called()
        self.assertIn("Would restore", out)

    def test_not_under_archive_errors(self):
        rc, rs, out = _drive(["--repo=r", "--yes", "--", "docs/plans/p.md"])
        self.assertEqual(rc, 1)
        rs.assert_not_called()

    def test_missing_file_errors(self):
        rc, rs, out = _drive(["--repo=r", "--yes", "--", ARCHIVED], is_file=False)
        self.assertEqual(rc, 1)
        rs.assert_not_called()

    def test_repo_required(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan_unarchive.run(["--yes", "--", ARCHIVED])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
