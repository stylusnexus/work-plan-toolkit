"""brief cwd auto-scope (#358 Phase 2).

Exercises brief.run()'s scope resolution with the resolver, config loader,
track discovery, and the archived-reopen pass all mocked — so no network/git.
Tracks are inactive (status 'shipped') so the render loop stays trivial; we
assert behavior through the banner text and the `repo_key` threaded into
`_surface_archived_reopens` (which is exactly the value used to scope both the
track list and the archived callouts).
"""
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from commands import brief


def _track(folder, repo):
    return types.SimpleNamespace(
        has_frontmatter=True,
        meta={"status": "shipped"},   # inactive → no per-track render
        needs_init=False,
        needs_filing=False,
        folder=folder,
        repo=repo,
        path=Path(f"/notes/{folder}/{folder}.md"),
    )


CFG = {"repos": {
    "work-plan-toolkit": {"local": "/code/wpt", "github": "stylusnexus/work-plan-toolkit"},
    "defect-scan": {"local": "/code/ds", "github": "stylusnexus/defect-scan"},
}}

TRACKS = [
    _track("work-plan-toolkit", "stylusnexus/work-plan-toolkit"),
    _track("defect-scan", "stylusnexus/defect-scan"),
]

BANNER = "Scoped to repo"


def _run(args, cfg=None, resolve_return=mock.DEFAULT):
    """Run brief.run(args) with collaborators mocked. Returns (stdout, archived_mock, resolve_mock)."""
    cfg = CFG if cfg is None else cfg
    buf = io.StringIO()
    with mock.patch.object(brief, "load_config", return_value=cfg), \
         mock.patch.object(brief, "discover_tracks", return_value=list(TRACKS)), \
         mock.patch.object(brief, "_surface_archived_reopens") as archived, \
         mock.patch.object(brief, "resolve_repo_for_dir") as resolve:
        if resolve_return is not mock.DEFAULT:
            resolve.return_value = resolve_return
        with redirect_stdout(buf):
            brief.run(args)
    return buf.getvalue(), archived, resolve


def _archived_repo_key(archived):
    self_call = archived.call_args
    return self_call.kwargs.get("repo_key")


class BriefAutoScopeTest(unittest.TestCase):
    # --- auto-detect on (default) -------------------------------------------

    def test_autoscope_prints_banner_and_scopes(self):
        out, archived, _ = _run(
            [], resolve_return={"key": "work-plan-toolkit",
                                "github": "stylusnexus/work-plan-toolkit",
                                "matched_by": "local"})
        self.assertIn(BANNER, out)
        self.assertIn("work-plan-toolkit", out)
        # archived-reopen pass scoped to the same detected key
        self.assertEqual(_archived_repo_key(archived), "work-plan-toolkit")

    def test_archived_reopens_scoped_to_detected_repo(self):
        _, archived, _ = _run(
            [], resolve_return={"key": "defect-scan",
                                "github": "stylusnexus/defect-scan",
                                "matched_by": "local"})
        self.assertEqual(_archived_repo_key(archived), "defect-scan")

    def test_banner_printed_exactly_once(self):
        out, _, _ = _run(
            [], resolve_return={"key": "work-plan-toolkit",
                                "github": "stylusnexus/work-plan-toolkit",
                                "matched_by": "local"})
        self.assertEqual(out.count(BANNER), 1)

    def test_no_match_shows_all_no_banner(self):
        out, archived, _ = _run([], resolve_return=None)
        self.assertNotIn(BANNER, out)
        self.assertIsNone(_archived_repo_key(archived))

    # --- explicit --repo / escape hatch -------------------------------------

    def test_repo_all_shows_everything_no_banner_no_autodetect(self):
        out, archived, resolve = _run(["--repo=all"])
        self.assertNotIn(BANNER, out)
        self.assertIsNone(_archived_repo_key(archived))
        resolve.assert_not_called()   # --repo=all must short-circuit auto-detect

    def test_explicit_repo_scopes_without_banner_or_autodetect(self):
        out, archived, resolve = _run(["--repo=defect-scan"])
        self.assertNotIn(BANNER, out)
        self.assertEqual(_archived_repo_key(archived), "defect-scan")
        resolve.assert_not_called()

    # --- opt-out -------------------------------------------------------------

    def test_optout_disables_autoscope(self):
        cfg = {"repos": CFG["repos"], "brief_auto_scope": False}
        out, archived, resolve = _run([], cfg=cfg)
        self.assertNotIn(BANNER, out)
        self.assertIsNone(_archived_repo_key(archived))
        resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
