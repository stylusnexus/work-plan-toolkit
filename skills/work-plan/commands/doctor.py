"""doctor subcommand — detect (and, for a safe subset, fix) drift between
config.yml, local git clones, GitHub, and notes_root track frontmatter.

See docs/superpowers/specs/2026-07-15-config-drift-doctor-design.md (revision
5) for the full design and the four Codex /spec-review passes that shaped it.
Read-only by default; --fix applies the two mechanically-safe corrections
(a GitHub-confirmed rename, a stale track frontmatter slug) and always
re-scans from disk afterward before deciding the exit code.
"""
import json
import subprocess
import sys

from lib.config import load_config, ConfigError
from lib.prompts import parse_flags

_FATAL_EXCEPTIONS = (
    ConfigError,
    FileNotFoundError,
    subprocess.CalledProcessError,
    json.JSONDecodeError,
    OSError,
    AttributeError,
    UnicodeDecodeError,
)


def _finding(type_, *, key=None, folder=None, track=None, message,
             fixable=False, unverified=False, old=None, new=None):
    return {
        "type": type_, "key": key, "folder": folder, "track": track,
        "message": message, "fixable": fixable, "unverified": unverified,
        "old": old, "new": new,
    }


def _load_config_safely():
    """Returns (cfg, fatal_message) — exactly one is None."""
    try:
        return load_config(), None
    except _FATAL_EXCEPTIONS as e:
        return None, str(e)


def _validate_repo_field_shapes(cfg):
    """Excludes any `repos` entry whose github/local field has the wrong type,
    reporting `repo_entry_malformed` for each. Returns (valid_repos, findings)
    — valid_repos is a NEW dict, cfg["repos"] is left untouched.
    """
    valid = {}
    findings = []
    for key, entry in (cfg.get("repos") or {}).items():
        github = entry.get("github")
        local = entry.get("local")
        if not isinstance(github, str):
            findings.append(_finding(
                "repo_entry_malformed", key=key,
                message=f"'github' must be a string, got {type(github).__name__}",
            ))
            continue
        if local is not None and not isinstance(local, str):
            findings.append(_finding(
                "repo_entry_malformed", key=key,
                message=f"'local' must be a string, got {type(local).__name__}",
            ))
            continue
        valid[key] = entry
    return valid, findings


def _scan(cfg, repos):
    """Steps 1-4. Stubbed in this task — returns no additional findings.
    Filled in by Tasks 6-8; this task only wires Step 0 through to output."""
    return []


def _print_json(payload):
    print(json.dumps(payload))


def run(args: list) -> int:
    flags, _ = parse_flags(args, {"--json", "--fix"})
    want_json = bool(flags.get("--json"))
    want_fix = bool(flags.get("--fix"))

    cfg, fatal = _load_config_safely()
    if fatal is not None:
        if want_json:
            _print_json({"fatal": fatal, "attempts": [], "findings": []})
            return 0
        print(f"ERROR: work-plan config could not be loaded ({fatal}) — doctor cannot run.")
        return 1

    repos, shape_findings = _validate_repo_field_shapes(cfg)
    findings = list(shape_findings) + _scan(cfg, repos)
    attempts = []  # --fix wiring lands in Task 9

    if want_json:
        _print_json({"attempts": attempts, "findings": findings})
        return 0

    if not findings:
        print("No drift found.")
        return 0
    for f in findings:
        print(f"WARN: {f['message']}")
    print(f"{len(findings)} issue(s) found.")
    return 1
