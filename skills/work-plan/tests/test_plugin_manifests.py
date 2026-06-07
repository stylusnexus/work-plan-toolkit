"""Plugin manifest(s) parse, carry required fields, and match VERSION (CalVer).

Offline. The Codex manifest (.codex-plugin/plugin.json) lands in Phase 2; this
test tolerates its absence and only asserts equality when it exists.
"""
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load(rel):
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


class ClaudeManifestTest(unittest.TestCase):
    def test_required_fields(self):
        m = _load(".claude-plugin/plugin.json")
        self.assertEqual(m["name"], "work-plan")
        self.assertTrue(m["description"])
        self.assertEqual(m["license"], "MIT")

    def test_version_matches_VERSION(self):
        m = _load(".claude-plugin/plugin.json")
        ver = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(m["version"], ver)   # CalVer string, not semver

    def test_codex_manifest_agrees_when_present(self):
        codex = REPO_ROOT / ".codex-plugin" / "plugin.json"
        if not codex.exists():
            self.skipTest("Codex manifest is Phase 2")
        self.assertEqual(_load(".codex-plugin/plugin.json")["version"],
                         _load(".claude-plugin/plugin.json")["version"])


if __name__ == "__main__":
    unittest.main()
