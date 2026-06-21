"""Batched last-commit-date lookup (#391): one `git log` walk yields the latest
commit datetime per path, replacing N per-path subprocess spawns. Offline —
`_git` is mocked, no real git invoked."""
import io
import json as _json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib import git_state
from commands import plan_status


class _FakeProc:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


# `git log --format=%cI --name-only` over three paths, newest-first. a.md last
# touched in the newest commit; b.md too; c.md only in the older commit.
LOG = (
    "2026-06-19T10:00:00-07:00\n"
    "\n"
    "docs/plans/a.md\n"
    "docs/plans/b.md\n"
    "2026-06-10T09:00:00-07:00\n"
    "\n"
    "docs/plans/a.md\n"
    "docs/plans/c.md\n"
)


class PathsLastCommitDatesTest(unittest.TestCase):
    def test_single_call_maps_each_path_to_its_latest(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=_FakeProc(LOG)) as g:
            res = git_state.paths_last_commit_dates(
                ["docs/plans/a.md", "docs/plans/b.md", "docs/plans/c.md"],
                Path("/repo"))
        g.assert_called_once()                       # ONE git spawn, not three
        self.assertEqual(res["docs/plans/a.md"].date().isoformat(), "2026-06-19")
        self.assertEqual(res["docs/plans/b.md"].date().isoformat(), "2026-06-19")
        self.assertEqual(res["docs/plans/c.md"].date().isoformat(), "2026-06-10")

    def test_batched_call_uses_name_only_walk(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=_FakeProc(LOG)) as g:
            git_state.paths_last_commit_dates(["docs/plans/a.md"], Path("/repo"))
        args = g.call_args.args
        self.assertIn("--name-only", args)
        self.assertIn("log", args)
        self.assertIn("docs/plans/a.md", args)       # path passed through

    def test_uncommitted_path_omitted(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=_FakeProc(LOG)):
            res = git_state.paths_last_commit_dates(
                ["docs/plans/a.md", "docs/plans/never.md"], Path("/repo"))
        self.assertIn("docs/plans/a.md", res)
        self.assertNotIn("docs/plans/never.md", res)  # no commit → omitted

    def test_empty_input_no_git_call(self):
        with mock.patch("lib.git_state._git") as g:
            self.assertEqual(git_state.paths_last_commit_dates([], Path("/repo")), {})
        g.assert_not_called()

    def test_git_failure_returns_empty(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=_FakeProc("", returncode=128)):
            self.assertEqual(
                git_state.paths_last_commit_dates(["docs/plans/a.md"], Path("/repo")), {})

    def test_offtree_paths_filtered_before_git(self):
        # An off-tree pathspec (../, absolute, ~) makes `git log` exit 128 and
        # poison the whole chunk; they must be dropped before the call (#391).
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=_FakeProc(LOG)) as g:
            res = git_state.paths_last_commit_dates(
                ["docs/plans/a.md", "../escape.md", "/abs/x.md", "~/h.md",
                 "a/../../b.md"], Path("/repo"))
        passed = g.call_args.args
        self.assertIn("docs/plans/a.md", passed)
        for bad in ("../escape.md", "/abs/x.md", "~/h.md", "a/../../b.md"):
            self.assertNotIn(bad, passed)        # never reaches git
        self.assertIn("docs/plans/a.md", res)

    def test_all_offtree_no_git_call(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git") as g:
            self.assertEqual(
                git_state.paths_last_commit_dates(["../x", "/y"], Path("/repo")), {})
        g.assert_not_called()

    def test_none_proc_returns_empty(self):
        with mock.patch("lib.git_state.Path.exists", return_value=True), \
             mock.patch("lib.git_state._git", return_value=None):
            self.assertEqual(
                git_state.paths_last_commit_dates(["docs/plans/a.md"], Path("/repo")), {})


class PlanStatusBatchesTest(unittest.TestCase):
    """run() must use the ONE batched call, not a per-doc git spawn (#391)."""

    def _repo(self, d):
        root = Path(d)
        (root / "docs/plans").mkdir(parents=True)
        # A Modify path is what drove the per-path committed_since git spawns.
        (root / "docs/plans/a.md").write_text(
            "# A\n\n- Create: `src/a.ts`\n- Modify: `src/x.ts`\n")
        (root / "docs/plans/b.md").write_text("# B\n\n- Create: `src/b.ts`\n")
        return root

    def test_run_batches_one_call_no_per_doc_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            with mock.patch("commands.plan_status.Path.cwd", return_value=root), \
                 mock.patch("commands.plan_status.git_state.paths_last_commit_dates",
                            return_value={}) as batch, \
                 mock.patch("commands.plan_status.git_state.path_last_commit_date") as per, \
                 mock.patch("commands.plan_status.git_state.paths_last_commit_date") as per_multi:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = plan_status.run(["--json"])
            self.assertEqual(rc, 0)
            batch.assert_called_once()      # one git walk for all docs + declared paths
            per.assert_not_called()         # no per-doc last-commit spawn
            per_multi.assert_not_called()   # no per-partial staleness spawn
            # committed_since is served from the injected map (run() passes a
            # closure to score_manifest), so its per-Modify-path git fallback
            # never runs — that was the real O(n) cost.
            docs = _json.loads(buf.getvalue())["docs"]
            self.assertEqual(len(docs), 2)


if __name__ == "__main__":
    unittest.main()
