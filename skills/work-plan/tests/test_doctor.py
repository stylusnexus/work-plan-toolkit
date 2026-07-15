"""Tests for the doctor subcommand — config-drift detection."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from commands import doctor
from lib.config import ConfigError


def _finding(findings, type_):
    return [f for f in findings if f["type"] == type_]


class TestStep0FatalLoad(unittest.TestCase):
    def _run_json_with_load_error(self, exc):
        with mock.patch("commands.doctor.load_config", side_effect=exc):
            with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
                code = doctor.run(["--json"])
            return code, out.getvalue()

    def test_config_error_produces_fatal_json_and_exit_0(self):
        code, out = self._run_json_with_load_error(ConfigError("missing notes_root"))
        self.assertEqual(code, 0)
        blob = json.loads(out)
        self.assertIn("missing notes_root", blob["fatal"])
        self.assertEqual(blob["attempts"], [])
        self.assertEqual(blob["findings"], [])

    def test_file_not_found_is_fatal(self):
        code, out = self._run_json_with_load_error(FileNotFoundError("no yq"))
        self.assertEqual(code, 0)
        self.assertIn("fatal", json.loads(out))

    def test_called_process_error_is_fatal(self):
        exc = subprocess.CalledProcessError(1, ["yq"], stderr="bad yaml")
        code, out = self._run_json_with_load_error(exc)
        self.assertEqual(code, 0)
        self.assertIn("fatal", json.loads(out))

    def test_json_decode_error_is_fatal(self):
        exc = json.JSONDecodeError("bad", "doc", 0)
        code, out = self._run_json_with_load_error(exc)
        self.assertEqual(code, 0)
        self.assertIn("fatal", json.loads(out))

    def test_os_error_is_fatal(self):
        code, out = self._run_json_with_load_error(OSError("read failed"))
        self.assertEqual(code, 0)
        self.assertIn("fatal", json.loads(out))

    def test_attribute_error_is_fatal(self):
        # Simulates `repos: null` reaching `.items()` inside load_config.
        code, out = self._run_json_with_load_error(AttributeError("'NoneType' object has no attribute 'items'"))
        self.assertEqual(code, 0)
        self.assertIn("fatal", json.loads(out))

    def test_unicode_decode_error_is_fatal(self):
        exc = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        code, out = self._run_json_with_load_error(exc)
        self.assertEqual(code, 0)
        self.assertIn("fatal", json.loads(out))

    def test_human_mode_exits_1_on_fatal(self):
        with mock.patch("commands.doctor.load_config", side_effect=ConfigError("bad")):
            with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
                code = doctor.run([])
        self.assertEqual(code, 1)
        printed = out.getvalue()
        self.assertIn("ERROR:", printed)
        self.assertIn("bad", printed)
        self.assertNotIn("{", printed)  # no JSON fallback shape leaked into human mode


class TestFieldShapeValidation(unittest.TestCase):
    def test_non_string_github_is_excluded_and_reported(self):
        cfg = {"repos": {"bad": {"github": 12345, "local": None}}, "_scalar_shape_keys": set()}
        valid, findings = doctor._validate_repo_field_shapes(cfg)
        self.assertNotIn("bad", valid)
        self.assertEqual(len(_finding(findings, "repo_entry_malformed")), 1)
        self.assertEqual(findings[0]["key"], "bad")

    def test_non_string_local_is_excluded_and_reported(self):
        cfg = {"repos": {"bad": {"github": "org/bad", "local": 42}}, "_scalar_shape_keys": set()}
        valid, findings = doctor._validate_repo_field_shapes(cfg)
        self.assertNotIn("bad", valid)
        self.assertEqual(len(_finding(findings, "repo_entry_malformed")), 1)

    def test_conforming_entries_pass_through_unaffected(self):
        cfg = {"repos": {"ok": {"github": "org/ok", "local": "/code/ok"}}, "_scalar_shape_keys": set()}
        valid, findings = doctor._validate_repo_field_shapes(cfg)
        self.assertIn("ok", valid)
        self.assertEqual(findings, [])

    def test_one_bad_entry_does_not_exclude_others(self):
        cfg = {"repos": {
            "bad": {"github": 1, "local": None},
            "ok": {"github": "org/ok", "local": None},
        }, "_scalar_shape_keys": set()}
        valid, findings = doctor._validate_repo_field_shapes(cfg)
        self.assertIn("ok", valid)
        self.assertNotIn("bad", valid)
        self.assertEqual(len(findings), 1)


class TestCleanConfigNoDrift(unittest.TestCase):
    def test_empty_repos_no_notes_root_findings_yields_clean_json(self):
        # A full-pipeline smoke test using a real empty notes_root, to be
        # extended in later tasks as Steps 1-4 are implemented — this proves
        # the skeleton wires Step 0 through to output correctly even with
        # zero repos configured.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"notes_root": tmp, "repos": {}, "_scalar_shape_keys": set()}
            with mock.patch("commands.doctor.load_config", return_value=cfg):
                with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
                    code = doctor.run(["--json"])
            self.assertEqual(code, 0)
            blob = json.loads(out.getvalue())
            self.assertEqual(blob["attempts"], [])
            self.assertEqual(blob["findings"], [])

    def test_empty_repos_no_notes_root_findings_yields_clean_human_mode(self):
        # Same clean-config scenario as test_empty_repos_no_notes_root_findings_yields_clean_json,
        # but exercising human mode (no --json flag) to ensure the success path
        # prints "No drift found." and exits with code 0.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"notes_root": tmp, "repos": {}, "_scalar_shape_keys": set()}
            with mock.patch("commands.doctor.load_config", return_value=cfg):
                with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
                    code = doctor.run([])
            self.assertEqual(code, 0)
            printed = out.getvalue()
            self.assertIn("No drift found.", printed)


class TestStep1CanonicalSlugs(unittest.TestCase):
    def test_matching_slug_no_finding(self):
        repos = {"foo": {"github": "org/foo", "local": None}}
        with mock.patch("commands.doctor.repo_full_name", return_value="org/foo"):
            canonical = doctor._resolve_canonical_slugs(repos)
            findings = doctor._step1_findings(repos, canonical)
        self.assertEqual(canonical["foo"], {"canonical": "org/foo", "unverified": False})
        self.assertEqual(findings, [])

    def test_matching_slug_is_case_insensitive(self):
        repos = {"foo": {"github": "Org/Foo", "local": None}}
        with mock.patch("commands.doctor.repo_full_name", return_value="org/foo"):
            canonical = doctor._resolve_canonical_slugs(repos)
            findings = doctor._step1_findings(repos, canonical)
        self.assertEqual(findings, [])

    def test_renamed_slug_is_fixable_finding(self):
        repos = {"foo": {"github": "org/old-name", "local": None}}
        with mock.patch("commands.doctor.repo_full_name", return_value="org/new-name"):
            canonical = doctor._resolve_canonical_slugs(repos)
            findings = doctor._step1_findings(repos, canonical)
        self.assertEqual(canonical["foo"]["canonical"], "org/new-name")
        renamed = _finding(findings, "github_rename_detected")
        self.assertEqual(len(renamed), 1)
        self.assertTrue(renamed[0]["fixable"])
        self.assertEqual(renamed[0]["old"], "org/old-name")
        self.assertEqual(renamed[0]["new"], "org/new-name")

    def test_renamed_slug_unsafe_key_not_fixable(self):
        repos = {"a.b": {"github": "org/old-name", "local": None}}
        with mock.patch("commands.doctor.repo_full_name", return_value="org/new-name"):
            canonical = doctor._resolve_canonical_slugs(repos)
            findings = doctor._step1_findings(repos, canonical)
        renamed = _finding(findings, "github_rename_detected")
        self.assertFalse(renamed[0]["fixable"])
        self.assertIn("unsafe", renamed[0]["message"].lower())

    def test_renamed_slug_scalar_shaped_not_fixable(self):
        repos = {"foo": {"github": "org/old-name", "local": None}}
        with mock.patch("commands.doctor.repo_full_name", return_value="org/new-name"):
            canonical = doctor._resolve_canonical_slugs(repos)
            findings = doctor._step1_findings(repos, canonical, scalar_shape_keys={"foo"})
        renamed = _finding(findings, "github_rename_detected")
        self.assertFalse(renamed[0]["fixable"])
        self.assertIn("scalar", renamed[0]["message"].lower())

    def test_unreachable_repo(self):
        repos = {"foo": {"github": "org/gone", "local": None}}
        with mock.patch("commands.doctor.repo_full_name", return_value=None):
            canonical = doctor._resolve_canonical_slugs(repos)
            findings = doctor._step1_findings(repos, canonical)
        self.assertEqual(canonical["foo"], {"canonical": "org/gone", "unverified": True})
        unreachable = _finding(findings, "github_repo_unreachable")
        self.assertEqual(len(unreachable), 1)
        self.assertFalse(unreachable[0]["fixable"])

    def test_aggregate_deadline_marks_unresolved_as_unreachable(self):
        import time
        def _slow(slug):
            time.sleep(0.3)
            return "org/foo"
        repos = {f"repo{i}": {"github": f"org/repo{i}", "local": None} for i in range(3)}
        with mock.patch("commands.doctor.repo_full_name", side_effect=_slow):
            with mock.patch("commands.doctor.SCAN_DEADLINE", 0.05):
                canonical = doctor._resolve_canonical_slugs(repos)
        # With a near-zero deadline every repo should be marked unreachable/unverified.
        self.assertTrue(all(v["unverified"] for v in canonical.values()))

    def test_deadline_bounds_actual_return_time_regardless_of_repo_count(self):
        import time
        def _slow(slug):
            time.sleep(1)  # long enough to still be "not done" at the deadline
            return "org/foo"
        # More repos than MAX_GH_WORKERS (4), so most are queued, never started.
        repos = {f"repo{i}": {"github": f"org/repo{i}", "local": None} for i in range(12)}
        with mock.patch("commands.doctor.repo_full_name", side_effect=_slow):
            with mock.patch("commands.doctor.SCAN_DEADLINE", 0.05):
                start = time.monotonic()
                canonical = doctor._resolve_canonical_slugs(repos)
                elapsed = time.monotonic() - start
        # Must return close to the deadline, NOT scale with repo count — 12
        # repos / MAX_GH_WORKERS=4 workers * 1s sleep would be ~3s+ if queued
        # jobs ran to completion instead of being cancelled at the deadline.
        self.assertLess(elapsed, 1.0)
        self.assertTrue(all(v["unverified"] for v in canonical.values()))


class TestStep2LocalPathChecks(unittest.TestCase):
    def test_relative_local_path(self):
        repos = {"foo": {"github": "org/foo", "local": "relative/path"}}
        findings = doctor._step2_findings(repos)
        self.assertEqual(len(_finding(findings, "local_path_relative")), 1)
        # Downstream checks should not ALSO fire for this entry.
        self.assertEqual(_finding(findings, "missing_local"), [])

    def test_missing_local_path(self):
        repos = {"foo": {"github": "org/foo", "local": "/definitely/not/here/xyz"}}
        findings = doctor._step2_findings(repos)
        self.assertEqual(len(_finding(findings, "missing_local")), 1)

    def test_local_not_git(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repos = {"foo": {"github": "org/foo", "local": tmp}}
            findings = doctor._step2_findings(repos)
        self.assertEqual(len(_finding(findings, "local_not_git")), 1)

    def test_no_finding_when_local_absent(self):
        repos = {"foo": {"github": "org/foo", "local": None}}
        self.assertEqual(doctor._step2_findings(repos), [])

    def test_remote_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            repos = {"foo": {"github": "org/foo", "local": tmp}}
            with mock.patch("commands.doctor._git", return_value=None):
                findings = doctor._step2_findings(repos)
        self.assertEqual(len(_finding(findings, "local_remote_missing")), 1)

    def test_remote_mismatch_github_fork(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            repos = {"foo": {"github": "org/foo", "local": tmp}}
            fake = mock.Mock(returncode=0, stdout="git@github.com:someone/fork.git\n")
            with mock.patch("commands.doctor._git", return_value=fake):
                findings = doctor._step2_findings(repos, canonical={"foo": {"canonical": "org/foo", "unverified": False}})
        mismatch = _finding(findings, "local_remote_mismatch")
        self.assertEqual(len(mismatch), 1)
        self.assertFalse(mismatch[0]["fixable"])

    def test_remote_non_github_host(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            repos = {"foo": {"github": "org/foo", "local": tmp}}
            fake = mock.Mock(returncode=0, stdout="git@gitlab.com:org/foo.git\n")
            with mock.patch("commands.doctor._git", return_value=fake):
                findings = doctor._step2_findings(repos, canonical={"foo": {"canonical": "org/foo", "unverified": False}})
        mismatch = _finding(findings, "local_remote_mismatch")
        self.assertEqual(len(mismatch), 1)
        self.assertIn("non-github", mismatch[0]["message"].lower())
        self.assertFalse(mismatch[0]["fixable"])

    def test_remote_host_with_explicit_port_still_recognized_as_github(self):
        # https://github.com:8080/org/foo.git — an explicit port on a genuine
        # github.com remote must not be misclassified as a non-GitHub host.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            repos = {"foo": {"github": "org/foo", "local": tmp}}
            fake = mock.Mock(returncode=0, stdout="https://github.com:8080/org/foo.git\n")
            with mock.patch("commands.doctor._git", return_value=fake):
                findings = doctor._step2_findings(repos, canonical={"foo": {"canonical": "org/foo", "unverified": False}})
        self.assertEqual(_finding(findings, "local_remote_mismatch"), [])

    def test_happy_path_no_findings(self):
        # Valid absolute local path, valid git repo, origin matching the
        # canonical slug — Step 2 should report nothing.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").mkdir()
            repos = {"foo": {"github": "org/foo", "local": tmp}}
            fake = mock.Mock(returncode=0, stdout="git@github.com:org/foo.git\n")
            with mock.patch("commands.doctor._git", return_value=fake):
                findings = doctor._step2_findings(repos, canonical={"foo": {"canonical": "org/foo", "unverified": False}})
        self.assertEqual(findings, [])


class TestStep3WholeConfigChecks(unittest.TestCase):
    def test_duplicate_local(self):
        repos = {
            "a": {"github": "org/a", "local": "/code/dup"},
            "b": {"github": "org/b", "local": "/code/dup"},
        }
        cfg = {"notes_root": "/tmp/notes"}
        findings = doctor._step3_findings(repos, canonical={}, cfg=cfg)
        self.assertEqual(len(_finding(findings, "duplicate_local")), 2)

    def test_duplicate_github(self):
        repos = {
            "a": {"github": "org/x", "local": None},
            "b": {"github": "org/x", "local": None},
        }
        canonical = {"a": {"canonical": "org/x", "unverified": False},
                     "b": {"canonical": "org/x", "unverified": False}}
        cfg = {"notes_root": "/tmp/notes"}
        findings = doctor._step3_findings(repos, canonical, cfg)
        self.assertEqual(len(_finding(findings, "duplicate_github")), 2)

    def test_notes_root_invalid_blank(self):
        cfg = {"notes_root": ""}
        findings = doctor._step3_findings({}, {}, cfg)
        self.assertEqual(len(_finding(findings, "notes_root_invalid")), 1)

    def test_notes_root_invalid_relative(self):
        cfg = {"notes_root": "."}
        findings = doctor._step3_findings({}, {}, cfg)
        self.assertEqual(len(_finding(findings, "notes_root_invalid")), 1)

    def test_notes_root_invalid_bare_root(self):
        cfg = {"notes_root": "/"}
        findings = doctor._step3_findings({}, {}, cfg)
        self.assertEqual(len(_finding(findings, "notes_root_invalid")), 1)

    def test_notes_root_missing(self):
        cfg = {"notes_root": "/definitely/not/here/xyz"}
        findings = doctor._step3_findings({}, {}, cfg)
        self.assertEqual(len(_finding(findings, "notes_root_missing")), 1)

    def test_notes_root_ok_no_finding(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"notes_root": tmp}
            findings = doctor._step3_findings({}, {}, cfg)
        self.assertEqual(_finding(findings, "notes_root_invalid"), [])
        self.assertEqual(_finding(findings, "notes_root_missing"), [])


class TestStep4NotesRootWalk(unittest.TestCase):
    def _mk(self, tmp, subpath, content):
        p = Path(tmp) / subpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_orphaned_folder(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "unknown-project/track.md", "---\n---\nbody")
            cfg = {"notes_root": tmp}
            findings = doctor._step4_findings(cfg, repos={}, canonical={}, walkable=True)
        self.assertEqual(len(_finding(findings, "orphaned_folder")), 1)

    def test_not_orphaned_when_folder_matches_repo_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/track.md", "---\ngithub:\n  repo: org/known\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/known", "local": None}}
            canonical = {"known": {"canonical": "org/known", "unverified": False}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        self.assertEqual(_finding(findings, "orphaned_folder"), [])

    def test_dotdir_never_orphaned(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, ".git/config", "junk")
            self._mk(tmp, ".obsidian/workspace.json", "{}")
            cfg = {"notes_root": tmp}
            findings = doctor._step4_findings(cfg, repos={}, canonical={}, walkable=True)
        self.assertEqual(_finding(findings, "orphaned_folder"), [])

    def test_empty_folder_never_orphaned(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty-dir").mkdir()
            cfg = {"notes_root": tmp}
            findings = doctor._step4_findings(cfg, repos={}, canonical={}, walkable=True)
        self.assertEqual(_finding(findings, "orphaned_folder"), [])

    def test_track_unreadable_bad_yaml(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/bad.md", "---\ngithub: [this is not a mapping\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/known", "local": None}}
            canonical = {"known": {"canonical": "org/known", "unverified": False}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        self.assertEqual(len(_finding(findings, "track_unreadable")), 1)

    def test_track_unreadable_non_mapping_root(self):
        # Valid YAML but the frontmatter root itself is a list, not a mapping
        # (e.g. a stray leading '-' turns the whole block into a YAML
        # sequence) — a distinct trigger from a parse exception.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/bad.md", "---\n- a\n- b\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/known", "local": None}}
            canonical = {"known": {"canonical": "org/known", "unverified": False}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        self.assertEqual(len(_finding(findings, "track_unreadable")), 1)

    def test_track_unreadable_non_mapping_github(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/bad.md", "---\ngithub: not-a-mapping\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/known", "local": None}}
            canonical = {"known": {"canonical": "org/known", "unverified": False}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        self.assertEqual(len(_finding(findings, "track_unreadable")), 1)

    def test_track_unreadable_non_string_repo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/bad.md", "---\ngithub:\n  repo: 12345\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/known", "local": None}}
            canonical = {"known": {"canonical": "org/known", "unverified": False}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        self.assertEqual(len(_finding(findings, "track_unreadable")), 1)

    def test_stale_frontmatter(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/track.md", "---\ngithub:\n  repo: org/old\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/old", "local": None}}
            canonical = {"known": {"canonical": "org/new", "unverified": False}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        stale = _finding(findings, "stale_frontmatter")
        self.assertEqual(len(stale), 1)
        self.assertTrue(stale[0]["fixable"])
        self.assertEqual(stale[0]["old"], "org/old")
        self.assertEqual(stale[0]["new"], "org/new")

    def test_stale_frontmatter_unverified_never_fixable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/track.md", "---\ngithub:\n  repo: org/old\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/old", "local": None}}
            canonical = {"known": {"canonical": "org/old", "unverified": True}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        stale = _finding(findings, "stale_frontmatter")
        self.assertEqual(stale, [])  # matches configured value, and unverified — no finding either way here

    def test_archived_track_is_scanned(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._mk(tmp, "known/archive/old.md", "---\ngithub:\n  repo: org/old\n---\nbody")
            cfg = {"notes_root": tmp}
            repos = {"known": {"github": "org/old", "local": None}}
            canonical = {"known": {"canonical": "org/new", "unverified": False}}
            findings = doctor._step4_findings(cfg, repos, canonical, walkable=True)
        self.assertEqual(len(_finding(findings, "stale_frontmatter")), 1)

    def test_not_walkable_returns_no_findings(self):
        findings = doctor._step4_findings({"notes_root": "/nope"}, {}, {}, walkable=False)
        self.assertEqual(findings, [])


class TestApplyFixesConfigRename(unittest.TestCase):
    def test_fixable_rename_writes_config_and_ledger_entry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.yml"
            cfg_path.write_text("notes_root: /tmp/notes\nrepos:\n  foo:\n    github: org/old\n")
            finding = doctor._finding(
                "github_rename_detected", key="foo", fixable=True,
                message="renamed", old="org/old", new="org/new",
            )
            with mock.patch("commands.doctor.DEFAULT_CONFIG_PATH", cfg_path):
                ledger = doctor._apply_config_fixes([finding])
            self.assertEqual(len(ledger), 1)
            self.assertTrue(ledger[0]["fixed"])
            self.assertIsNone(ledger[0]["error"])
            text = cfg_path.read_text()
            self.assertIn("org/new", text)

    def test_yq_failure_recorded_as_ledger_error(self):
        finding = doctor._finding(
            "github_rename_detected", key="foo", fixable=True,
            message="renamed", old="org/old", new="org/new",
        )
        exc = subprocess.CalledProcessError(1, ["yq"], stderr="boom")
        with mock.patch("commands.doctor.write_repo_field", side_effect=exc):
            ledger = doctor._apply_config_fixes([finding])
        self.assertFalse(ledger[0]["fixed"])
        self.assertIn("boom", ledger[0]["error"])

    def test_unfixable_findings_are_never_attempted(self):
        finding = doctor._finding(
            "github_rename_detected", key="foo", fixable=False,
            message="unsafe key", old="org/old", new="org/new",
        )
        with mock.patch("commands.doctor.write_repo_field") as m:
            ledger = doctor._apply_config_fixes([finding])
        m.assert_not_called()
        self.assertEqual(ledger, [])


class TestDirtyFilePolicy(unittest.TestCase):
    def test_pre_snapshot_failure_skips_all_frontmatter_writes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "known" / "track.md"
            track.parent.mkdir()
            track.write_text("---\ngithub:\n  repo: org/old\n---\nbody")
            finding = doctor._finding(
                "stale_frontmatter", folder="known", track="track.md", fixable=True,
                message="stale", old="org/old", new="org/new",
            )
            with mock.patch("commands.doctor.dirty_paths_checked", return_value=(False, set())):
                ledger, skipped_write = doctor._apply_frontmatter_fixes(
                    Path(tmp), [finding], auto_commit_enabled=True,
                )
            self.assertEqual(ledger, [])
            self.assertIn("org/old", track.read_text())  # untouched
            self.assertTrue(skipped_write)

    def test_already_dirty_file_is_skipped_others_still_fixed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dirty = Path(tmp) / "known" / "dirty.md"
            clean = Path(tmp) / "known" / "clean.md"
            dirty.parent.mkdir()
            dirty.write_text("---\ngithub:\n  repo: org/old\n---\nbody")
            clean.write_text("---\ngithub:\n  repo: org/old\n---\nbody")
            findings = [
                doctor._finding("stale_frontmatter", folder="known", track="dirty.md",
                                 fixable=True, old="org/old", new="org/new", message="m"),
                doctor._finding("stale_frontmatter", folder="known", track="clean.md",
                                 fixable=True, old="org/old", new="org/new", message="m"),
            ]
            with mock.patch("commands.doctor.dirty_paths_checked",
                            return_value=(True, {"known/dirty.md"})):
                ledger, _ = doctor._apply_frontmatter_fixes(Path(tmp), findings, auto_commit_enabled=False)
            fixed_tracks = {a["track"] for a in ledger if a["fixed"]}
            self.assertEqual(fixed_tracks, {"clean.md"})
            self.assertIn("org/old", dirty.read_text())
            self.assertIn("org/new", clean.read_text())

    def test_write_failure_recorded_in_ledger_and_residual(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "known" / "track.md"
            track.parent.mkdir()
            track.write_text("---\ngithub:\n  repo: org/old\n---\nbody")
            finding = doctor._finding(
                "stale_frontmatter", folder="known", track="track.md", fixable=True,
                message="stale", old="org/old", new="org/new",
            )
            with mock.patch("commands.doctor.dirty_paths_checked", return_value=(True, set())):
                with mock.patch("commands.doctor.write_file", side_effect=ValueError("symlink")):
                    ledger, _ = doctor._apply_frontmatter_fixes(Path(tmp), [finding], auto_commit_enabled=False)
            self.assertFalse(ledger[0]["fixed"])
            self.assertIn("symlink", ledger[0]["error"])

    def test_auto_commit_gated_on_notes_vcs_setting(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            track = Path(tmp) / "known" / "track.md"
            track.parent.mkdir()
            track.write_text("---\ngithub:\n  repo: org/old\n---\nbody")
            finding = doctor._finding(
                "stale_frontmatter", folder="known", track="track.md", fixable=True,
                message="stale", old="org/old", new="org/new",
            )
            with mock.patch("commands.doctor.dirty_paths_checked", return_value=(True, set())):
                with mock.patch("commands.doctor.auto_commit") as m:
                    doctor._apply_frontmatter_fixes(Path(tmp), [finding], auto_commit_enabled=False)
            m.assert_not_called()

    def test_archived_name_collision_is_not_blindly_overwritten(self):
        # A finding's folder/track fields lose any intermediate path segment
        # (see _step4_findings: folder=rel.parts[0], track=md_path.name), so a
        # finding raised against a nested/archived file (e.g.
        # 'known/archive/old.md') collides on-disk with 'known/old.md' if one
        # exists. _apply_frontmatter_fixes must refuse to write when the
        # resolved path's current value doesn't match the finding's `old`
        # value, rather than blindly overwriting whatever file it lands on.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # The path _apply_frontmatter_fixes actually resolves to
            # ('known/old.md') is a DIFFERENT, unrelated track — not the
            # archived file the finding was really raised against.
            unrelated = Path(tmp) / "known" / "old.md"
            unrelated.parent.mkdir()
            unrelated.write_text("---\ngithub:\n  repo: org/unrelated\n---\nbody")
            finding = doctor._finding(
                "stale_frontmatter", folder="known", track="old.md", fixable=True,
                message="stale", old="org/old", new="org/new",
            )
            with mock.patch("commands.doctor.dirty_paths_checked", return_value=(True, set())):
                ledger, _ = doctor._apply_frontmatter_fixes(Path(tmp), [finding], auto_commit_enabled=False)
            self.assertFalse(ledger[0]["fixed"])
            self.assertIsNotNone(ledger[0]["error"])
            # The unrelated file must be completely untouched.
            self.assertIn("org/unrelated", unrelated.read_text())


class TestFixThenRescan(unittest.TestCase):
    def test_fixable_only_fixture_converges_to_clean_on_second_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.yml"
            notes_root = Path(tmp) / "notes"
            (notes_root / "known").mkdir(parents=True)
            (notes_root / "known" / "track.md").write_text(
                "---\ngithub:\n  repo: org/old\n---\nbody"
            )
            cfg_path.write_text(
                f"notes_root: {notes_root}\nrepos:\n  known:\n    github: org/old\n"
            )
            # The dirty-file safety check (dirty_paths_checked) requires
            # notes_root to actually be a git repo to report ok_before=True —
            # this mirrors a real user who has opted into notes-vcs. Without
            # this, the pre-fix snapshot call fails closed (see
            # TestDirtyFilePolicy) and the frontmatter fix would be
            # (correctly) skipped, which isn't what this test is exercising.
            for git_args in (
                ["init"],
                ["add", "-A"],
                ["-c", "user.email=doctor-test@example.com",
                 "-c", "user.name=doctor-test", "commit", "-m", "init"],
            ):
                subprocess.run(["git", "-C", str(notes_root), *git_args],
                                capture_output=True, text=True, check=True)

            def _load(*_a, **_kw):
                from lib.config import load_config as real_load
                return real_load(path=cfg_path, notes_root=notes_root)

            with mock.patch("commands.doctor.DEFAULT_CONFIG_PATH", cfg_path):
                with mock.patch("commands.doctor.load_config", side_effect=_load):
                    with mock.patch("commands.doctor.repo_full_name", return_value="org/new"):
                        with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out1:
                            code1 = doctor.run(["--json", "--fix"])
                        with mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out2:
                            code2 = doctor.run(["--json"])
            self.assertEqual(code1, 0)
            blob1 = json.loads(out1.getvalue())
            self.assertTrue(any(a["fixed"] for a in blob1["attempts"]))
            self.assertEqual(code2, 0)
            blob2 = json.loads(out2.getvalue())
            self.assertEqual(blob2["findings"], [])


if __name__ == "__main__":
    unittest.main()
