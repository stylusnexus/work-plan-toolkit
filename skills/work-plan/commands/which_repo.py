"""which-repo — resolve the current directory to a configured repo.

Prints the matched repo's config key + GitHub slug, or reports no match. The
VS Code viewer spawns this with cwd set to the workspace folder to auto-focus its
repo lens (#357); `brief` calls the underlying resolver directly for cwd
auto-scope (#358). Read-only — never mutates anything.

Exit codes (human form): 0 on a match, 1 on no match — so a shell caller can
gate on it. The `--json` form always exits 0 and prints a `{"key": ...}` payload
(key is null on no match) for the viewer to parse.
"""
import json
import os

from lib.config import load_config, ConfigError
from lib.cwd_repo import resolve_repo_for_dir
from lib.prompts import parse_flags


def run(args: list) -> int:
    flags, _ = parse_flags(args, {"--json"})
    want_json = bool(flags.get("--json"))

    try:
        cfg = load_config()
    except ConfigError as e:
        if want_json:
            print(json.dumps({"key": None}))
            return 0
        print(f"ERROR: {e}")
        return 1

    match = resolve_repo_for_dir(cfg, os.getcwd())

    if want_json:
        if match:
            print(json.dumps({
                "key": match["key"],
                "github": match.get("github"),
                "matched_by": match["matched_by"],
            }))
        else:
            print(json.dumps({"key": None}))
        return 0

    if match:
        how = "local clone path" if match["matched_by"] == "local" else "git remote"
        print(f"Resolved to repo '{match['key']}' (matched by {how}).")
        return 0

    print("No configured repo matches the current directory.")
    return 1
