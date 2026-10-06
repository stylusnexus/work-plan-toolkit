"""Load + validate ~/.claude/work-plan/config.yml."""
import json
import os
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
    # A key-only `repos:` parses as null: treat it as "no repos yet", like
    # `repos: {}`. Any other non-mapping shape is a config error, not a crash (#432).
    repos = cfg.get("repos")
    if repos is None:
        repos = {}
    elif not isinstance(repos, dict):
        raise ConfigError(
            f"config.yml key 'repos' must be a mapping of folder -> repo, got {type(repos).__name__}")
    cfg["repos"] = repos
    scalar_shape_keys = set()
    # Normalize string-shape entries to dict shape
    for folder, val in list(cfg["repos"].items()):
        if isinstance(val, str):
            scalar_shape_keys.add(folder)
            cfg["repos"][folder] = {"github": val, "local": None}
        elif isinstance(val, dict):
            val.setdefault("local", None)
            if "github" not in val:
                raise ConfigError(f"repo '{folder}' missing 'github' key")
        else:
            raise ConfigError(f"repo '{folder}' must be string or dict, got {type(val).__name__}")
    cfg["_scalar_shape_keys"] = scalar_shape_keys
    return cfg


def is_valid_git_repo(path: Path) -> bool:
    """Return True if path is a directory that contains a .git entry."""
    p = Path(path)
    return p.is_dir() and (p / ".git").exists()


def notes_vcs_auto_commit(cfg: dict) -> bool:
    """True when opt-in local VCS auto-commit is enabled for notes_root (#103).

    Reads `notes_vcs.auto_commit` from config. Absent/malformed → False
    (opt-in: the feature does nothing until the user turns it on, e.g. via
    `work-plan notes-vcs init` or `notes-vcs enable`).
    """
    block = cfg.get("notes_vcs")
    return bool(block.get("auto_commit")) if isinstance(block, dict) else False


def resolve_github_for_folder(folder_name: str, cfg: dict) -> Optional[str]:
    entry = cfg.get("repos", {}).get(folder_name)
    return entry.get("github") if entry else None


def resolve_local_path_for_folder(folder_name: str, cfg: dict) -> Optional[Path]:
    entry = cfg.get("repos", {}).get(folder_name)
    if not entry or not entry.get("local"):
        return None
    return Path(entry["local"]).expanduser()


def write_repo_field(key: str, updates: dict, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Merge `updates` into `repos.<key>` in config.yml via an opaque-env `yq`
    merge — the same mechanic `init_repo.py::_update_existing` already used
    (extracted here so `doctor` and `init-repo` share one implementation).

    `updates` values travel as JSON through an env var, never interpolated
    into the yq expression, so they can't break out of the merge. `key` is
    interpolated directly into the yq path — callers MUST validate it against
    a safe-key pattern (e.g. `^[a-z][a-z0-9-]*$`) before calling this; this
    function does not re-validate, matching `_update_existing`'s existing
    contract (its caller already validates via `init-repo`'s own regex check).

    An entry written in the scalar shorthand (`foo: org/foo`) is migrated to
    mapping form (`foo: {github: org/foo}`) as part of the merge: `yq` cannot
    multiply a string with a map (#440). The scalar's trailing comment is moved
    onto the new `github:` line, because yq would otherwise re-attach it to the
    NEXT key. The merged entry is written in block style, not yq's flow default.
    All of it is one yq invocation.

    Raises `subprocess.CalledProcessError` on any yq failure. Callers must catch
    this and treat it as "entry not fixable this way", not crash the whole command.
    """
    env = {**os.environ, "WP_REPO_UPDATES": json.dumps(updates)}
    entry = f".repos.{key}"
    scalar = f"({entry} | select(tag == \"!!str\"))"
    maps = f"({entry} | .. | select(kind == \"map\"))"
    yq_expr = (
        # the scalar's line comment ("" when the entry is not a scalar), then clear
        # every comment on the scalar so yq cannot re-attach them to the next key
        f"(({entry} | select(tag == \"!!str\") | line_comment) // \"\") as $c "
        f"| {scalar} head_comment = \"\" | {scalar} line_comment = \"\" "
        f"| {scalar} foot_comment = \"\" "
        # wrap a scalar as {github: <scalar>}, else keep the entry (or start {}), then merge
        f"| {entry} = ((({entry} | select(tag == \"!!str\")) as $s | {{\"github\": $s}}) "
        f"// {entry} // {{}}) * env(WP_REPO_UPDATES) "
        f"| with({entry} | select($c != \"\"); .github line_comment = $c) "
        f"| {maps} style=\"\" | ({maps} | .[] | key) style=\"\""
    )
    subprocess.run(
        ["yq", "-i", yq_expr, str(path)],
        check=True, capture_output=True, text=True, env=env,
    )