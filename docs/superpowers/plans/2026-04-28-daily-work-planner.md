# Daily Work Planner Implementation Plan

<!-- plan-status: BEGIN -->
> **Status:** 🟡 partial · 0/38 files · last touched 2026-04-28
<!-- plan-status: END -->

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a global Claude Code skill `/work-plan` that turns Eve's stale Project Notes/*.md files into a track-aware daily planning system. Bookended brief/handoff rituals, parallel-session re-orientation via where-was-i, GitHub-derived per-issue priority, 3-state closure, AND **the intelligence layer** that makes the system self-managing: in-progress auto-detection, drift detection, new-issue surfacing, archived-track re-open detection, closure-ready signals, and AI-assisted priority backfill.

**Architecture:** Skill markdown (`~/.claude/skills/work-plan/SKILL.md`) routes subcommands to a Python CLI helper (`work_plan.py`) that handles deterministic logic. Claude provides AI-assisted parts (handoff prompt drafting, suggest-priorities batch, slot suggestions). Configuration at `~/.claude/work-plan/config.yml` maps folder→{github_repo, local_path}. Tracks live in `<notes_root>/<repo-folder>/*.md` with YAML frontmatter referencing GitHub issues by ID; per-issue state is queried live, never duplicated. Local git state is queried per-track via the `local_path` mapping (this is what enables in-progress auto-detection).

