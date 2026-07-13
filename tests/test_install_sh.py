"""Native regression tests for install.sh/uninstall.sh ownership boundaries."""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class InstallerShellTest(unittest.TestCase):
    def setUp(self):
        if os.name == "nt":
            self.skipTest("bash installer is covered on Unix")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / "target"
        self.target.mkdir()
        self.toolbin = self.root / "bin"
        self.toolbin.mkdir()
        for name in ("gh", "git", "yq"):
            stub = self.toolbin / name
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        (self.toolbin / "python3").symlink_to(sys.executable)
        self.env = {
            **os.environ,
            "HOME": str(self.root / "home"),
            "PATH": f"{self.toolbin}:/usr/bin:/bin:/usr/sbin:/sbin",
        }
        (self.root / "home").mkdir()

    def run_script(self, name, *, stdin="", env=None):
        return subprocess.run(
            [str(REPO / name), f"--target={self.target}"], input=stdin,
            text=True, capture_output=True, env=env or self.env,
        )

    def install(self, *, stdin=""):
        result = self.run_script("install.sh", stdin=stdin)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_fresh_install_marks_and_managed_reinstall_updates_launcher(self):
        self.install()
        launcher = self.target / "bin/work-plan"
        marker = self.target / "bin/work-plan.installed-from"
        self.assertTrue(launcher.is_file())
        self.assertRegex(marker.read_text(),
                         r"^stylusnexus/work-plan-toolkit launcher v1\nsha256=[0-9a-f]{64}\n$")

        result = self.install()
        self.assertNotIn("Overwrite?", result.stdout)

    def test_unmanaged_launcher_is_preserved_by_install_and_uninstall(self):
        launcher = self.target / "bin/work-plan"
        launcher.parent.mkdir()
        launcher.write_bytes(b"custom launcher\n")

        self.install(stdin="n\n")
        self.assertEqual(launcher.read_bytes(), b"custom launcher\n")
        self.assertFalse(Path(f"{launcher}.installed-from").exists())

        result = self.run_script("uninstall.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(launcher.read_bytes(), b"custom launcher\n")

    def test_unmanaged_launcher_can_be_accepted_and_becomes_managed(self):
        launcher = self.target / "bin/work-plan"
        launcher.parent.mkdir()
        launcher.write_bytes(b"custom launcher\n")

        self.install(stdin="y\n")

        self.assertEqual(launcher.read_bytes(), (REPO / "bin/work-plan").read_bytes())
        self.assertTrue(Path(f"{launcher}.installed-from").is_file())

    def test_modified_managed_launcher_is_preserved_by_default(self):
        self.install()
        launcher = self.target / "bin/work-plan"
        launcher.write_bytes(b"user modification\n")

        self.install(stdin="n\n")
        self.assertEqual(launcher.read_bytes(), b"user modification\n")
        result = self.run_script("uninstall.sh")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(launcher.read_bytes(), b"user modification\n")
        self.assertTrue(Path(f"{launcher}.installed-from").exists())

    def test_managed_launcher_is_removed_with_marker(self):
        self.install()
        launcher = self.target / "bin/work-plan"
        marker = Path(f"{launcher}.installed-from")

        result = self.run_script("uninstall.sh")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(launcher.exists())
        self.assertFalse(marker.exists())

    def test_declined_required_skill_is_unchanged_and_aborts_dependents(self):
        skill = self.target / "skills/work-plan"
        skill.mkdir(parents=True)
        user_file = skill / "user-file.md"
        user_file.write_bytes(b"mine\n")

        result = self.run_script("install.sh", stdin="n\n")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(skill.iterdir()), [user_file])
        self.assertEqual(user_file.read_bytes(), b"mine\n")
        self.assertFalse((self.target / "bin/work-plan").exists())
        self.assertFalse((self.target / "commands/work-plan.md").exists())
        self.assertNotIn("Done.", result.stdout)

    def test_failed_smoke_is_fatal_and_never_prints_done(self):
        real_python = sys.executable
        wrapper = self.toolbin / "python3"
        wrapper.unlink()
        wrapper.write_text(
            "#!/bin/sh\n"
            "if [ \"${2-}\" = \"--help\" ]; then exit 9; fi\n"
            f'exec "{real_python}" "$@"\n'
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)

        result = self.run_script("install.sh")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation is incomplete", result.stderr)
        self.assertNotIn("Done.", result.stdout)


if __name__ == "__main__":
    unittest.main()
