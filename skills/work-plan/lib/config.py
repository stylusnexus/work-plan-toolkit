"""Load + validate ~/.claude/work-plan/config.yml."""
import json
import subprocess
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "work-plan" / "config.yml"
DEFAULT_NOTES_ROOT = Path.home() / ".claude" / "work-plan" / "notes"

_SEED_TEMPLATE = (
    "# work-plan config — auto-seeded on first run. Edit to customize.\n"
    "# Run /work-plan init-repo <key> --github=<org/repo> to populate repos:.\n"
    "notes_root: {notes_root}\n"
    "repos: {{}}\n"
)


class ConfigError(Exception):
    pass


def ensure_config(path: Path = DEFAULT_CONFIG_PATH,
                  notes_root: Path = DEFAULT_NOTES_ROOT) -> bool:
    """Create a default config.yml (and notes_root dir) if absent.

    Single source of the seed content — install.sh/install.ps1 delegate here, so
    plugin installs (which run no install hook) and script installs behave
    identically. `notes_root` is written as an ABSOLUTE path (never a literal
    `~`, which downstream `Path(...)` would not expand). Returns True if it
    created the file, False if it already existed.
    """
    path = Path(path)
    if path.exists():
        return False
    notes_root = Path(notes_root).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    notes_root.mkdir(parents=True, exist_ok=True)
    path.write_text(_SEED_TEMPLATE.format(notes_root=notes_root), encoding="utf-8")
    return True


def load_config(path: Path = DEFAULT_CONFIG_PATH,
                notes_root: Path = DEFAULT_NOTES_ROOT) -> dict:
    """Load and validate. Self-seeds a default config if absent (no install hook
    exists for plugin installs). Normalizes string-shape repo entries to dicts."""
    path = Path(path)
    if not path.exists():
        ensure_config(path, notes_root)
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


def is_valid_git_repo(path: Path) -> bool:
    """Return True if path is a directory that contains a .git entry."""
    p = Path(path)
    return p.is_dir() and (p / ".git").exists()


def resolve_github_for_folder(folder_name: str, cfg: dict) -> Optional[str]:
    entry = cfg.get("repos", {}).get(folder_name)
    return entry.get("github") if entry else None


def resolve_local_path_for_folder(folder_name: str, cfg: dict) -> Optional[Path]:
    entry = cfg.get("repos", {}).get(folder_name)
    if not entry or not entry.get("local"):
        return None
    return Path(entry["local"]).expanduser()