**Tech Stack:** Python 3 stdlib (no pip), shelling out to `yq` for YAML, `gh` for GitHub queries, `git` for repo state. Tests use `unittest` (stdlib). All tools verified present at `/opt/homebrew/bin/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `~/.claude/skills/work-plan/SKILL.md` | Skill entry point. Documents subcommands. Instructs Claude how/when to invoke `work_plan.py` and how to handle interactive prompts. |
| `~/.claude/skills/work-plan/work_plan.py` | CLI entry point. Dispatches to subcommand modules. |
| `~/.claude/skills/work-plan/lib/frontmatter.py` | Parse + write YAML frontmatter on .md files. Body-preserving. |
| `~/.claude/skills/work-plan/lib/config.py` | Load + validate `~/.claude/work-plan/config.yml`. Resolve folder→{github, local}, notes_root. |
| `~/.claude/skills/work-plan/lib/tracks.py` | Discover tracks under notes_root. Includes archive scanning. |
| `~/.claude/skills/work-plan/lib/github_state.py` | Query GitHub via `gh` for issue state, labels, PRs. Cached per-run. |
| `~/.claude/skills/work-plan/lib/git_state.py` | Local git queries via `local_path`: branches, uncommitted, recent commits, branch_in_progress. |
| `~/.claude/skills/work-plan/lib/status_table.py` | Find, parse, and update the first markdown table with a Status column. |
| `~/.claude/skills/work-plan/lib/closure.py` | Detect closure-ready signals (5 signals from spec). |
| `~/.claude/skills/work-plan/lib/new_issues.py` | Query recently-created GitHub issues + match against active and archived tracks. |
| `~/.claude/skills/work-plan/lib/drift.py` | Diff body status table against current GitHub state. |
| `~/.claude/skills/work-plan/lib/render.py` | Compose terminal output strings. Time-aware framing. |
| `~/.claude/skills/work-plan/commands/brief.py` | `/work-plan brief` — multi-track status output. |
| `~/.claude/skills/work-plan/commands/handoff.py` | `/work-plan handoff [track]` — interactive prompts → write frontmatter + status table + session log. |
| `~/.claude/skills/work-plan/commands/where_was_i.py` | `/work-plan where-was-i [track]` — single-track re-orientation. |
| `~/.claude/skills/work-plan/commands/slot.py` | `/work-plan slot <issue-num>` — place a new issue in a track. |
| `~/.claude/skills/work-plan/commands/close.py` | `/work-plan close [track]` — closure ritual + archive move. |
| `~/.claude/skills/work-plan/commands/refresh_md.py` | `/work-plan refresh-md [track]` — reconcile body status table with GitHub. |
| `~/.claude/skills/work-plan/commands/list_cmd.py` | `/work-plan list [--all]` — list tracks. |
| `~/.claude/skills/work-plan/commands/init.py` | `/work-plan init <file>` — scaffold frontmatter on existing .md. |
| `~/.claude/skills/work-plan/commands/suggest_priorities.py` | `/work-plan suggest-priorities` — AI-assisted batch label backfill (one-time migration helper). |
| `~/.claude/skills/work-plan/tests/test_*.py` | Unit tests for each lib module. |
| `~/.claude/skills/work-plan/tests/fixtures/*` | Sample track files for tests. |
| `~/.claude/work-plan/config.yml` | User config. Created during one-time setup. |

**Phases:**

- **Phase 0** — Skeleton (2 tasks)
- **Phase 1** — Frontmatter + config libs (5 tasks)
- **Phase 2** — Track discovery + state primitives (4 tasks)
- **Phase 3** — Intelligence libs: closure, new_issues, drift (3 tasks)
- **Phase 4** — `brief` + `list` (5 tasks)
- **Phase 5** — `handoff` (3 tasks)
- **Phase 6** — `where-was-i` (1 task)
- **Phase 7** — `slot`, `refresh-md`, `close` (3 tasks)
- **Phase 8** — `init`, `suggest-priorities`, SKILL.md (3 tasks)
- **Phase 9** — Migration on Eve's actual notes (5 tasks)

**Total: 34 tasks.**

---

## Phase 0 — Skeleton

### Task 1: Create skill directory + stubs

**Files:**
- Create: `~/.claude/skills/work-plan/{lib,commands,tests/fixtures}/`
- Create: `~/.claude/skills/work-plan/SKILL.md` (placeholder)
- Create: `~/.claude/skills/work-plan/work_plan.py`

- [ ] **Step 1: Create directories and `__init__.py` files**

```bash
mkdir -p ~/.claude/skills/work-plan/{lib,commands,tests/fixtures}
touch ~/.claude/skills/work-plan/{lib,commands,tests}/__init__.py
```

- [ ] **Step 2: Create stub SKILL.md**

Write to `~/.claude/skills/work-plan/SKILL.md`:

```markdown
---
name: work-plan
description: Track-aware daily work planning. Subcommands: brief, handoff, where-was-i, slot, close, refresh-md, list, init, suggest-priorities. Reads YAML-frontmattered Project Notes; queries GitHub for live state.
---

# Work Plan

(Implementation in progress. Final SKILL.md written in Task 32.)
```

- [ ] **Step 3: Create work_plan.py with subcommand router**

Write to `~/.claude/skills/work-plan/work_plan.py`:

```python
#!/usr/bin/env python3
"""Daily work planner CLI."""
import sys

SUBCOMMANDS = {
    "brief": "commands.brief",
    "handoff": "commands.handoff",
    "where-was-i": "commands.where_was_i",
    "slot": "commands.slot",
    "close": "commands.close",
    "refresh-md": "commands.refresh_md",
    "list": "commands.list_cmd",
    "init": "commands.init",
    "suggest-priorities": "commands.suggest_priorities",
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: work_plan.py <subcommand> [args...]", file=sys.stderr)
        print(f"subcommands: {', '.join(SUBCOMMANDS)}", file=sys.stderr)
        return 2
    sub = argv[1]
    if sub not in SUBCOMMANDS:
        print(f"unknown subcommand '{sub}'", file=sys.stderr)
        return 2
    try:
        module = __import__(SUBCOMMANDS[sub], fromlist=["run"])
    except ImportError as e:
        print(f"subcommand '{sub}' not implemented yet ({e})", file=sys.stderr)
        return 1
    return module.run(argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

Then: `chmod +x ~/.claude/skills/work-plan/work_plan.py`.

- [ ] **Step 4: Verify skeleton runs**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py
python3 ~/.claude/skills/work-plan/work_plan.py brief
```

Expected first: `usage: work_plan.py <subcommand> ...` + exit 2.
Expected second: `subcommand 'brief' not implemented yet ...` + exit 1.

---

### Task 2: First test passes

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_smoke.py`

- [ ] **Step 1: Write smoke test**

Write to `~/.claude/skills/work-plan/tests/test_smoke.py`:

```python
"""Smoke test: importable + main() exists."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

import work_plan


class SmokeTest(unittest.TestCase):
    def test_main_exists(self):
        self.assertTrue(callable(work_plan.main))

    def test_main_no_args_returns_2(self):
        self.assertEqual(work_plan.main(["work_plan.py"]), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest discover tests -v
```

Expected: 2 tests PASS.

---

## Phase 1 — Frontmatter + Config

### Task 3: Frontmatter parser

**Files:**
- Create: `~/.claude/skills/work-plan/tests/fixtures/track_with_frontmatter.md`
- Create: `~/.claude/skills/work-plan/tests/fixtures/track_without_frontmatter.md`
- Create: `~/.claude/skills/work-plan/tests/test_frontmatter.py`
- Create: `~/.claude/skills/work-plan/lib/frontmatter.py`

- [ ] **Step 1: Create fixtures**

`~/.claude/skills/work-plan/tests/fixtures/track_with_frontmatter.md`:

```markdown
---
track: tabletop
status: active
launch_priority: P1
github:
  repo: stylusnexus/CritForge
  issues: [4254, 4127]
  branches: []
next_up: [4254]
---

# Tabletop

Body content.
```

`~/.claude/skills/work-plan/tests/fixtures/track_without_frontmatter.md`:

```markdown
# Some plan

Body only.
```

- [ ] **Step 2: Write failing test**

`~/.claude/skills/work-plan/tests/test_frontmatter.py`:

```python
"""Tests for frontmatter parser/writer."""
import unittest
import tempfile
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.frontmatter import parse_file, write_file

FIXTURES = Path(__file__).parent / "fixtures"


class FrontmatterTest(unittest.TestCase):
    def test_parse_file_with_frontmatter(self):
        meta, body = parse_file(FIXTURES / "track_with_frontmatter.md")
        self.assertEqual(meta["track"], "tabletop")
        self.assertEqual(meta["github"]["issues"], [4254, 4127])
        self.assertIn("Body content.", body)

    def test_parse_file_without_frontmatter_returns_empty_meta(self):
        meta, body = parse_file(FIXTURES / "track_without_frontmatter.md")
        self.assertEqual(meta, {})
        self.assertIn("# Some plan", body)

    def test_write_then_parse_roundtrip(self):
        meta = {
            "track": "test",
            "status": "active",
            "github": {"repo": "org/repo", "issues": [42]},
        }
        body = "\n# Body\n\nProse.\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.md"
            write_file(path, meta, body)
            m2, b2 = parse_file(path)
            self.assertEqual(m2, meta)
            self.assertEqual(b2, body)

    def test_write_with_empty_meta_writes_body_only(self):
        body = "# Title\n\nProse.\n"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.md"
            write_file(path, {}, body)
            m, b = parse_file(path)
            self.assertEqual(m, {})
            self.assertEqual(b, body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify FAIL**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_frontmatter -v
```

Expected: FAIL on `ImportError`.

- [ ] **Step 4: Implement frontmatter**

`~/.claude/skills/work-plan/lib/frontmatter.py`:

```python
"""Parse + write YAML frontmatter on markdown files. Body-preserving."""
import json
import re
import subprocess
from pathlib import Path
from typing import Tuple

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_file(path: Path) -> Tuple[dict, str]:
    """Parse markdown with optional YAML frontmatter. Returns (meta, body)."""
    text = Path(path).read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return ({}, text)
    meta = _yaml_to_dict(match.group(1))
    return (meta, match.group(2))


def write_file(path: Path, meta: dict, body: str) -> None:
    """Write markdown with frontmatter. Empty meta = body only."""
    if not meta:
        Path(path).write_text(body, encoding="utf-8")
        return
    yaml_text = _dict_to_yaml(meta)
    Path(path).write_text(f"---\n{yaml_text}---\n{body}", encoding="utf-8")


def _yaml_to_dict(yaml_text: str) -> dict:
    proc = subprocess.run(
        ["yq", "-o=json", "."], input=yaml_text,
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def _dict_to_yaml(d: dict) -> str:
    proc = subprocess.run(
        ["yq", "-P", "."], input=json.dumps(d),
        capture_output=True, text=True, check=True,
    )
    out = proc.stdout
    if not out.endswith("\n"):
        out += "\n"
    return out
```

- [ ] **Step 5: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_frontmatter -v
```

Expected: 4 tests PASS.

---

### Task 4: Config loader (with new dict-shape repo map)

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_config.py`
- Create: `~/.claude/skills/work-plan/lib/config.py`

The config schema MUST support the dict shape so that in-progress auto-detection has a `local_path` to query:

```yaml
notes_root: /Applications/Development/Projects/Project Notes/
repos:
  critforge:
    github: stylusnexus/CritForge
    local: /Applications/Development/Projects/CritForge
```

- [ ] **Step 1: Write failing test**

`~/.claude/skills/work-plan/tests/test_config.py`:

```python
"""Tests for config loader."""
import unittest
import tempfile
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.config import (
    load_config, ConfigError,
    resolve_github_for_folder, resolve_local_path_for_folder,
)


class LoadConfigTest(unittest.TestCase):
    def _write(self, d, content):
        path = Path(d) / "config.yml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_load_dict_shape(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, (
                "notes_root: /tmp/notes\n"
                "repos:\n"
                "  critforge:\n"
                "    github: stylusnexus/CritForge\n"
                "    local: /Applications/Development/Projects/CritForge\n"
            ))
            cfg = load_config(path)
            self.assertEqual(cfg["notes_root"], "/tmp/notes")
            self.assertEqual(cfg["repos"]["critforge"]["github"], "stylusnexus/CritForge")
            self.assertEqual(cfg["repos"]["critforge"]["local"],
                             "/Applications/Development/Projects/CritForge")

    def test_load_string_shape_normalizes_to_dict(self):
        # Backward-friendly: bare string is treated as github-only, no local
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, (
                "notes_root: /tmp/notes\n"
                "repos:\n"
                "  critforge: stylusnexus/CritForge\n"
            ))
            cfg = load_config(path)
            self.assertEqual(cfg["repos"]["critforge"]["github"], "stylusnexus/CritForge")
            self.assertIsNone(cfg["repos"]["critforge"]["local"])

    def test_missing_file_raises(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(Path("/nonexistent/config.yml"))
        self.assertIn("config.yml", str(ctx.exception))

    def test_missing_notes_root_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "repos:\n  foo: bar/baz\n")
            with self.assertRaises(ConfigError) as ctx:
                load_config(path)
            self.assertIn("notes_root", str(ctx.exception))


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "repos": {
                "critforge": {"github": "stylusnexus/CritForge", "local": "/path/to/critforge"},
            },
        }

    def test_resolve_github(self):
        self.assertEqual(resolve_github_for_folder("critforge", self.cfg), "stylusnexus/CritForge")
        self.assertIsNone(resolve_github_for_folder("unknown", self.cfg))

    def test_resolve_local_path(self):
        self.assertEqual(resolve_local_path_for_folder("critforge", self.cfg), Path("/path/to/critforge"))
        self.assertIsNone(resolve_local_path_for_folder("unknown", self.cfg))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify FAIL**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_config -v
```

Expected: ImportError.

- [ ] **Step 3: Implement config**

`~/.claude/skills/work-plan/lib/config.py`:

```python
"""Load + validate ~/.claude/work-plan/config.yml."""
import json
import subprocess
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "work-plan" / "config.yml"


class ConfigError(Exception):
    pass


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Load and validate. Normalizes string-shape repo entries to dicts."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"config.yml not found at {path}. Create it with:\n"
            "  notes_root: /Applications/Development/Projects/Project Notes/\n"
            "  repos:\n"
            "    <folder-name>:\n"
            "      github: <org>/<repo>\n"
            "      local: <absolute-path-to-clone>\n"
        )
    text = path.read_text(encoding="utf-8")
    proc = subprocess.run(
        ["yq", "-o=json", "."], input=text,
        capture_output=True, text=True, check=True,
    )
    cfg = json.loads(proc.stdout)
    if not isinstance(cfg, dict):
        raise ConfigError(f"config.yml must be a YAML mapping; got {type(cfg).__name__}")
    if "notes_root" not in cfg:
        raise ConfigError("config.yml missing required key 'notes_root'.")
    cfg.setdefault("repos", {})
    # Normalize string-shape entries to dict shape
    for folder, val in list(cfg["repos"].items()):
        if isinstance(val, str):
            cfg["repos"][folder] = {"github": val, "local": None}
        elif isinstance(val, dict):
            val.setdefault("local", None)
            if "github" not in val:
                raise ConfigError(f"repo '{folder}' missing 'github' key")
        else:
            raise ConfigError(f"repo '{folder}' must be string or dict, got {type(val).__name__}")
    return cfg


def resolve_github_for_folder(folder_name: str, cfg: dict) -> Optional[str]:
    entry = cfg.get("repos", {}).get(folder_name)
    return entry.get("github") if entry else None


def resolve_local_path_for_folder(folder_name: str, cfg: dict) -> Optional[Path]:
    entry = cfg.get("repos", {}).get(folder_name)
    if not entry or not entry.get("local"):
        return None
    return Path(entry["local"]).expanduser()
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_config -v
```

Expected: 7 tests PASS.

---

## Phase 2 — Track Discovery + State Primitives

### Task 5: Track discovery (with archive scanning)

**Files:**
- Create: fixture files in `~/.claude/skills/work-plan/tests/fixtures/notes_root/`
- Create: `~/.claude/skills/work-plan/tests/test_tracks.py`
- Create: `~/.claude/skills/work-plan/lib/tracks.py`

- [ ] **Step 1: Create fixtures**

```bash
mkdir -p ~/.claude/skills/work-plan/tests/fixtures/notes_root/critforge/archive/shipped
```

`~/.claude/skills/work-plan/tests/fixtures/notes_root/critforge/example.md`:

```markdown
---
track: example
status: active
launch_priority: P1
github:
  repo: stylusnexus/CritForge
  issues: [100, 200]
next_up: [100]
---

# Example
```

`~/.claude/skills/work-plan/tests/fixtures/notes_root/critforge/no_frontmatter.md`:

```markdown
# No frontmatter
```

`~/.claude/skills/work-plan/tests/fixtures/notes_root/loose_at_root.md`:

```markdown
# Loose
```

`~/.claude/skills/work-plan/tests/fixtures/notes_root/critforge/archive/shipped/old.md`:

```markdown
---
track: old
status: shipped
launch_priority: P2
github:
  repo: stylusnexus/CritForge
  issues: [50]
---

# Old shipped track
```

- [ ] **Step 2: Write failing test**

`~/.claude/skills/work-plan/tests/test_tracks.py`:

```python
"""Tests for track discovery."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.tracks import discover_tracks, discover_archived_tracks

FIXTURES = Path(__file__).parent / "fixtures" / "notes_root"


class DiscoverTracksTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "notes_root": str(FIXTURES),
            "repos": {"critforge": {"github": "stylusnexus/CritForge", "local": None}},
        }

    def test_active_track_discovered(self):
        names = [t.name for t in discover_tracks(self.cfg) if t.has_frontmatter]
        self.assertIn("example", names)

    def test_repo_inferred_from_folder(self):
        ex = next(t for t in discover_tracks(self.cfg) if t.name == "example")
        self.assertEqual(ex.repo, "stylusnexus/CritForge")

    def test_no_frontmatter_flagged_needs_init(self):
        nf = next(t for t in discover_tracks(self.cfg) if t.path.name == "no_frontmatter.md")
        self.assertTrue(nf.needs_init)

    def test_loose_file_flagged_needs_filing(self):
        loose = next(t for t in discover_tracks(self.cfg) if t.path.name == "loose_at_root.md")
        self.assertTrue(loose.needs_filing)

    def test_archived_excluded_from_discover_tracks(self):
        names = [t.name for t in discover_tracks(self.cfg)]
        self.assertNotIn("old", names)


class DiscoverArchivedTracksTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "notes_root": str(FIXTURES),
            "repos": {"critforge": {"github": "stylusnexus/CritForge", "local": None}},
        }

    def test_finds_shipped_track_in_archive(self):
        archived = discover_archived_tracks(self.cfg)
        slugs = [a.meta.get("track") for a in archived]
        self.assertIn("old", slugs)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Verify FAIL**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_tracks -v
```

Expected: ImportError.

- [ ] **Step 4: Implement tracks**

`~/.claude/skills/work-plan/lib/tracks.py`:

```python
"""Discover tracks under notes_root."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib.frontmatter import parse_file
from lib.config import resolve_github_for_folder, resolve_local_path_for_folder


@dataclass
class Track:
    path: Path
    name: str
    has_frontmatter: bool
    needs_init: bool
    needs_filing: bool
    repo: Optional[str] = None
    local_path: Optional[Path] = None
    meta: dict = field(default_factory=dict)
    body: str = ""


def discover_tracks(cfg: dict) -> list[Track]:
    """Walk notes_root for active (non-archived) .md files."""
    notes_root = Path(cfg["notes_root"])
    if not notes_root.exists():
        return []
    return _walk(notes_root, cfg, include_archive=False)


def discover_archived_tracks(cfg: dict) -> list[Track]:
    """Walk notes_root for archived .md files only."""
    notes_root = Path(cfg["notes_root"])
    if not notes_root.exists():
        return []
    out = []
    for md_path in sorted(notes_root.rglob("*.md")):
        if "archive" not in md_path.parts:
            continue
        if md_path.name.startswith((".", "_")):
            continue
        out.append(_build_track(md_path, notes_root, cfg))
    return out


def _walk(notes_root: Path, cfg: dict, include_archive: bool) -> list[Track]:
    out = []
    for md_path in sorted(notes_root.rglob("*.md")):
        if not include_archive and "archive" in md_path.parts:
            continue
        if md_path.name.startswith((".", "_")):
            continue
        out.append(_build_track(md_path, notes_root, cfg))
    return out


def _build_track(md_path: Path, notes_root: Path, cfg: dict) -> Track:
    meta, body = parse_file(md_path)
    has_fm = bool(meta)
    rel = md_path.relative_to(notes_root)
    in_subfolder = len(rel.parts) > 1
    folder_name = rel.parts[0] if in_subfolder else None

    # Resolve repo: frontmatter takes precedence, else folder map
    repo = None
    if has_fm and meta.get("github", {}).get("repo"):
        repo = meta["github"]["repo"]
    elif folder_name:
        repo = resolve_github_for_folder(folder_name, cfg)

    local = resolve_local_path_for_folder(folder_name, cfg) if folder_name else None

    return Track(
        path=md_path,
        name=md_path.stem,
        has_frontmatter=has_fm,
        needs_init=in_subfolder and not has_fm,
        needs_filing=not in_subfolder,
        repo=repo,
        local_path=local,
        meta=meta,
        body=body,
    )
```

- [ ] **Step 5: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_tracks -v
```

Expected: 6 tests PASS.

---

### Task 6: GitHub state fetcher

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_github_state.py`
- Create: `~/.claude/skills/work-plan/lib/github_state.py`

- [ ] **Step 1: Write test (mocked)**

`~/.claude/skills/work-plan/tests/test_github_state.py`:

```python
"""Tests for GitHub state — uses mocks (gh requires auth)."""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.github_state import fetch_issues, extract_priority, fetch_recent_issues


class ExtractPriorityTest(unittest.TestCase):
    def test_p0_label(self):
        labels = [{"name": "priority/P0"}, {"name": "bug"}]
        self.assertEqual(extract_priority(labels), "P0")

    def test_no_priority_label_returns_p3(self):
        self.assertEqual(extract_priority([{"name": "bug"}]), "P3")

    def test_p2_label(self):
        self.assertEqual(extract_priority([{"name": "priority/P2"}]), "P2")


class FetchIssuesTest(unittest.TestCase):
    @patch("lib.github_state.subprocess.run")
    def test_returns_list(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"number": 4254, "state": "OPEN", "labels": [{"name": "priority/P0"}], "title": "polls"}',
            returncode=0,
        )
        result = fetch_issues("stylusnexus/CritForge", [4254])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["number"], 4254)

    def test_empty_returns_empty(self):
        self.assertEqual(fetch_issues("stylusnexus/CritForge", []), [])


class FetchRecentIssuesTest(unittest.TestCase):
    @patch("lib.github_state.subprocess.run")
    def test_calls_gh_with_search(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='[{"number": 9999, "title": "new", "labels": [], "createdAt": "2026-04-28T10:00:00Z"}]',
            returncode=0,
        )
        result = fetch_recent_issues("stylusnexus/CritForge", since_iso="2026-04-27")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["number"], 9999)
        # Verify the search query includes the date filter
        called_args = mock_run.call_args[0][0]
        self.assertIn("created:>=2026-04-27", " ".join(called_args))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify FAIL**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_github_state -v
```

- [ ] **Step 3: Implement github_state**

`~/.claude/skills/work-plan/lib/github_state.py`:

```python
"""Query GitHub via `gh`."""
import json
import subprocess
from typing import Iterable

PRIORITY_LABELS = ("priority/P0", "priority/P1", "priority/P2", "priority/P3")
DEFAULT_PRIORITY = "P3"


def fetch_issues(repo: str, issue_numbers: Iterable[int]) -> list[dict]:
    """Fetch state of multiple issues via gh."""
    nums = list(issue_numbers)
    if not nums:
        return []
    results = []
    for num in nums:
        proc = subprocess.run(
            ["gh", "issue", "view", str(num),
             "--repo", repo,
             "--json", "number,state,labels,title,milestone,url"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            continue
        results.append(json.loads(proc.stdout))
    return results


def fetch_recent_issues(repo: str, since_iso: str, extra_labels: list[str] = None) -> list[dict]:
    """Fetch issues created since `since_iso` (date YYYY-MM-DD).

    Optional extra_labels: filter to issues with any of these labels.
    """
    search = f"created:>={since_iso}"
    cmd = ["gh", "issue", "list", "--repo", repo,
           "--state", "all",
           "--search", search,
           "--limit", "50",
           "--json", "number,title,labels,createdAt,milestone,url"]
    if extra_labels:
        for lab in extra_labels:
            cmd.extend(["--label", lab])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout) if proc.stdout.strip() else []


def extract_priority(labels: list[dict]) -> str:
    label_names = {l["name"] for l in labels}
    for p in PRIORITY_LABELS:
        if p in label_names:
            return p.split("/")[1]
    return DEFAULT_PRIORITY
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_github_state -v
```

Expected: 6 tests PASS.

---

### Task 7: Local git state (extended for in-progress detection)

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_git_state.py`
- Create: `~/.claude/skills/work-plan/lib/git_state.py`

- [ ] **Step 1: Write tests**

`~/.claude/skills/work-plan/tests/test_git_state.py`:

```python
"""Tests for git_state pure functions."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.git_state import (
    gap_seconds_to_label, parse_iso_timestamp,
    branch_in_progress, _has_recent_commits,
)


class GapLabelTest(unittest.TestCase):
    def test_minutes(self):
        self.assertEqual(gap_seconds_to_label(30 * 60), "30m ago")

    def test_one_hour(self):
        self.assertEqual(gap_seconds_to_label(3600), "1h ago")

    def test_six_hours(self):
        self.assertEqual(gap_seconds_to_label(6 * 3600), "6h ago")

    def test_one_day(self):
        self.assertEqual(gap_seconds_to_label(86400), "1d ago")

    def test_multi_days(self):
        self.assertEqual(gap_seconds_to_label(5 * 86400 + 3600), "5d ago")


class ParseTimestampTest(unittest.TestCase):
    def test_iso_with_hour(self):
        dt = parse_iso_timestamp("2026-04-23T22:14")
        self.assertEqual(dt.hour, 22)

    def test_iso_date_only(self):
        dt = parse_iso_timestamp("2026-04-23")
        self.assertEqual(dt.year, 2026)


class BranchInProgressTest(unittest.TestCase):
    def test_returns_false_when_repo_path_missing(self):
        self.assertFalse(branch_in_progress("any-branch", None))

    def test_returns_false_when_path_doesnt_exist(self):
        self.assertFalse(branch_in_progress("any-branch", Path("/nonexistent")))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify FAIL**

- [ ] **Step 3: Implement git_state**

`~/.claude/skills/work-plan/lib/git_state.py`:

```python
"""Local git queries + time helpers."""
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


def gap_seconds_to_label(seconds: int) -> str:
    """'Nm ago' / 'Nh ago' / 'Nd ago'."""
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def parse_iso_timestamp(s: str) -> datetime:
    if "T" in s:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M")
    return datetime.strptime(s, "%Y-%m-%d")


def current_branch(repo_path: Path) -> Optional[str]:
    if not repo_path or not Path(repo_path).exists():
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "branch", "--show-current"],
        capture_output=True, text=True,
    )
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def has_uncommitted(repo_path: Path) -> bool:
    """True if working tree has uncommitted changes."""
    if not repo_path or not Path(repo_path).exists():
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def uncommitted_file_count(repo_path: Path) -> int:
    if not repo_path or not Path(repo_path).exists():
        return 0
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return 0
    return len([l for l in proc.stdout.splitlines() if l.strip()])


def commits_ahead(branch_name: str, base: str, repo_path: Path) -> int:
    """How many commits is branch_name ahead of base?"""
    if not repo_path or not Path(repo_path).exists():
        return 0
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-list", "--count", f"{base}..{branch_name}"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return 0
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return 0


def branch_exists(branch_name: str, repo_path: Path) -> bool:
    if not repo_path or not Path(repo_path).exists():
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", branch_name],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


def _has_recent_commits(branch_name: str, repo_path: Path, hours: int = 24) -> bool:
    """True if branch has commits in the last N hours."""
    if not repo_path or not Path(repo_path).exists():
        return False
    if not branch_exists(branch_name, repo_path):
        return False
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "log", branch_name,
         f"--since={since}", "--pretty=format:%H"],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def branch_in_progress(branch_name: str, repo_path: Path) -> bool:
    """Detect if a branch is 'in-progress':
    - It's the current branch AND has uncommitted changes, OR
    - It has commits in the last 24 hours.
    """
    if not repo_path or not Path(repo_path).exists():
        return False
    if not branch_exists(branch_name, repo_path):
        return False
    cur = current_branch(repo_path)
    if cur == branch_name and has_uncommitted(repo_path):
        return True
    return _has_recent_commits(branch_name, repo_path, hours=24)


def last_commit_date(branch_name: str, repo_path: Path) -> Optional[datetime]:
    """Most recent commit timestamp on branch."""
    if not repo_path or not Path(repo_path).exists():
        return None
    if not branch_exists(branch_name, repo_path):
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "log", "-1", branch_name, "--pretty=format:%cI"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        # Trim timezone for naive comparison
        s = proc.stdout.strip().split("+")[0].split("Z")[0]
        return datetime.fromisoformat(s)
    except (ValueError, IndexError):
        return None
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_git_state -v
```

Expected: 10 tests PASS.

---

### Task 8: Status table parser/updater

**Files:**
- Create: `~/.claude/skills/work-plan/tests/fixtures/with_status_table.md`
- Create: `~/.claude/skills/work-plan/tests/test_status_table.py`
- Create: `~/.claude/skills/work-plan/lib/status_table.py`

- [ ] **Step 1: Create fixture**

`~/.claude/skills/work-plan/tests/fixtures/with_status_table.md`:

```markdown
# Track

## Issues

| # | Title | Status |
|---|---|---|
| #4254 | admin polls | 🔲 Open |
| #4127 | dice roller | ✅ Shipped |
| #925 | wild magic | 🟡 In PR (#4137) |
```

- [ ] **Step 2: Write failing test**

`~/.claude/skills/work-plan/tests/test_status_table.py`:

```python
"""Tests for status_table parser/updater."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.status_table import find_status_table, update_row_status, ISSUE_NUM_RE

FIXTURES = Path(__file__).parent / "fixtures"


class FindStatusTableTest(unittest.TestCase):
    def test_finds_table_with_status_col(self):
        body = (FIXTURES / "with_status_table.md").read_text()
        table = find_status_table(body)
        self.assertIsNotNone(table)
        self.assertEqual(table["status_col_index"], 2)
        self.assertEqual(len(table["rows"]), 3)

    def test_returns_none_when_no_status_table(self):
        self.assertIsNone(find_status_table("# Just text"))


class UpdateRowStatusTest(unittest.TestCase):
    def test_updates_one_row(self):
        body = (FIXTURES / "with_status_table.md").read_text()
        new = update_row_status(body, 4254, "✅ Shipped (PR #9999)")
        self.assertIn("✅ Shipped (PR #9999)", new)
        # Other rows preserved
        self.assertIn("✅ Shipped ", new)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Implement status_table**

`~/.claude/skills/work-plan/lib/status_table.py`:

```python
"""Find + update first markdown table with a Status column."""
import re
from typing import Optional

ISSUE_NUM_RE = re.compile(r"#(\d+)")


def find_status_table(body: str) -> Optional[dict]:
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = _parse_row(line)
        if not cells:
            continue
        status_idx = next((idx for idx, c in enumerate(cells) if c.strip().lower() == "status"), None)
        if status_idx is None:
            continue
        if i + 1 >= len(lines) or not _is_separator(lines[i + 1]):
            continue
        rows = []
        j = i + 2
        while j < len(lines):
            if "|" not in lines[j]:
                break
            row_cells = _parse_row(lines[j])
            if not row_cells:
                break
            rows.append({"raw": lines[j], "cells": row_cells, "line_idx": j})
            j += 1
        return {"header_line_idx": i, "rows": rows, "status_col_index": status_idx}
    return None


def update_row_status(body: str, issue_num: int, new_status: str) -> str:
    table = find_status_table(body)
    if not table:
        return body
    lines = body.split("\n")
    sidx = table["status_col_index"]
    for row in table["rows"]:
        nums = []
        for cell in row["cells"]:
            nums.extend(int(m) for m in ISSUE_NUM_RE.findall(cell))
        if issue_num not in nums:
            continue
        new_cells = list(row["cells"])
        new_cells[sidx] = " " + new_status + " "
        lines[row["line_idx"]] = "|" + "|".join(new_cells) + "|"
        break
    return "\n".join(lines)


def _parse_row(line: str) -> list[str]:
    s = line.strip()
    if "|" not in s:
        return []
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return s.split("|")


def _is_separator(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return all(c in "|-: " for c in s)
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_status_table -v
```

Expected: 3 tests PASS.

---

## Phase 3 — Intelligence Libs

### Task 9: Closure detection

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_closure.py`
- Create: `~/.claude/skills/work-plan/lib/closure.py`

Closure-ready signals from spec:
1. All `github.issues` are closed
2. All `github.branches` merged or deleted
3. `next_up` is empty
4. No commits to listed branches in 14d
5. No new related issues filed in 30d (deferred to combine with new_issues lib)

- [ ] **Step 1: Write test**

`~/.claude/skills/work-plan/tests/test_closure.py`:

```python
"""Tests for closure detection."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.closure import is_closure_ready, ClosureSignals


class ClosureReadyTest(unittest.TestCase):
    def test_all_signals_green(self):
        meta = {"github": {"issues": [1, 2], "branches": []}, "next_up": []}
        # All issues closed, branches empty/merged, no recent commits, etc.
        issues = [{"number": 1, "state": "CLOSED"}, {"number": 2, "state": "CLOSED"}]
        signals = ClosureSignals(
            all_issues_closed=True,
            all_branches_done=True,
            next_up_empty=True,
            cold_14d=True,
            no_recent_related_issues=True,
        )
        ready, reasons = is_closure_ready(signals)
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

    def test_open_issue_blocks_closure(self):
        signals = ClosureSignals(
            all_issues_closed=False,
            all_branches_done=True,
            next_up_empty=True,
            cold_14d=True,
            no_recent_related_issues=True,
        )
        ready, reasons = is_closure_ready(signals)
        self.assertFalse(ready)
        self.assertIn("open issues remain", " ".join(reasons))

    def test_partial_signals_returns_count(self):
        signals = ClosureSignals(
            all_issues_closed=True,
            all_branches_done=True,
            next_up_empty=False,  # blocker
            cold_14d=False,  # blocker
            no_recent_related_issues=True,
        )
        ready, reasons = is_closure_ready(signals)
        self.assertFalse(ready)
        self.assertEqual(len(reasons), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement closure**

`~/.claude/skills/work-plan/lib/closure.py`:

```python
"""Closure-ready signal detection."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from lib.git_state import last_commit_date, branch_exists


@dataclass
class ClosureSignals:
    """The 5 closure signals from the spec."""
    all_issues_closed: bool
    all_branches_done: bool  # merged or deleted
    next_up_empty: bool
    cold_14d: bool  # no commits in 14d
    no_recent_related_issues: bool  # no new related issues in 30d


def is_closure_ready(signals: ClosureSignals) -> tuple[bool, list[str]]:
    """All signals must be true. Returns (ready, list-of-blocking-reasons)."""
    reasons = []
    if not signals.all_issues_closed:
        reasons.append("open issues remain")
    if not signals.all_branches_done:
        reasons.append("branches still active")
    if not signals.next_up_empty:
        reasons.append("next_up is not empty")
    if not signals.cold_14d:
        reasons.append("recent commits within 14 days")
    if not signals.no_recent_related_issues:
        reasons.append("new related issues in last 30 days")
    return (not reasons, reasons)


def compute_signals(track_meta: dict, github_issues: list[dict],
                    repo_path: Optional[Path],
                    recent_related_count: int) -> ClosureSignals:
    """Build ClosureSignals from observed state."""
    listed_issue_nums = track_meta.get("github", {}).get("issues") or []
    state_by_num = {i["number"]: i.get("state", "OPEN") for i in github_issues}

    all_closed = all(state_by_num.get(n, "OPEN") == "CLOSED" for n in listed_issue_nums)

    branches = track_meta.get("github", {}).get("branches") or []
    if repo_path:
        all_branches_done = all(not branch_exists(b, repo_path) for b in branches)
    else:
        all_branches_done = len(branches) == 0

    next_up_empty = not (track_meta.get("next_up") or [])

    # Cold 14d: latest commit on any listed branch is more than 14d old (or no branches)
    cutoff = datetime.now() - timedelta(days=14)
    cold = True
    if repo_path:
        for b in branches:
            last = last_commit_date(b, repo_path)
            if last and last > cutoff:
                cold = False
                break

    no_recent = recent_related_count == 0

    return ClosureSignals(
        all_issues_closed=all_closed,
        all_branches_done=all_branches_done,
        next_up_empty=next_up_empty,
        cold_14d=cold,
        no_recent_related_issues=no_recent,
    )
```

- [ ] **Step 3: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_closure -v
```

Expected: 3 tests PASS.

---

### Task 10: New-issue detection (matches active AND archived tracks)

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_new_issues.py`
- Create: `~/.claude/skills/work-plan/lib/new_issues.py`

Match logic:
1. Issue has `track/<slug>` label → exact match
2. Issue title contains slug words → fuzzy match (rough but useful)

- [ ] **Step 1: Write test**

`~/.claude/skills/work-plan/tests/test_new_issues.py`:

```python
"""Tests for new-issue matching."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.new_issues import match_issue_to_tracks


class MatchIssueTest(unittest.TestCase):
    def test_label_match_wins(self):
        issue = {"number": 9, "title": "unrelated", "labels": [{"name": "track/tabletop"}]}
        track_slugs = ["tabletop", "ux-redesign"]
        matches = match_issue_to_tracks(issue, track_slugs)
        self.assertEqual(matches, ["tabletop"])

    def test_keyword_in_title(self):
        issue = {"number": 10, "title": "fix tabletop initiative tracker", "labels": []}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(matches, ["tabletop"])

    def test_no_match_returns_empty(self):
        issue = {"number": 11, "title": "boring thing", "labels": []}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(matches, [])

    def test_multiple_matches(self):
        issue = {"number": 12, "title": "tabletop ux redesign for combat", "labels": []}
        matches = match_issue_to_tracks(issue, ["tabletop", "ux-redesign"])
        self.assertEqual(set(matches), {"tabletop", "ux-redesign"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement new_issues**

`~/.claude/skills/work-plan/lib/new_issues.py`:

```python
"""Detect new GitHub issues that should slot into existing tracks (active or archived)."""
import re
from datetime import datetime, timedelta

from lib.github_state import fetch_recent_issues


def match_issue_to_tracks(issue: dict, track_slugs: list[str]) -> list[str]:
    """Return slugs of tracks this issue might belong to.

    Match strategy:
    1. `track/<slug>` label → exact match (highest confidence)
    2. Slug words appear in title → fuzzy match
    """
    label_names = {l["name"] for l in issue.get("labels", [])}
    title_lower = issue.get("title", "").lower()

    matches = set()

    # Exact label match
    for slug in track_slugs:
        if f"track/{slug}" in label_names:
            matches.add(slug)

    # Fuzzy title match (slug words must all appear)
    for slug in track_slugs:
        if slug in matches:
            continue
        words = [w for w in re.split(r"[-_]", slug) if len(w) >= 3]
        if not words:
            continue
        if all(w.lower() in title_lower for w in words):
            matches.add(slug)

    return sorted(matches)


def find_new_issues_for_tracks(repo: str, track_slugs: list[str],
                               since_days: int = 7) -> dict[str, list[dict]]:
    """For each track slug, return list of recent issues that match.

    since_days: how many days back to look. Default 7 (a week).
    """
    if not track_slugs:
        return {}
    since_date = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    recent = fetch_recent_issues(repo, since_iso=since_date)
    out: dict[str, list[dict]] = {s: [] for s in track_slugs}
    for issue in recent:
        for slug in match_issue_to_tracks(issue, track_slugs):
            out[slug].append(issue)
    return out
```

- [ ] **Step 3: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_new_issues -v
```

Expected: 4 tests PASS.

---

### Task 11: Drift detection

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_drift.py`
- Create: `~/.claude/skills/work-plan/lib/drift.py`

- [ ] **Step 1: Write test**

`~/.claude/skills/work-plan/tests/test_drift.py`:

```python
"""Tests for drift detection."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.drift import detect_drift


class DetectDriftTest(unittest.TestCase):
    def test_no_drift_when_table_matches(self):
        body = (
            "| # | Title | Status |\n"
            "|---|---|---|\n"
            "| #1 | foo | ✅ Shipped |\n"
        )
        github_issues = [{"number": 1, "state": "CLOSED"}]
        drift = detect_drift(body, github_issues)
        self.assertEqual(drift, [])

    def test_drift_when_open_in_md_closed_in_github(self):
        body = (
            "| # | Title | Status |\n"
            "|---|---|---|\n"
            "| #1 | foo | 🔲 Open |\n"
        )
        github_issues = [{"number": 1, "state": "CLOSED"}]
        drift = detect_drift(body, github_issues)
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["issue"], 1)

    def test_no_table_returns_empty(self):
        drift = detect_drift("# No table\n", [{"number": 1, "state": "CLOSED"}])
        self.assertEqual(drift, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement drift**

`~/.claude/skills/work-plan/lib/drift.py`:

```python
"""Detect drift between body status table and GitHub state."""
from lib.status_table import find_status_table, ISSUE_NUM_RE


def detect_drift(body: str, github_issues: list[dict]) -> list[dict]:
    """Return list of {issue, body_status, github_state} for drifted rows."""
    table = find_status_table(body)
    if not table:
        return []

    state_by_num = {i["number"]: i.get("state", "OPEN") for i in github_issues}
    drift = []
    sidx = table["status_col_index"]
    for row in table["rows"]:
        nums = []
        for cell in row["cells"]:
            nums.extend(int(m) for m in ISSUE_NUM_RE.findall(cell))
        if not nums:
            continue
        body_status = row["cells"][sidx].strip().lower() if sidx < len(row["cells"]) else ""
        for num in nums:
            if num not in state_by_num:
                continue
            gh_state = state_by_num[num]
            # Heuristic: 'closed' or 'shipped' in body should match CLOSED on GitHub
            looks_closed_in_body = any(k in body_status for k in ("✅", "shipped", "merged", "closed"))
            looks_open_in_body = "🔲" in body_status or "open" in body_status

            if gh_state == "CLOSED" and not looks_closed_in_body:
                drift.append({"issue": num, "body_status": body_status, "github_state": "CLOSED"})
            elif gh_state == "OPEN" and looks_closed_in_body:
                drift.append({"issue": num, "body_status": body_status, "github_state": "OPEN"})
    return drift
```

- [ ] **Step 3: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_drift -v
```

Expected: 3 tests PASS.

---

## Phase 4 — `brief` + `list`

### Task 12: Render module — time-aware framing + track row

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_render.py`
- Create: `~/.claude/skills/work-plan/lib/render.py`

- [ ] **Step 1: Write tests**

`~/.claude/skills/work-plan/tests/test_render.py`:

```python
"""Tests for render module."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.render import time_aware_framing, render_track_row


class TimeAwareFramingTest(unittest.TestCase):
    def test_long_gap(self):
        f = time_aware_framing(7 * 3600, 14)
        self.assertIn("Fresh start", f)

    def test_morning_says_fresh_start(self):
        f = time_aware_framing(1800, 9)
        self.assertIn("Fresh start", f)

    def test_medium_gap(self):
        self.assertIn("Picking back up", time_aware_framing(2 * 3600, 14))

    def test_short_gap(self):
        self.assertIn("Continuing", time_aware_framing(30 * 60, 14))

    def test_late_night_handoff_nudge(self):
        f = time_aware_framing(1800, 23, handoff_today=False)
        self.assertIn("handoff", f.lower())


class RenderTrackRowTest(unittest.TestCase):
    def _data(self, **overrides):
        d = {
            "name": "tabletop",
            "operational_status": "active",
            "launch_priority": "P1",
            "milestone_alignment": "v1.0.0",
            "last_touched_label": "5d ago",
            "last_handoff_label": "5d ago",
            "next_up": [],
            "active_branches": [],
            "new_issues": [],
            "blockers": [],
            "drift_items": [],
            "closure_ready": False,
            "closure_signals_summary": None,
            "archived_reopen": [],
        }
        d.update(overrides)
        return d

    def test_basic_row(self):
        row = render_track_row(self._data())
        for s in ["tabletop", "P1", "v1.0.0", "5d ago"]:
            self.assertIn(s, row)

    def test_in_progress_badge(self):
        row = render_track_row(self._data(operational_status="in-progress"))
        self.assertIn("in-progress", row)

    def test_active_branch_shown(self):
        row = render_track_row(self._data(
            active_branches=[{"name": "feat/4254", "ahead": 1, "uncommitted_files": 2}]
        ))
        self.assertIn("feat/4254", row)
        self.assertIn("ahead 1", row)
        self.assertIn("2", row)

    def test_new_issues_shown(self):
        row = render_track_row(self._data(
            new_issues=[{"number": 9, "title": "new"}]
        ))
        self.assertIn("#9", row)
        self.assertIn("slot? [run: /work-plan slot 9", row)

    def test_drift_shown(self):
        row = render_track_row(self._data(
            drift_items=[{"issue": 1, "body_status": "open", "github_state": "CLOSED"}]
        ))
        self.assertIn("Drift:", row)
        self.assertIn("#1", row)

    def test_closure_ready_shown(self):
        row = render_track_row(self._data(closure_ready=True))
        self.assertIn("Closure?:   YES", row)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement render**

`~/.claude/skills/work-plan/lib/render.py`:

```python
"""Compose terminal output strings."""


def time_aware_framing(gap_seconds: int, current_hour: int, handoff_today: bool = True) -> str:
    """Adapt framing to gap-since-last-activity + hour."""
    six_hours = 6 * 3600
    one_hour = 3600

    if gap_seconds > six_hours or current_hour < 11:
        line = "Fresh start. Here's what changed since you stepped away."
    elif gap_seconds >= one_hour:
        line = "Picking back up. Here's what was active when you stepped away."
    else:
        line = "Continuing. Drift since last brief:"

    if current_hour >= 23 and not handoff_today:
        line += "\n  Want a handoff before bed? Run /work-plan handoff [track]."

    return line


def render_track_row(t: dict) -> str:
    """Render one track block in the brief output."""
    lines = []

    badge_parts = []
    if t["operational_status"] == "in-progress":
        badge_parts.append("in-progress")
    elif t["operational_status"] == "blocked":
        badge_parts.append("blocked")
    badge_parts.append(t["launch_priority"])
    badge_parts.append(t["milestone_alignment"])
    badge_parts.append(f"last touched {t['last_touched_label']}, last handoff {t['last_handoff_label']}")
    lines.append(f"▸ {t['name']} ({' · '.join(badge_parts)})")

    # Up next
    if t["next_up"]:
        for idx, item in enumerate(t["next_up"]):
            label = f"#{item['number']} {item['title']} ({item['priority']}, {item['state']})"
            prefix = "    Up next:    " if idx == 0 else "                "
            lines.append(prefix + label)
    else:
        lines.append("    Up next:    <empty — set 'next_up:' or all items show backlog>")

    # Active branches
    for b in t["active_branches"]:
        ahead = f"ahead {b['ahead']}" if b["ahead"] else "no commits ahead"
        uc = f", uncommitted: {b['uncommitted_files']} file(s)" if b["uncommitted_files"] else ""
        lines.append(f"    Active:     {b['name']} ({ahead}{uc})")

    # New issues
    for n in t["new_issues"]:
        lines.append(f"    New:        #{n['number']} {n['title']} — slot? [run: /work-plan slot {n['number']}]")

    # Blockers
    if t["blockers"]:
        for b in t["blockers"]:
            reason = b.get("reason", "manually flagged")
            lines.append(f"    Blocker:    #{b['number']} — {reason}")
    else:
        lines.append("    Blockers:   none")

    # Drift
    if t["drift_items"]:
        items = ", ".join(f"#{d['issue']}" for d in t["drift_items"])
        lines.append(f"    Drift:      {items} — body says open but GitHub says closed (or vice versa). "
                     f"Run /work-plan refresh-md {t['name']}")

    # Closure
    if t["closure_ready"]:
        lines.append(f"    Closure?:   YES — run /work-plan close {t['name']}")
    elif t.get("closure_signals_summary"):
        lines.append(f"    Closure?:   {t['closure_signals_summary']}")

    return "\n".join(lines)


def render_archived_reopen(repo: str, slug: str, issue: dict) -> str:
    """Render a 'an archived track has new related activity' callout."""
    return (f"⚠  archive/{slug}.md (shipped) — new issue #{issue['number']} "
            f"matches this slug. Re-open or slot into a different track?")
```

- [ ] **Step 3: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_render -v
```

Expected: 11 tests PASS.

---

### Task 13: Brief command — full implementation (no deferrals)

**Files:**
- Create: `~/.claude/skills/work-plan/commands/brief.py`

- [ ] **Step 1: Implement brief**

`~/.claude/skills/work-plan/commands/brief.py`:

```python
"""brief subcommand — fully featured (in-progress detection, drift, new issues, closure)."""
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, discover_archived_tracks
from lib.github_state import fetch_issues, extract_priority
from lib.git_state import (
    parse_iso_timestamp, gap_seconds_to_label,
    branch_in_progress, commits_ahead, uncommitted_file_count, current_branch,
)
from lib.closure import compute_signals, is_closure_ready
from lib.new_issues import find_new_issues_for_tracks
from lib.drift import detect_drift
from lib.render import time_aware_framing, render_track_row, render_archived_reopen


def run(args: list[str]) -> int:
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}", flush=True)
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if not active and not tracks:
        print("No tracks found.")
        return 0

    now = datetime.now()

    # Time-aware framing inputs
    most_recent = max(
        (parse_iso_timestamp(t.meta["last_touched"]) for t in active if t.meta.get("last_touched")),
        default=None,
    )
    gap = int((now - most_recent).total_seconds()) if most_recent else 999999
    handoff_today = any(
        t.meta.get("last_handoff", "").startswith(now.strftime("%Y-%m-%d")) for t in active
    )
    framing = time_aware_framing(gap, now.hour, handoff_today)

    print(f"DAILY BRIEF — {now.strftime('%Y-%m-%d %H:%M')} (gap: {gap_seconds_to_label(gap)})")
    print()
    print(framing)
    print()

    # Build per-track data
    blocks = []
    for t in active:
        b = _build_track_block(t, cfg, now)
        blocks.append((b["sort_key"], b))

    # Sort: in-progress first, then P0..P3, then -recency
    blocks.sort(key=lambda x: x[0])
    for _, block in blocks:
        print(render_track_row(block))
        print()

    # Surface stale tracks needing init
    needs_init = [t for t in tracks if t.needs_init]
    needs_filing = [t for t in tracks if t.needs_filing]
    if needs_init or needs_filing:
        print("--- Setup needed ---")
        for t in needs_init:
            print(f"  needs init:   {t.path}  → /work-plan init '{t.path}'")
        for t in needs_filing:
            print(f"  needs filing: {t.path}  → move into a repo subfolder")
        print()

    # Archived re-open detection
    _surface_archived_reopens(cfg)

    # Summary line
    n_active = len(active)
    n_in_progress = sum(1 for _, b in blocks if b["operational_status"] == "in-progress")
    n_closure = sum(1 for _, b in blocks if b["closure_ready"])
    n_drift = sum(1 for _, b in blocks if b["drift_items"])
    n_new = sum(len(b["new_issues"]) for _, b in blocks)
    print(f"{n_active} active tracks. "
          f"{n_in_progress} in-progress. {n_closure} closure-ready. "
          f"{n_drift} with drift. {n_new} new issues to slot.")

    return 0


def _build_track_block(track, cfg, now: datetime) -> dict:
    meta = track.meta
    repo = track.repo
    local = track.local_path

    issue_nums = meta.get("github", {}).get("issues") or []
    issues = fetch_issues(repo, issue_nums) if (repo and issue_nums) else []
    issues_by_num = {i["number"]: i for i in issues}

    # next_up rendering
    next_up_items = []
    for num in (meta.get("next_up") or []):
        i = issues_by_num.get(num)
        if i:
            next_up_items.append({
                "number": num, "title": i.get("title", ""),
                "priority": extract_priority(i.get("labels", [])),
                "state": i.get("state", "?").lower(),
            })

    # Active branches with in-progress detection from git
    branch_names = meta.get("github", {}).get("branches") or []
    active_branches = []
    branch_in_prog = False
    for bn in branch_names:
        in_prog = branch_in_progress(bn, local)
        if in_prog:
            branch_in_prog = True
        active_branches.append({
            "name": bn,
            "ahead": commits_ahead(bn, "dev", local) if local else 0,
            "uncommitted_files": (
                uncommitted_file_count(local)
                if local and current_branch(local) == bn else 0
            ),
        })

    # Operational status: stored value, OR upgrade to in-progress if git says so
    stored_status = meta.get("status", "active")
    if stored_status == "active" and branch_in_prog:
        operational_status = "in-progress"
    else:
        operational_status = stored_status

    # New issues for THIS track (filed in last 7 days, matches track slug)
    track_slug = meta.get("track", track.name)
    new_issues_map = find_new_issues_for_tracks(repo, [track_slug], since_days=7) if repo else {}
    new_issues = []
    listed_set = set(issue_nums)
    for issue in new_issues_map.get(track_slug, []):
        if issue["number"] in listed_set:
            continue  # already in track
        new_issues.append({"number": issue["number"], "title": issue["title"]})

    # Drift detection: body status table vs GitHub
    drift_items = detect_drift(track.body, issues) if issues else []

    # Closure signals
    related_recent_count = len(new_issues_map.get(track_slug, []))
    signals = compute_signals(meta, issues, local, related_recent_count)
    closure_ready, closure_reasons = is_closure_ready(signals)
    if closure_ready:
        closure_signals_summary = None
    else:
        green = sum([signals.all_issues_closed, signals.all_branches_done,
                     signals.next_up_empty, signals.cold_14d, signals.no_recent_related_issues])
        closure_signals_summary = f"{green}/5 signals green"

    # Blockers
    blockers = [{"number": bn, "reason": "manually flagged"}
                for bn in (meta.get("blockers") or [])]

    # Time labels
    def lbl(key):
        if not meta.get(key):
            return "?"
        gs = (now - parse_iso_timestamp(meta[key])).total_seconds()
        return gap_seconds_to_label(int(gs))

    # Sort key
    in_prog_rank = 0 if operational_status == "in-progress" else 1
    pri_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(meta.get("launch_priority", "P3"), 3)
    recency_key = (
        -parse_iso_timestamp(meta["last_touched"]).timestamp()
        if meta.get("last_touched") else 0
    )

    return {
        "name": meta.get("track", track.name),
        "operational_status": operational_status,
        "launch_priority": meta.get("launch_priority", "P3"),
        "milestone_alignment": meta.get("milestone_alignment", "—"),
        "last_touched_label": lbl("last_touched"),
        "last_handoff_label": lbl("last_handoff"),
        "next_up": next_up_items,
        "active_branches": active_branches,
        "new_issues": new_issues,
        "blockers": blockers,
        "drift_items": drift_items,
        "closure_ready": closure_ready,
        "closure_signals_summary": closure_signals_summary,
        "archived_reopen": [],
        "sort_key": (in_prog_rank, pri_rank, recency_key),
    }


def _surface_archived_reopens(cfg: dict) -> None:
    """Scan archived/shipped tracks; if any new issue matches their slug, surface it."""
    archived = discover_archived_tracks(cfg)
    if not archived:
        return
    # Group by repo to batch gh queries
    by_repo: dict[str, list] = {}
    for a in archived:
        if a.repo:
            by_repo.setdefault(a.repo, []).append(a)
    callouts = []
    for repo, tracks_in_repo in by_repo.items():
        slugs = [a.meta.get("track", a.name) for a in tracks_in_repo]
        new_map = find_new_issues_for_tracks(repo, slugs, since_days=14)
        for slug, issues in new_map.items():
            for issue in issues:
                callouts.append((slug, issue))
    if callouts:
        print("--- Archived tracks with new activity ---")
        for slug, issue in callouts:
            print("  " + render_archived_reopen(repo, slug, issue))
        print()
```

- [ ] **Step 2: Smoke-test against missing config**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py brief
```

Expected: ERROR about config.yml. Exit 1.

- [ ] **Step 3: Create config + retry**

```bash
mkdir -p ~/.claude/work-plan
cat > ~/.claude/work-plan/config.yml <<'EOF'
notes_root: /Applications/Development/Projects/Project Notes/
repos:
  critforge:
    github: stylusnexus/CritForge
    local: /Applications/Development/Projects/CritForge
EOF
python3 ~/.claude/skills/work-plan/work_plan.py brief
```

Expected: Either "No tracks found" (if nothing has frontmatter yet) OR a brief with `[NEEDS FILING]` notes.

---

### Task 14: list command

**Files:**
- Create: `~/.claude/skills/work-plan/commands/list_cmd.py`

- [ ] **Step 1: Implement**

`~/.claude/skills/work-plan/commands/list_cmd.py`:

```python
"""list subcommand."""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, discover_archived_tracks


def run(args: list[str]) -> int:
    show_all = "--all" in args
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    if not tracks and not show_all:
        print(f"No tracks found under {cfg['notes_root']}")
        return 0

    print(f"Tracks under {cfg['notes_root']}:\n")
    for t in tracks:
        status = t.meta.get("status", "(no frontmatter)")
        priority = t.meta.get("launch_priority", "—")
        repo = t.repo or "(no repo)"
        flags = []
        if t.needs_init:
            flags.append("NEEDS INIT")
        if t.needs_filing:
            flags.append("NEEDS FILING")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  {t.name:30}  {status:14}  {priority:3}  {repo}{flag_str}")

    if show_all:
        archived = discover_archived_tracks(cfg)
        if archived:
            print("\nArchived:")
            for a in archived:
                end_state = a.meta.get("status", "?")
                print(f"  {a.name:30}  {end_state:14}  {a.repo or '(no repo)'}")
    return 0
```

- [ ] **Step 2: Smoke-test**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py list
```

Expected: Lists discovered files. If your 4 .md files are still at notes_root level (not yet moved into critforge/), they show with `[NEEDS FILING]`.

---

## Phase 5 — `handoff`

### Task 15: Session log writer

**Files:**
- Create: `~/.claude/skills/work-plan/tests/test_session_log.py`
- Create: `~/.claude/skills/work-plan/lib/session_log.py`

- [ ] **Step 1: Test**

`~/.claude/skills/work-plan/tests/test_session_log.py`:

```python
"""Tests for session_log."""
import unittest
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from lib.session_log import append_session_log, SESSION_LOG_HEADER


class AppendSessionLogTest(unittest.TestCase):
    def test_appends_under_existing_section(self):
        body = (
            "# Track\n\nProse.\n\n"
            f"{SESSION_LOG_HEADER}\n\n"
            "### Session — 2026-04-23 22:14\n\n- Touched: prior\n"
        )
        new = append_session_log(
            body, timestamp="2026-04-28 18:30",
            touched=["#4254 polls"], next_up=["#925 wmsr"], blockers=[],
        )
        self.assertIn("### Session — 2026-04-28 18:30", new)
        self.assertIn("### Session — 2026-04-23 22:14", new)
        self.assertIn("- Touched: #4254 polls", new)

    def test_creates_section_when_missing(self):
        body = "# Track\n\nProse.\n"
        new = append_session_log(
            body, timestamp="2026-04-28 18:30",
            touched=["#1 foo"], next_up=["#2 bar"],
            blockers=[{"number": 3, "reason": "waiting"}],
        )
        self.assertIn(SESSION_LOG_HEADER, new)
        self.assertIn("- Blocker: #3 — waiting", new)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement**

`~/.claude/skills/work-plan/lib/session_log.py`:

```python
"""Append session log entries to track body."""

SESSION_LOG_HEADER = "## Session log"


def append_session_log(body: str, timestamp: str,
                       touched: list[str], next_up: list[str],
                       blockers: list[dict]) -> str:
    """Append a `### Session — <timestamp>` block under the Session log section."""
    block_lines = [f"### Session — {timestamp}\n"]
    if touched:
        for t in touched:
            block_lines.append(f"- Touched: {t}")
    else:
        block_lines.append("- Touched: (nothing committed)")
    if next_up:
        for n in next_up:
            block_lines.append(f"- Next: {n}")
    else:
        block_lines.append("- Next: (open)")
    if blockers:
        for b in blockers:
            block_lines.append(f"- Blocker: #{b['number']} — {b['reason']}")
    block_lines.append("")
    block = "\n".join(block_lines)

    if SESSION_LOG_HEADER in body:
        idx = body.index(SESSION_LOG_HEADER)
        rest = body[idx + len(SESSION_LOG_HEADER):]
        next_h2 = rest.find("\n## ")
        if next_h2 == -1:
            insertion = rest + "\n" + block
        else:
            insertion = rest[:next_h2] + "\n" + block + rest[next_h2:]
        return body[:idx] + SESSION_LOG_HEADER + insertion

    if not body.endswith("\n"):
        body += "\n"
    return body + f"\n{SESSION_LOG_HEADER}\n\n{block}"
```

- [ ] **Step 3: Verify PASS**

```bash
cd ~/.claude/skills/work-plan && python3 -m unittest tests.test_session_log -v
```

Expected: 2 tests PASS.

---

### Task 16: Handoff command

**Files:**
- Create: `~/.claude/skills/work-plan/commands/handoff.py`

The handoff command is INTERACTIVE. Reads stdin for prompts.

- [ ] **Step 1: Implement**

`~/.claude/skills/work-plan/commands/handoff.py`:

```python
"""handoff subcommand."""
import sys
from datetime import datetime

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.frontmatter import write_file
from lib.session_log import append_session_log
from lib.git_state import has_uncommitted, current_branch


def run(args: list[str]) -> int:
    track_arg = args[0] if args else None

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    matching = [t for t in tracks if t.has_frontmatter
                and (track_arg is None
                     or t.name == track_arg
                     or t.meta.get("track") == track_arg)]
    if not matching:
        print(f"No track matching '{track_arg}'.")
        return 1
    if len(matching) > 1 and track_arg:
        print(f"Multiple matches for '{track_arg}':")
        for t in matching:
            print(f"  {t.name}")
        return 1
    if len(matching) > 1:
        # Try to pick by current git branch
        for t in matching:
            cb = current_branch(t.local_path) if t.local_path else None
            for b in (t.meta.get("github", {}).get("branches") or []):
                if cb == b:
                    matching = [t]
                    break
        if len(matching) > 1:
            print("Multiple active tracks; specify name:")
            for t in matching:
                print(f"  {t.name}")
            return 1

    track = matching[0]
    print(f"Handoff for: {track.name}\n")

    print("What did you touch this session? (one item per line, blank line to finish):")
    touched = _read_lines()

    print("\nWhat's next? (one item per line, blank line to finish):")
    next_up_text = _read_lines()

    print("\nBlockers? (format: #NNNN reason — one per line, blank to finish):")
    blocker_lines = _read_lines()
    blockers = []
    for line in blocker_lines:
        if not line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        try:
            num = int(parts[0][1:])
            reason = parts[1] if len(parts) > 1 else "(no reason given)"
            blockers.append({"number": num, "reason": reason})
        except (ValueError, IndexError):
            continue

    # Update frontmatter
    now = datetime.now()
    iso_now = now.strftime("%Y-%m-%dT%H:%M")
    track.meta["last_touched"] = iso_now
    track.meta["last_handoff"] = iso_now
    if blockers:
        track.meta["blockers"] = [b["number"] for b in blockers]

    # Demote in-progress → active if no uncommitted
    if track.meta.get("status") == "in-progress":
        if not (track.local_path and has_uncommitted(track.local_path)):
            track.meta["status"] = "active"

    new_body = append_session_log(
        track.body,
        timestamp=now.strftime("%Y-%m-%d %H:%M"),
        touched=touched,
        next_up=next_up_text,
        blockers=blockers,
    )
    write_file(track.path, track.meta, new_body)
    print(f"\n✓ Updated {track.path.name}")
    return 0


def _read_lines() -> list[str]:
    out = []
    for line in sys.stdin:
        line = line.rstrip()
        if not line:
            break
        out.append(line)
    return out
```

- [ ] **Step 2: Smoke-test deferred until Phase 9 migration**

---

### Task 17: Status table updater wired into handoff (opt-in)

**Files:**
- Modify: `~/.claude/skills/work-plan/commands/handoff.py`

Right before writing the file, also update body status table for any newly-shipped issues mentioned by the user.

- [ ] **Step 1: Add status-table update step**

After `new_body = append_session_log(...)` in `commands/handoff.py`, ADD:

```python
    # Auto-update status table from GitHub state
    issue_nums = track.meta.get("github", {}).get("issues") or []
    if issue_nums and track.repo:
        from lib.github_state import fetch_issues
        from lib.status_table import update_row_status
        issues = fetch_issues(track.repo, issue_nums)
        for i in issues:
            new_status = "✅ Shipped" if i.get("state") == "CLOSED" else "🔲 Open"
            new_body = update_row_status(new_body, i["number"], new_status)
```

(Insert above the `write_file(...)` line.)

- [ ] **Step 2: No new test (covered by status_table + github_state tests)**

---

## Phase 6 — `where-was-i`

### Task 18: where-was-i command

**Files:**
- Create: `~/.claude/skills/work-plan/commands/where_was_i.py`

- [ ] **Step 1: Implement**

`~/.claude/skills/work-plan/commands/where_was_i.py`:

```python
"""where-was-i subcommand."""
from datetime import datetime

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.github_state import fetch_issues
from lib.git_state import (
    parse_iso_timestamp, gap_seconds_to_label,
    current_branch, has_uncommitted, uncommitted_file_count, commits_ahead,
)
from lib.new_issues import find_new_issues_for_tracks


def run(args: list[str]) -> int:
    if not args:
        print("usage: work_plan.py where-was-i <track-name>")
        return 2
    track_name = args[0]

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    matching = [t for t in tracks
                if t.has_frontmatter and (t.name == track_name or t.meta.get("track") == track_name)]
    if not matching:
        print(f"No track matching '{track_name}'.")
        return 1
    track = matching[0]

    lh = track.meta.get("last_handoff")
    if lh:
        gap = (datetime.now() - parse_iso_timestamp(lh)).total_seconds()
        print(f"WHERE YOU WERE — {track.name} (last handoff: {lh}, {gap_seconds_to_label(int(gap))})")
    else:
        print(f"WHERE YOU WERE — {track.name} (no prior handoff)")
    print()

    last_session = _extract_last_session(track.body)
    if last_session:
        print("Last session log:")
        for line in last_session.split("\n"):
            print(f"  {line}")
        print()

    # Issue state
    issue_nums = track.meta.get("github", {}).get("issues") or []
    if track.repo and issue_nums:
        issues = fetch_issues(track.repo, issue_nums)
        print("Current issue state:")
        for i in issues:
            state = i.get("state", "?").lower()
            print(f"  #{i['number']}: {state} — {i.get('title','')}")
        print()

    # New issues since last handoff
    if track.repo and lh:
        days_ago = max(1, int((datetime.now() - parse_iso_timestamp(lh)).total_seconds() / 86400))
        slug = track.meta.get("track", track.name)
        new_map = find_new_issues_for_tracks(track.repo, [slug], since_days=days_ago)
        listed = set(issue_nums)
        new_unlisted = [i for i in new_map.get(slug, []) if i["number"] not in listed]
        if new_unlisted:
            print("New issues since last handoff (not yet in track):")
            for i in new_unlisted:
                print(f"  #{i['number']} {i['title']}  → /work-plan slot {i['number']} {slug}")
            print()

    # Local git state
    if track.local_path:
        cur = current_branch(track.local_path)
        if cur:
            uc = uncommitted_file_count(track.local_path)
            ahead = commits_ahead(cur, "dev", track.local_path)
            print(f"Local git: on branch '{cur}', {ahead} commits ahead of dev, "
                  f"{uc} uncommitted file(s)")
            print()

    next_up = track.meta.get("next_up") or []
    if next_up:
        print(f"Suggested first move: continue on #{next_up[0]}")
    return 0


def _extract_last_session(body: str) -> str:
    if "### Session — " not in body:
        return ""
    idx = body.rfind("### Session — ")
    rest = body[idx:]
    end = len(rest)
    for marker in ("\n### ", "\n## "):
        m = rest.find(marker, 1)
        if m != -1 and m < end:
            end = m
    return rest[:end].strip()
```

- [ ] **Step 2: Smoke-test deferred until Phase 9**

---

## Phase 7 — `slot`, `refresh-md`, `close`

### Task 19: refresh-md command

**Files:**
- Create: `~/.claude/skills/work-plan/commands/refresh_md.py`

- [ ] **Step 1: Implement**

`~/.claude/skills/work-plan/commands/refresh_md.py`:

```python
"""refresh-md subcommand."""
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.github_state import fetch_issues
from lib.frontmatter import write_file
from lib.status_table import find_status_table, update_row_status, ISSUE_NUM_RE


def run(args: list[str]) -> int:
    if not args:
        print("usage: work_plan.py refresh-md <track-name>")
        return 2
    track_name = args[0]

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    matching = [t for t in tracks if t.has_frontmatter
                and (t.name == track_name or t.meta.get("track") == track_name)]
    if not matching:
        print(f"No track matching '{track_name}'.")
        return 1
    track = matching[0]

    table = find_status_table(track.body)
    if not table:
        print(f"No status table found in {track.path.name}.")
        return 0

    table_issues = set()
    for row in table["rows"]:
        for cell in row["cells"]:
            for m in ISSUE_NUM_RE.findall(cell):
                table_issues.add(int(m))
    if not table_issues:
        print("Status table has no issue references.")
        return 0

    issues = fetch_issues(track.repo, sorted(table_issues))
    new_body = track.body
    updates = []
    for i in issues:
        new_status = "✅ Shipped" if i.get("state") == "CLOSED" else "🔲 Open"
        new_body = update_row_status(new_body, i["number"], new_status)
        updates.append((i["number"], new_status))

    if new_body == track.body:
        print("No changes needed.")
        return 0

    print(f"Proposed updates to {track.path.name}:")
    for num, status in updates:
        print(f"  #{num} → {status}")
    print("\nApply? [y/N]")
    if input().strip().lower() != "y":
        print("Cancelled.")
        return 0

    write_file(track.path, track.meta, new_body)
    print(f"✓ Updated {track.path.name}")
    return 0
```

---

### Task 20: slot command

**Files:**
- Create: `~/.claude/skills/work-plan/commands/slot.py`

- [ ] **Step 1: Implement**

`~/.claude/skills/work-plan/commands/slot.py`:

```python
"""slot subcommand."""
import json
import subprocess

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.frontmatter import write_file


def run(args: list[str]) -> int:
    if not args:
        print("usage: work_plan.py slot <issue-num> [track-name]")
        return 2
    try:
        issue_num = int(args[0])
    except ValueError:
        print(f"ERROR: '{args[0]}' is not an issue number.")
        return 2
    target_name = args[1] if len(args) > 1 else None

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    active = [t for t in tracks if t.has_frontmatter
              and t.meta.get("status") in ("active", "in-progress", "blocked")]

    if target_name:
        matching = [t for t in active
                    if t.name == target_name or t.meta.get("track") == target_name]
        if not matching:
            print(f"No active track matching '{target_name}'.")
            return 1
        target = matching[0]
    else:
        print("Active tracks:")
        for i, t in enumerate(active, 1):
            print(f"  [{i}] {t.name} ({t.meta.get('launch_priority','P3')}, "
                  f"{t.meta.get('milestone_alignment','—')})")
        print("\nSlot into which? (number or name):")
        choice = input().strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if not (0 <= idx < len(active)):
                print("Out of range.")
                return 1
            target = active[idx]
        else:
            matching = [t for t in active if t.name == choice or t.meta.get("track") == choice]
            if not matching:
                print(f"No active track matching '{choice}'.")
                return 1
            target = matching[0]

    issues = list(target.meta.get("github", {}).get("issues") or [])
    if issue_num in issues:
        print(f"#{issue_num} already in track '{target.name}'.")
        return 0
    issues.append(issue_num)
    target.meta.setdefault("github", {})["issues"] = sorted(issues)

    # Milestone-conflict check
    proc = subprocess.run(
        ["gh", "issue", "view", str(issue_num),
         "--repo", target.repo, "--json", "milestone"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        info = json.loads(proc.stdout)
        m = info.get("milestone", {})
        if m and m.get("title") and m["title"] != target.meta.get("milestone_alignment"):
            print(f"⚠  #{issue_num} is on milestone '{m['title']}', "
                  f"track '{target.name}' aligned to '{target.meta.get('milestone_alignment')}'.")

    write_file(target.path, target.meta, target.body)
    print(f"✓ Slotted #{issue_num} into '{target.name}'.")
    return 0
```

---

### Task 21: close command

**Files:**
- Create: `~/.claude/skills/work-plan/commands/close.py`

- [ ] **Step 1: Implement**

`~/.claude/skills/work-plan/commands/close.py`:

```python
"""close subcommand."""
import shutil
from pathlib import Path

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks
from lib.frontmatter import write_file


def run(args: list[str]) -> int:
    if not args:
        print("usage: work_plan.py close <track-name>")
        return 2
    track_name = args[0]

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)
    matching = [t for t in tracks if t.has_frontmatter
                and (t.name == track_name or t.meta.get("track") == track_name)]
    if not matching:
        print(f"No track matching '{track_name}'.")
        return 1
    track = matching[0]

    print(f"Closing track: {track.name}")
    print("Choose state: [s]hipped, [p]arked, [a]bandoned")
    choice = input().strip().lower()
    end_state = {"s": "shipped", "p": "parked", "a": "abandoned"}.get(choice)
    if not end_state:
        print("Invalid choice. Cancelled.")
        return 1

    print("Wrap-up note (optional, single line):")
    note = input().strip()

    track.meta["status"] = end_state
    new_body = track.body
    if note:
        new_body += f"\n\n## Wrap-up\n\n{note}\n"

    write_file(track.path, track.meta, new_body)

    if end_state == "parked":
        print(f"✓ '{track.name}' marked parked. Stays in place.")
        return 0

    notes_root = Path(cfg["notes_root"])
    folder = track.path.parent
    archive_dir = folder / "archive" / end_state
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / track.path.name
    shutil.move(str(track.path), str(dest))
    print(f"✓ '{track.name}' marked {end_state}, moved to {dest.relative_to(notes_root)}")
    return 0
```

---

## Phase 8 — `init`, `suggest-priorities`, SKILL.md

### Task 22: init command

**Files:**
- Create: `~/.claude/skills/work-plan/commands/init.py`

- [ ] **Step 1: Implement**

`~/.claude/skills/work-plan/commands/init.py`:

```python
"""init subcommand."""
import re
from datetime import datetime
from pathlib import Path

from lib.config import load_config, ConfigError, resolve_github_for_folder
from lib.frontmatter import parse_file, write_file


def run(args: list[str]) -> int:
    if not args:
        print("usage: work_plan.py init <path-to-md>")
        return 2
    path = Path(args[0]).expanduser().resolve()
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 1

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    meta, body = parse_file(path)
    if meta:
        print(f"{path.name} already has frontmatter.")
        return 0

    slug = re.sub(r"[^a-z0-9-]+", "-", path.stem.lower()).strip("-")

    notes_root = Path(cfg["notes_root"])
    try:
        rel = path.relative_to(notes_root)
        folder = rel.parts[0] if len(rel.parts) > 1 else None
    except ValueError:
        folder = None
    repo = resolve_github_for_folder(folder, cfg) if folder else None

    issue_nums = sorted(set(int(m) for m in re.findall(r"#(\d+)", body)))

    print(f"Initializing: {path.name}")
    print(f"  track: {slug}")
    print(f"  repo: {repo or '(unknown — will set TBD)'}")
    print(f"  issues found in body: {issue_nums or '(none)'}")
    print()
    print("Launch priority? [P0/P1/P2/P3] (default P2):")
    priority = (input().strip() or "P2").upper()
    if priority not in ("P0", "P1", "P2", "P3"):
        priority = "P2"

    print("Milestone? (default v1.0.0):")
    milestone = input().strip() or "v1.0.0"

    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    meta = {
        "track": slug, "status": "active",
        "launch_priority": priority,
        "milestone_alignment": milestone,
        "github": {"repo": repo or "TBD", "issues": issue_nums, "branches": []},
        "related_tracks": [],
        "last_touched": now, "last_handoff": now,
        "next_up": [], "blockers": [],
    }
    write_file(path, meta, body)
    print(f"✓ Frontmatter added to {path.name}.")
    return 0
```

---

### Task 23: suggest-priorities command (AI-assisted)

**Files:**
- Create: `~/.claude/skills/work-plan/commands/suggest_priorities.py`

This command shells out to `claude` (the Claude Code CLI) to batch-rank issues. Since we're running INSIDE a Claude Code skill, we delegate the AI call back to the parent agent via a structured output that the skill markdown handles.

For the CLI portion: fetch a batch of issues, write a prompt file, and tell the user (or the calling agent) to ask Claude to fill it in.

- [ ] **Step 1: Implement (CLI side — fetch + scaffold)**

`~/.claude/skills/work-plan/commands/suggest_priorities.py`:

```python
"""suggest-priorities subcommand: prepare batch for AI labeling.

This command:
1. Fetches all unlabeled issues (no priority/PN label) for a repo
2. Writes a JSON batch to /tmp/work_plan_priorities.json
3. Prints a structured prompt the calling agent can answer
4. After agent fills in priorities, --apply mode applies them via gh label add
"""
import json
import subprocess
import sys
from pathlib import Path

from lib.config import load_config, ConfigError

BATCH_PATH = Path("/tmp/work_plan_priorities.json")
PROMPT_TEMPLATE = """\
For each GitHub issue below, suggest a priority label (P0/P1/P2/P3) based on
title, milestone, and labels. Return JSON: [{"number": N, "priority": "P0"}, ...]

Heuristics:
- P0: launch-critical bugs/features tagged for v0.4.0 or v1.0.0 with urgent verbs (blocks, breaks, must)
- P1: important but not blocking; v0.4.0/v1.0.0 features
- P2: should ship eventually; v1.0.0 nice-to-haves, v2.0.0 features
- P3: backlog; long-tail polish, parked work

Skip issues with insufficient signal. Output ONLY valid JSON.

Issues:
"""


def run(args: list[str]) -> int:
    apply_mode = "--apply" in args
    repo_arg = next((a for a in args if a.startswith("--repo=")), None)

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    if apply_mode:
        return _apply()

    # Fetch mode
    repos = list(cfg["repos"].keys())
    if repo_arg:
        repo_folder = repo_arg.split("=", 1)[1]
        repos = [repo_folder]
    elif len(repos) > 1:
        print("Multiple repos in config. Specify with --repo=<folder-name>.")
        return 1

    folder = repos[0]
    repo = cfg["repos"][folder]["github"]
    print(f"Fetching unlabeled issues in {repo}...")

    # Fetch open issues without any priority/* label
    proc = subprocess.run(
        ["gh", "issue", "list", "--repo", repo,
         "--state", "open", "--limit", "100",
         "--json", "number,title,milestone,labels,url"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"ERROR fetching issues: {proc.stderr}")
        return 1
    all_issues = json.loads(proc.stdout) if proc.stdout.strip() else []

    unlabeled = [
        i for i in all_issues
        if not any(l["name"].startswith("priority/") for l in i.get("labels", []))
    ]
    if not unlabeled:
        print("All open issues already have priority labels.")
        return 0

    BATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_PATH.write_text(json.dumps({"repo": repo, "issues": unlabeled}, indent=2))
    print(f"Wrote {len(unlabeled)} issues to {BATCH_PATH}")
    print()
    print("=" * 60)
    print(PROMPT_TEMPLATE)
    for i in unlabeled:
        m = i.get("milestone", {})
        m_title = m.get("title", "—") if m else "—"
        labels = [l["name"] for l in i.get("labels", [])]
        print(f"#{i['number']} [{m_title}] [{','.join(labels) or 'no-labels'}] {i['title']}")
    print("=" * 60)
    print()
    print(f"After agent returns JSON, save to {BATCH_PATH.with_suffix('.answers.json')}")
    print(f"Then run: python3 {Path(__file__).resolve()} --apply")
    return 0


def _apply() -> int:
    answers_path = BATCH_PATH.with_suffix(".answers.json")
    if not answers_path.exists():
        print(f"ERROR: {answers_path} not found. Run without --apply first.")
        return 1
    if not BATCH_PATH.exists():
        print(f"ERROR: {BATCH_PATH} not found.")
        return 1
    batch = json.loads(BATCH_PATH.read_text())
    repo = batch["repo"]
    answers = json.loads(answers_path.read_text())

    print(f"Applying {len(answers)} priority labels to {repo}...")
    for ans in answers:
        num = ans["number"]
        priority = ans["priority"]
        if priority not in ("P0", "P1", "P2", "P3"):
            print(f"  SKIP #{num}: invalid priority '{priority}'")
            continue
        proc = subprocess.run(
            ["gh", "issue", "edit", str(num),
             "--repo", repo,
             "--add-label", f"priority/{priority}"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            print(f"  ✓ #{num} → priority/{priority}")
        else:
            print(f"  ✗ #{num}: {proc.stderr.strip()}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
```

- [ ] **Step 2: Smoke-test fetch mode**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py suggest-priorities --repo=critforge
```

Expected: Lists unlabeled issues + writes to `/tmp/work_plan_priorities.json`.

The "ask Claude to fill in priorities" step is documented in SKILL.md (Task 24). The Python CLI does the I/O; Claude does the AI call.

---

### Task 24: SKILL.md final version

**Files:**
- Modify: `~/.claude/skills/work-plan/SKILL.md`

- [ ] **Step 1: Replace SKILL.md**

Write to `~/.claude/skills/work-plan/SKILL.md`:

````markdown
---
name: work-plan
description: Track-aware daily work planning. Subcommands brief / handoff / where-was-i / slot / close / refresh-md / list / init / suggest-priorities. Reads YAML-frontmattered Project Notes/<repo>/*.md; queries GitHub live for issue state; auto-detects in-progress branches, drift, new related issues, and closure-readiness. Use when starting a session, ending a session, switching between parallel Claude Code sessions on different tracks, or migrating an existing notes file into the system.
---

# Work Plan

Track-aware daily planner. Composes with `/repo-activity-summary` (global view) and `/handoff` (fresh-session export). Spec: `<CritForge>/docs/superpowers/specs/2026-04-28-daily-work-planner-design.md`.

## When to use which subcommand

| Subcommand | When |
|---|---|
| `/work-plan brief` | Starting work, after a gap, or whenever a multi-track snapshot is needed. |
| `/work-plan handoff [track]` | Wrapping up a work block. Captures touched + next + blockers. Updates frontmatter and body status table. |
| `/work-plan where-was-i [track]` | Re-orienting on a track after switching from another Claude Code session. |
| `/work-plan slot <issue-num> [track]` | A new GitHub issue should belong to a track. |
| `/work-plan close [track]` | Track is done (shipped) / paused (parked) / won't ship (abandoned). |
| `/work-plan refresh-md [track]` | Body status icons drifted from GitHub state. |
| `/work-plan list [--all]` | List active tracks (or all including parked/archived). |
| `/work-plan init <path>` | Add frontmatter to a new track .md file. |
| `/work-plan suggest-priorities --repo=<folder>` | Batch AI label backfill (one-time migration). |

## How to invoke

ALL subcommands route through the Python CLI:

```bash
python3 ~/.claude/skills/work-plan/work_plan.py <subcommand> [args...]
```

Run that EXACT command via Bash. Don't reimplement the logic in chat.

## Per-subcommand notes

- **`brief`** — Read-only. Output IS the brief — relay verbatim.
- **`handoff`** — Interactive (prompts via stdin). Pipe answers as multi-line input. Each prompt is "one item per line, blank line to advance."
- **`where-was-i`** — Read-only. Output is also a fresh-session prompt; user can paste into a new terminal.
- **`slot`** — Interactive without args (lists + asks for selection). Pass track name to skip prompt.
- **`close`** — Interactive (asks for end state + optional wrap note).
- **`refresh-md`** — Interactive (asks for confirmation).
- **`init`** — Interactive (asks for priority + milestone if not inferable).
- **`suggest-priorities`** — Two-step: (1) CLI fetches unlabeled issues + writes prompt to terminal. (2) YOU (Claude) read the issues, output JSON `[{"number": N, "priority": "P0"}, ...]`, save to `/tmp/work_plan_priorities.answers.json`, then run with `--apply` to apply labels via `gh`.

### suggest-priorities AI workflow

When user runs `/work-plan suggest-priorities --repo=<folder>`:

1. CLI fetches unlabeled issues, prints them with milestone + labels + title.
2. YOU produce JSON ranking each: `[{"number": 4254, "priority": "P0"}, ...]`. Use heuristics: launch-critical → P0; important → P1; eventual → P2; backlog → P3.
3. Save your JSON to `/tmp/work_plan_priorities.answers.json` via the Write tool.
4. Run `python3 ~/.claude/skills/work-plan/work_plan.py suggest-priorities --apply` to apply via `gh`.

Show the user the proposed labels BEFORE applying. They may want to override.

## Setup (one-time)

```bash
mkdir -p ~/.claude/work-plan
cat > ~/.claude/work-plan/config.yml <<'EOF'
notes_root: /Applications/Development/Projects/Project Notes/
repos:
  critforge:
    github: stylusnexus/CritForge
    local: /Applications/Development/Projects/CritForge
EOF
```

Then create per-repo subfolders under notes_root and move existing track files in.

## Composition with other skills

- DO use `/repo-activity-summary` for the global "what's open across the whole repo" view.
- DO use `/handoff` (existing skill) for spinning up a new Claude Code session on a generic context.
- DO use `/work-plan` for track-aware work: bookended brief/handoff, parallel-session re-orientation, drift detection, closure.

## Common mistakes

| Mistake | Fix |
|---|---|
| Running brief without config | Run setup first. |
| Calling `gh` directly to check issue state | `brief` already does it, with track context. |
| Editing track frontmatter manually | Prefer `/work-plan handoff` or `/work-plan slot` — they update timestamps and dedupe. |
| Forgetting to label issues with priority/PN | Brief sorts by priority. Without labels, everything looks the same. |
| Setting `local:` in config to a path that doesn't exist | In-progress detection silently no-ops. Verify path. |
````

- [ ] **Step 2: Smoke-test from Claude Code**

In a new prompt:

```
/work-plan brief
```

Expected: Skill engages, runs the bash command, relays output.

---

## Phase 9 — Migration on Eve's Actual Notes

### Task 25: Create folder structure + config

- [ ] **Step 1: Create folders**

```bash
mkdir -p "/Applications/Development/Projects/Project Notes/critforge/archive/shipped"
mkdir -p "/Applications/Development/Projects/Project Notes/critforge/archive/abandoned"
```

- [ ] **Step 2: Confirm config exists with correct local path**

```bash
cat ~/.claude/work-plan/config.yml
```

Expected: Shows the dict-shape config with `local: /Applications/Development/Projects/CritForge`. If not, create it (see Task 13 step 3).

---

### Task 26: Move 4 existing track files into critforge/

- [ ] **Step 1: Move files**

```bash
cd "/Applications/Development/Projects/Project Notes/"
mv tabletop.md ux-redesign.md roll20-features.md "Storytelling Enhancements.md" critforge/
ls critforge/
```

Expected: 4 files now in critforge/.

---

### Task 27: Backfill frontmatter on each file

- [ ] **Step 1: Run init on each**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py init "/Applications/Development/Projects/Project Notes/critforge/tabletop.md"
```

Answer prompts: priority (e.g. P1), milestone (e.g. v1.0.0).

Repeat for: `ux-redesign.md`, `roll20-features.md`, `Storytelling Enhancements.md`.

- [ ] **Step 2: Verify with list**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py list
```

Expected: All 4 tracks listed under critforge with priorities, no `[NEEDS INIT]` flags.

---

### Task 28: Create GitHub priority labels + AI backfill

- [ ] **Step 1: Create labels**

```bash
gh label create "priority/P0" --color "B60205" --description "Critical for current milestone" --repo stylusnexus/CritForge 2>/dev/null || true
gh label create "priority/P1" --color "D93F0B" --description "Important" --repo stylusnexus/CritForge 2>/dev/null || true
gh label create "priority/P2" --color "FBCA04" --description "Should ship eventually" --repo stylusnexus/CritForge 2>/dev/null || true
gh label create "priority/P3" --color "0E8A16" --description "Backlog" --repo stylusnexus/CritForge 2>/dev/null || true
```

- [ ] **Step 2: Run suggest-priorities**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py suggest-priorities --repo=critforge
```

Expected: Lists unlabeled open issues with milestone + labels + title.

- [ ] **Step 3: AI-assisted ranking (Claude does this in-skill)**

Read the printed list. Produce a JSON file `/tmp/work_plan_priorities.answers.json` with `[{"number": N, "priority": "PX"}, ...]` for each. Heuristics:

- P0: launch-critical bugs/features, blocks shipping
- P1: important but not blocking; ships before launch
- P2: should ship eventually; nice-to-have for v1.0.0
- P3: backlog; v2.0.0 or polish

Show user the proposed list, get approval, then:

- [ ] **Step 4: Apply labels**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py suggest-priorities --apply
```

Expected: Labels applied via `gh`. Lists results per issue.

---

### Task 29: First brief, handoff, where-was-i

- [ ] **Step 1: Run first brief**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py brief
```

Expected: Multi-track output with priorities, milestones, last-touched. Possibly shows in-progress badges, drift items, new issues. This is the "value delivered" moment.

- [ ] **Step 2: Test handoff on tabletop**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py handoff tabletop
```

Type a few lines for each prompt. Verify:
- File `Project Notes/critforge/tabletop.md` updated
- Frontmatter `last_handoff` updated to current ISO timestamp
- New `### Session — <today>` block appended

- [ ] **Step 3: Test where-was-i**

```bash
python3 ~/.claude/skills/work-plan/work_plan.py where-was-i tabletop
```

Expected: Shows the session block you just wrote, current GitHub state of issues, local git state.

---

## Done state

When all 29 tasks are complete:

- ✅ A working `/work-plan` skill at `~/.claude/skills/work-plan/`
- ✅ Eve's 4 existing notes migrated into `critforge/` subfolder with full frontmatter
- ✅ GitHub `priority/PN` labels created and AI-backfilled across all open issues
- ✅ `~/.claude/work-plan/config.yml` exists with notes_root + repos (with local paths)
- ✅ `/work-plan brief` produces a daily snapshot with: in-progress detection from git, new-issue surfacing, drift detection, closure-ready flagging, archived-track re-open warnings
- ✅ `/work-plan handoff` captures end-of-block state and updates body status tables
- ✅ `/work-plan where-was-i` re-orients on a single track
- ✅ Closure model works (with `close`)
- ✅ Status drift detection works (auto in `brief`, fix via `refresh-md`)
- ✅ Spec + plan committed on `spec/work-plan-skill` branch

## Pause-points if not finishing in one session

Each phase boundary leaves the system in a working state:

- **After Phase 4** — brief + list work read-only against live tracks. Useful as a daily snapshot tool.
- **After Phase 5** — bookend ritual works. handoff updates body status tables.
- **After Phase 6** — full MVP1+2+3. Parallel-session switching works.
- **After Phase 7** — closure + slot + refresh-md complete.
- **After Phase 8** — skill markdown finalized; ready for daily use.
- **After Phase 9** — system live on Eve's actual notes. The real "value delivered" line.
