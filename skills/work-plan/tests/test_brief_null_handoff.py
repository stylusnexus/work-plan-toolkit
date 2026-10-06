"""brief must survive a track whose `last_handoff` is present but empty (null).

`meta.get("last_handoff", "")` only defaults a MISSING key, so a track written
with `last_handoff:` and no value reached `.startswith` as None and crashed the
whole daily brief.
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import brief
from lib.tracks import Track


def _track(last_handoff):
    return Track(
        path=Path("/notes/r/t.md"), name="t", has_frontmatter=True,
        needs_init=False, needs_filing=False, repo="org/r", folder="r",
        local_path=None,
        meta={"status": "active", "track": "t", "last_handoff": last_handoff,
              "github": {"issues": []}, "next_up": []},
        body="",
    )


class NullHandoffTest(unittest.TestCase):
    def _brief(self, track):
        buf = io.StringIO()
        with mock.patch.object(brief, "load_config", return_value={"repos": {}}), \
             mock.patch.object(brief, "discover_tracks", return_value=[track]), \
             mock.patch.object(brief, "_surface_archived_reopens"), \
             mock.patch.object(brief, "resolve_repo_for_dir"), \
             mock.patch.object(brief, "fetch_issues", return_value=[]), \
             mock.patch.object(brief, "find_new_issues_for_tracks", return_value={"t": []}):
            with redirect_stdout(buf):
                rc = brief.run(["--repo=all"])
        return rc, buf.getvalue()

    def test_null_last_handoff_does_not_crash(self):
        rc, out = self._brief(_track(None))
        self.assertEqual(rc, 0)
        self.assertIn("DAILY BRIEF", out)

    def test_missing_and_string_last_handoff_still_work(self):
        for value in ("", "2020-01-01"):
            with self.subTest(value=value):
                self.assertEqual(self._brief(_track(value))[0], 0)


if __name__ == "__main__":
    unittest.main()
