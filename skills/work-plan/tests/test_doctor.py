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


if __name__ == "__main__":
    unittest.main()
