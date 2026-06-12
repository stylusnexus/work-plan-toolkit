"""Tests for the plan-status staleness clock (#164).

The clock keys off a plan's DECLARED manifest files (which get committed) — not
the plan doc's own git date, which is null because plan docs are gitignored.
All git is mocked; these run offline.
"""
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from lib import git_state
from lib import manifest
from lib import verdict as verdict_mod
from commands import plan_status


class TestPathsLastCommitDate(unittest.TestCase):
    def test_returns_max_date_over_paths(self):
        proc = mock.Mock(returncode=0, stdout="2026-06-10T12:00:00+00:00")
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git", return_value=proc):
            got = git_state.paths_last_commit_date(
                ["a.py", "b.py"], Path("/repo"))
        self.assertEqual(got, datetime(2026, 6, 10, 12, 0, 0))

    def test_empty_paths_is_none(self):
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git") as g:
            self.assertIsNone(git_state.paths_last_commit_date([], Path("/repo")))
            g.assert_not_called()

    def test_empty_stdout_is_none(self):
        proc = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(git_state, "_git", return_value=proc):
            self.assertIsNone(
                git_state.paths_last_commit_date(["a.py"], Path("/repo")))


class TestStallDaysConstant(unittest.TestCase):
    def test_default_is_14(self):
        self.assertEqual(verdict_mod.STALL_DAYS, 14)


class TestUncheckedCheckboxLabels(unittest.TestCase):
    def test_captures_unticked_labels_in_order(self):
        text = (
            "- [x] Phase 1 — git helper\n"
            "- [x] Phase 2 — manifest\n"
            "- [ ] Phase 4 — tests\n"
            "- [ ] Phase 5 — docs\n"
        )
        self.assertEqual(
            manifest.unchecked_checkbox_labels(text),
            ["Phase 4 — tests", "Phase 5 — docs"],
        )

    def test_cap_limits_results(self):
        text = "\n".join(f"- [ ] item {i}" for i in range(20))
        got = manifest.unchecked_checkbox_labels(text)
        self.assertEqual(len(got), 10)
        self.assertEqual(got[0], "item 0")


class _FakePath:
    def __init__(self, name):
        self.name = name


class _Doc:
    @classmethod
    def make(cls, rel="plans/p.md", kind="plan", name="2026-05-01-p.md"):
        d = cls.__new__(cls)
        d.rel = rel
        d.kind = kind
        d.path = _FakePath(name)
        return d


def _decl(path):
    return manifest.DeclaredPath(kind="create", path=path)


