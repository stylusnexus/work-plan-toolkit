"""Native Windows regression tests for installer launcher ownership."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(os.name == "nt" and POWERSHELL, "requires native Windows PowerShell")
class InstallerPowerShellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / "target"
        self.target.mkdir()
        self.env = {
            **os.environ,
            "HOME": str(self.root / "home"),
            "USERPROFILE": str(self.root / "home"),
        }
        (self.root / "home").mkdir()

    def run_script(self, name, *, stdin="", env=None):
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-File", str(REPO / name),
             "-Target", str(self.target)],
            input=stdin, text=True, capture_output=True, env=env or self.env,
        )

    def install(self, *, stdin=""):
        result = self.run_script("install.ps1", stdin=stdin)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_fresh_and_managed_reinstall_create_verified_markers(self):
        self.install()
        for name in ("work-plan", "work-plan.cmd"):
            launcher = self.target / "bin" / name
            marker = Path(f"{launcher}.installed-from")
            self.assertTrue(launcher.is_file())
            self.assertRegex(marker.read_text(encoding="utf-8"),
                             r"^stylusnexus/work-plan-toolkit launcher v1\nsha256=[0-9a-f]{64}\n$")
        result = self.install()
        self.assertNotIn("Overwrite?", result.stdout)

    def test_unmanaged_launchers_survive_install_and_uninstall_by_default(self):
        bindir = self.target / "bin"
        bindir.mkdir()
        sh = bindir / "work-plan"
        cmd = bindir / "work-plan.cmd"
        sh.write_bytes(b"custom sh\n")
        cmd.write_bytes(b"custom cmd\r\n")

        self.install(stdin="n\nn\n")
        self.assertEqual(sh.read_bytes(), b"custom sh\n")
        self.assertEqual(cmd.read_bytes(), b"custom cmd\r\n")
        result = self.run_script("uninstall.ps1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sh.read_bytes(), b"custom sh\n")
        self.assertEqual(cmd.read_bytes(), b"custom cmd\r\n")

    def test_unmanaged_launchers_can_be_accepted_and_become_managed(self):
        bindir = self.target / "bin"
        bindir.mkdir()
        (bindir / "work-plan").write_bytes(b"custom sh\n")
        (bindir / "work-plan.cmd").write_bytes(b"custom cmd\n")

        self.install(stdin="y\ny\n")

        self.assertTrue((bindir / "work-plan.installed-from").is_file())
        self.assertTrue((bindir / "work-plan.cmd.installed-from").is_file())

    def test_modified_managed_launchers_are_preserved(self):
        self.install()
        sh = self.target / "bin/work-plan"
        cmd = self.target / "bin/work-plan.cmd"
        sh.write_bytes(b"modified sh\n")
        cmd.write_bytes(b"modified cmd\n")
        self.install(stdin="n\nn\n")
        self.assertEqual(sh.read_bytes(), b"modified sh\n")
        self.assertEqual(cmd.read_bytes(), b"modified cmd\n")
        result = self.run_script("uninstall.ps1")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(sh.exists())
        self.assertTrue(cmd.exists())

    def test_managed_launchers_uninstall_with_markers(self):
        self.install()
        result = self.run_script("uninstall.ps1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ("work-plan", "work-plan.cmd"):
            launcher = self.target / "bin" / name
            self.assertFalse(launcher.exists())
            self.assertFalse(Path(f"{launcher}.installed-from").exists())

    def test_declined_required_skill_aborts_before_dependent_writes(self):
        skill = self.target / "skills/work-plan"
        skill.mkdir(parents=True)
        user_file = skill / "user-file.md"
        user_file.write_bytes(b"mine\n")
        result = self.run_script("install.ps1", stdin="n\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(skill.iterdir()), [user_file])
        self.assertFalse((self.target / "bin/work-plan").exists())
        self.assertFalse((self.target / "commands/work-plan.md").exists())
        self.assertNotIn("Done.", result.stdout)

    def test_failed_smoke_is_fatal_and_never_prints_done(self):
        real_python = shutil.which("python") or sys.executable
        toolbin = self.root / "toolbin"
        toolbin.mkdir()
        wrapper = toolbin / "python.cmd"
        wrapper.write_text(
            "@echo off\r\n"
            "if \"%~4\"==\"--help\" exit /b 9\r\n"
            f'"{real_python}" %*\r\nexit /b %ERRORLEVEL%\r\n',
            encoding="utf-8",
        )
        env = {**self.env, "PATH": f"{toolbin}{os.pathsep}{self.env['PATH']}"}
        result = self.run_script("install.ps1", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation is incomplete", result.stdout)
        self.assertNotIn("Done.", result.stdout)


if __name__ == "__main__":
    unittest.main()
