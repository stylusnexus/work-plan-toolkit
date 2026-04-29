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
