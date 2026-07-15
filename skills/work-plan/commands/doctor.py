"""doctor subcommand — detect (and, for a safe subset, fix) drift between
config.yml, local git clones, GitHub, and notes_root track frontmatter.

See docs/superpowers/specs/2026-07-15-config-drift-doctor-design.md (revision
5) for the full design and the four Codex /spec-review passes that shaped it.
Read-only by default; --fix applies the two mechanically-safe corrections
(a GitHub-confirmed rename, a stale track frontmatter slug) and always
re-scans from disk afterward before deciding the exit code.
"""
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, wait

from lib.config import load_config, ConfigError
from lib.github_state import repo_full_name
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

SAFE_KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SCAN_DEADLINE = 60  # seconds, wall-clock budget for Step 1 regardless of repo count
MAX_GH_WORKERS = 4


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


def _resolve_canonical_slugs(repos: dict) -> dict:
    """Step 1: one gh-confirmed canonical slug per repo, resolved concurrently
    with an overall wall-clock deadline so a large repo count can't stall the
    whole scan (or the VS Code extension's activation call, which has no
    process-level timeout of its own).
    """
    result = {}
    if not repos:
        return result
    with ThreadPoolExecutor(max_workers=min(MAX_GH_WORKERS, len(repos))) as pool:
        futures = {pool.submit(repo_full_name, entry["github"]): key
                   for key, entry in repos.items()}
        done, not_done = wait(futures, timeout=SCAN_DEADLINE)
        for fut in done:
            key = futures[fut]
            full_name = fut.result()
            configured = repos[key]["github"]
            if full_name is None:
                result[key] = {"canonical": configured, "unverified": True}
            else:
                result[key] = {"canonical": full_name, "unverified": False}
        for fut in not_done:
            key = futures[fut]
            result[key] = {"canonical": repos[key]["github"], "unverified": True}
    return result


def _step1_findings(repos: dict, canonical: dict, scalar_shape_keys=None) -> list:
    scalar_shape_keys = scalar_shape_keys or set()
    findings = []
    for key, entry in repos.items():
        configured = entry["github"]
        info = canonical[key]
        if info["unverified"]:
            findings.append(_finding(
                "github_repo_unreachable", key=key, unverified=True,
                message=f"could not confirm GitHub identity for '{configured}' "
                        "(404, no access, rate-limited, offline, or scan timed out)",
            ))
            continue
        if info["canonical"].lower() == configured.lower():
            continue
        fixable = True
        reason = None
        if not SAFE_KEY_RE.match(key):
            fixable = False
            reason = "config key contains characters unsafe for automatic YAML updates"
        elif key in scalar_shape_keys:
            fixable = False
            reason = (f"repo entry '{key}' uses the scalar shorthand form — convert "
                       f"'{key}: \"{configured}\"' to '{key}: {{github: \"{configured}\"}}' "
                       "by hand in config.yml, then re-run doctor --fix")
        message = (f"'{key}' GitHub repo renamed: configured as '{configured}', "
                   f"GitHub now reports '{info['canonical']}'")
        if reason:
            message += f" — {reason}"
        findings.append(_finding(
            "github_rename_detected", key=key, message=message, fixable=fixable,
            old=configured, new=info["canonical"],
        ))
    return findings


def _scan(cfg, repos):
    """Steps 1-4. Steps 2-4 are stubbed until Tasks 7-8 land."""
    canonical = _resolve_canonical_slugs(repos)
    findings = _step1_findings(repos, canonical, cfg.get("_scalar_shape_keys"))
    return findings


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
