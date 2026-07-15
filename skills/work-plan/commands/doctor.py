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
from pathlib import Path

from lib.config import load_config, ConfigError, is_valid_git_repo
from lib.cwd_repo import _git, _normalize_remote_url
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

_HOST_RE = re.compile(r"^[\w.+-]+@([\w.-]+):|^[\w.+-]+://(?:[^/@]+@)?([^/]+)/")


def _remote_host(url: str) -> "str | None":
    """Extract the host from a git remote URL, preserving it (unlike
    `_normalize_remote_url`, which discards the host on purpose for its own
    slug-comparison use case). Handles the same two forms `_normalize_remote_url`
    does: scp-like and scheme://. Returns None if unparseable."""
    if not url:
        return None
    m = _HOST_RE.match(url.strip())
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").lower() or None


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
    process-level timeout of its own). Not-yet-started jobs are cancelled at
    the deadline so this function's own return time stays bounded by roughly
    SCAN_DEADLINE + GH_TIMEOUT regardless of repo count — already-running
    calls (up to MAX_GH_WORKERS of them) can't be cancelled mid-subprocess,
    but that residual is count-independent, not the defect this fixes.
    """
    result = {}
    if not repos:
        return result
    pool = ThreadPoolExecutor(max_workers=min(MAX_GH_WORKERS, len(repos)))
    try:
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
            fut.cancel()
            result[key] = {"canonical": repos[key]["github"], "unverified": True}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
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


def _step2_findings(repos: dict, canonical: "dict | None" = None) -> list:
    canonical = canonical or {}
    findings = []
    for key, entry in repos.items():
        local = entry.get("local")
        if not local:
            continue
        p = Path(local).expanduser()
        if not p.is_absolute():
            findings.append(_finding(
                "local_path_relative", key=key,
                message=f"'{key}'.local is a relative path ('{local}') — "
                        "results would depend on the current working directory; "
                        "use an absolute path",
            ))
            continue
        if not p.exists():
            findings.append(_finding(
                "missing_local", key=key,
                message=f"'{key}'.local ('{local}') does not exist on disk",
            ))
            continue
        if not is_valid_git_repo(p):
            findings.append(_finding(
                "local_not_git", key=key,
                message=f"'{key}'.local ('{local}') has no .git entry",
            ))
            continue
        proc = _git(p, "remote", "get-url", "origin")
        if proc is None or proc.returncode != 0 or not proc.stdout.strip():
            findings.append(_finding(
                "local_remote_missing", key=key,
                message=f"'{key}'.local ('{local}') has no resolvable 'origin' remote",
            ))
            continue
        raw_url = proc.stdout.strip()
        host = _remote_host(raw_url)
        if host != "github.com":
            findings.append(_finding(
                "local_remote_mismatch", key=key,
                message=f"'{key}'.local's origin ('{raw_url}') is a non-GitHub host "
                        f"({host or 'unrecognized'}) — not compared to a slug",
            ))
            continue
        slug = _normalize_remote_url(raw_url)
        info = canonical.get(key)
        expected = info["canonical"] if info else entry["github"]
        if slug and slug != expected.lower():
            findings.append(_finding(
                "local_remote_mismatch", key=key, fixable=False,
                message=f"'{key}'.local's origin ('{slug}') differs from the "
                        f"configured/canonical slug ('{expected}') — could be a "
                        "legitimate fork or mirror",
            ))
    return findings


def _notes_root_status(cfg: dict):
    """Returns (walkable: bool, finding_or_None). walkable is False when either
    notes_root_invalid or notes_root_missing fired — Step 4 must not walk."""
    raw = cfg.get("notes_root")
    if not isinstance(raw, str) or not raw.strip():
        return False, _finding("notes_root_invalid",
                                message="notes_root is blank or not a string")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        return False, _finding("notes_root_invalid",
                                message=f"notes_root ('{raw}') is not an absolute path")
    resolved = p.resolve()
    if resolved == resolved.anchor or str(resolved) == resolved.anchor:
        return False, _finding("notes_root_invalid",
                                message=f"notes_root ('{raw}') resolves to a bare filesystem root")
    if not resolved.is_dir():
        return False, _finding("notes_root_missing",
                                message=f"notes_root ('{raw}') does not exist or is not a directory")
    return True, None


def _step3_findings(repos: dict, canonical: dict, cfg: dict) -> list:
    findings = []
    by_local = {}
    by_slug = {}
    for key, entry in repos.items():
        local = entry.get("local")
        if local:
            resolved = str(Path(local).expanduser().resolve())
            by_local.setdefault(resolved, []).append(key)
        info = canonical.get(key)
        slug = (info["canonical"] if info else entry["github"]).lower()
        by_slug.setdefault(slug, []).append(key)
    for resolved, keys in by_local.items():
        if len(keys) > 1:
            for key in keys:
                findings.append(_finding(
                    "duplicate_local", key=key,
                    message=f"'{key}' shares local path '{resolved}' with {[k for k in keys if k != key]}",
                ))
    for slug, keys in by_slug.items():
        if len(keys) > 1:
            for key in keys:
                findings.append(_finding(
                    "duplicate_github", key=key,
                    message=f"'{key}' shares canonical slug '{slug}' with {[k for k in keys if k != key]}",
                ))
    walkable, notes_finding = _notes_root_status(cfg)
    if notes_finding:
        findings.append(notes_finding)
    return findings


def _scan(cfg, repos):
    """Steps 1-4. Step 4 is stubbed until Task 8 lands."""
    canonical = _resolve_canonical_slugs(repos)
    findings = _step1_findings(repos, canonical, cfg.get("_scalar_shape_keys"))
    findings += _step2_findings(repos, canonical)
    findings += _step3_findings(repos, canonical, cfg)
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