class TestEvaluateStaleness(unittest.TestCase):
    """The staleness ladder fires only for partial verdicts and keys off the
    manifest files' commit date, not the plan doc's own (gitignored) date."""

    def setUp(self):
        self.today = date(2026, 6, 12)
        self.partial = verdict_mod.Verdict("partial", "\U0001f7e1", "files")
        self.decls = [_decl("src/a.py"), _decl("src/b.py")]

    def _evaluate(self, manifest_date, on_disk, verdict=None, text="body"):
        """Run _evaluate with manifest.* / git_state.* / classify mocked.

        manifest_date: what paths_last_commit_date returns.
        on_disk: which declared paths _declared_paths_on_disk reports present.
        """
        v = verdict or self.partial
        doc = _Doc.make()
        with mock.patch.object(plan_status, "_read", return_value=text), \
                mock.patch.object(manifest, "parse_declared_paths", return_value=self.decls), \
                mock.patch.object(manifest, "plan_date_from_filename", return_value=None), \
                mock.patch.object(manifest, "score_manifest",
                                  return_value=manifest.ManifestScore(2, 1, {})), \
                mock.patch.object(manifest, "count_checkboxes", return_value=(1, 4)), \
                mock.patch.object(manifest, "out_of_tree_ratio", return_value=0.0), \
                mock.patch.object(manifest, "unchecked_checkbox_labels",
                                  return_value=["do x"]), \
                mock.patch.object(plan_status, "_declared_paths_on_disk",
                                  return_value=on_disk), \
                mock.patch.object(git_state, "path_last_commit_date", return_value=None), \
                mock.patch.object(git_state, "paths_last_commit_date",
                                  return_value=manifest_date), \
                mock.patch.object(verdict_mod, "classify", return_value=v):
            return plan_status._evaluate(doc, Path("/repo"), self.today, 60, 14)

    def test_partial_cold_is_stalled(self):
        cold = datetime(2026, 5, 1, 12, 0, 0)  # 42 days before today
        row = self._evaluate(cold, ["src/a.py", "src/b.py"])
        self.assertTrue(row["stalled"])
        self.assertEqual(row["manifest_last_touched"], "2026-05-01")

    def test_partial_warm_is_not_stalled(self):
        warm = datetime(2026, 6, 10, 12, 0, 0)  # 2 days before today
        row = self._evaluate(warm, ["src/a.py"])
        self.assertFalse(row["stalled"])

    def test_partial_no_files_on_disk_is_not_stalled(self):
        row = self._evaluate(None, [])
        self.assertFalse(row["stalled"])
        self.assertIsNone(row["manifest_last_touched"])

    def test_doc_uncommitted_but_manifest_committed_is_stalled(self):
        # path_last_commit_date (doc) is None, but manifest committed 42d ago.
        cold = datetime(2026, 5, 1, 12, 0, 0)
        row = self._evaluate(cold, ["src/a.py"])
        self.assertTrue(row["stalled"])
        self.assertIsNone(row["last_touched"])  # doc date stays None

    def test_present_but_never_committed_is_stalled(self):
        # files exist on disk but manifest date is None -> never committed
        row = self._evaluate(None, ["src/a.py"])
        self.assertTrue(row["stalled"])

    def test_emits_unchecked_items_and_stall_days(self):
        row = self._evaluate(datetime(2026, 6, 10), ["src/a.py"])
        self.assertEqual(row["unchecked_items"], ["do x"])
        self.assertEqual(row["stall_days"], 14)

    def test_non_partial_is_never_stalled(self):
        shipped = verdict_mod.Verdict("shipped", "✅", "files")
        row = self._evaluate(None, [], verdict=shipped)
        self.assertFalse(row["stalled"])


class TestResolveStallDays(unittest.TestCase):
    def test_known_flag_set_includes_stall_days(self):
        self.assertIn("--stall-days", plan_status.KNOWN)

    def test_flag_beats_config_beats_default(self):
        with mock.patch.object(plan_status.config_mod, "load_config",
                               return_value={"stall_days": 30}):
            self.assertEqual(
                plan_status._resolve_stall_days({"--stall-days": "45"}), 45)

    def test_config_beats_default(self):
        with mock.patch.object(plan_status.config_mod, "load_config",
                               return_value={"stall_days": 30}):
            self.assertEqual(plan_status._resolve_stall_days({}), 30)

    def test_default_when_unset(self):
        with mock.patch.object(plan_status.config_mod, "load_config",
                               return_value={}):
            self.assertEqual(plan_status._resolve_stall_days({}), 14)

    def test_non_integer_flag_falls_through(self):
        with mock.patch.object(plan_status.config_mod, "load_config",
                               return_value={}):
            self.assertEqual(
                plan_status._resolve_stall_days({"--stall-days": "abc"}), 14)


if __name__ == "__main__":
    unittest.main()


class TestDeclaredPathsOnDiskGuards(unittest.TestCase):
    """A junk declared path ('/'), a directory, or an out-of-tree '../x' must be
    excluded — otherwise they poison `git log -- <paths>` and falsely stall an
    actively-built plan (regression from the smoke test for #164)."""

    def test_excludes_root_slash_dirs_and_escapes_keeps_real_files(self):
        import tempfile, os
        from lib.manifest import DeclaredPath
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "src").mkdir()
            real = "src/a.py"
            (root / real).write_text("x")
            # a sibling file outside the repo root
            outside = Path(td).parent / "escape_probe_164.py"
            try:
                outside.write_text("x")
                decls = [
                    DeclaredPath(kind="create", path=real),       # real file -> kept
                    DeclaredPath(kind="create", path="/"),        # resolves to FS root dir -> dropped
                    DeclaredPath(kind="create", path="src"),      # a directory -> dropped
                    DeclaredPath(kind="modify", path=f"../{outside.name}"),  # out-of-tree -> dropped
                ]
                got = plan_status._declared_paths_on_disk(decls, root)
                self.assertEqual(got, [real])
            finally:
                if outside.exists():
                    outside.unlink()
