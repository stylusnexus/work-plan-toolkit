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

from lib.config import (
    load_config, ConfigError, is_valid_git_repo,
    DEFAULT_CONFIG_PATH, write_repo_field, notes_vcs_auto_commit,
)
from lib.cwd_repo import _git, _normalize_remote_url
from lib.frontmatter import parse_file, write_file
from lib.github_state import repo_full_name
from lib.notes_vcs import dirty_paths_checked, auto_commit
from lib.prompts import parse_flags
from lib.tracks import iter_private_track_paths

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
    does: scp-like and scheme://. An explicit `:<port>` on the scheme form
    (e.g. `https://github.com:8080/org/repo.git`) is stripped so a genuine
    github.com remote isn't misreported as non-GitHub just because it names a
    port; the scp-like form's captured group can never contain a colon (its
    own colon is the path separator, outside the capture), so the split is a
    no-op there. Returns None if unparseable."""
    if not url:
        return None
    m = _HOST_RE.match(url.strip())
    if not m:
        return None
    host = (m.group(1) or m.group(2) or "").lower()
    return host.split(":", 1)[0] or None


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
    if str(resolved) == resolved.anchor:
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


def _step4_findings(cfg: dict, repos: dict, canonical: dict, walkable: bool) -> list:
    if not walkable:
        return []
    notes_root = Path(cfg["notes_root"]).expanduser()
    findings = []

    # Walk once; reuse for both the orphaned-folder pass and the per-track pass.
    track_paths = iter_private_track_paths(notes_root, include_archive=True)
    folders_with_tracks = {
        p.relative_to(notes_root).parts[0]
        for p in track_paths
        if len(p.relative_to(notes_root).parts) > 1
    }

    for child in sorted(notes_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name not in folders_with_tracks:
            continue
        if child.name not in repos:
            findings.append(_finding(
                "orphaned_folder", folder=child.name,
                message=f"notes_root folder '{child.name}' has no matching repos.<key>",
            ))

    for md_path in track_paths:
        rel = md_path.relative_to(notes_root)
        folder = rel.parts[0] if len(rel.parts) > 1 else None
        track_name = md_path.name
        try:
            meta, _body = parse_file(md_path)
        except Exception as e:
            findings.append(_finding(
                "track_unreadable", folder=folder, track=track_name,
                message=f"could not parse frontmatter: {e}",
            ))
            continue
        if not isinstance(meta, dict):
            findings.append(_finding(
                "track_unreadable", folder=folder, track=track_name,
                message="frontmatter root is not a mapping",
            ))
            continue
        github_block = meta.get("github")
        if github_block is None:
            continue
        if not isinstance(github_block, dict):
            findings.append(_finding(
                "track_unreadable", folder=folder, track=track_name,
                message="frontmatter 'github' is not a mapping",
            ))
            continue
        repo_value = github_block.get("repo")
        if repo_value is None:
            continue
        if not isinstance(repo_value, str):
            findings.append(_finding(
                "track_unreadable", folder=folder, track=track_name,
                message="frontmatter 'github.repo' is not a string",
            ))
            continue
        if folder is None or folder not in repos:
            continue
        info = canonical.get(folder)
        if info is None or info["unverified"]:
            continue
        expected = info["canonical"]
        if repo_value.lower() != expected.lower():
            findings.append(_finding(
                "stale_frontmatter", folder=folder, track=track_name, fixable=True,
                message=f"track '{track_name}' frontmatter github.repo is '{repo_value}', "
                        f"folder '{folder}' canonical slug is '{expected}'",
                old=repo_value, new=expected,
            ))
    return findings


def _scan(cfg, repos):
    """Steps 1-4 — the full scan pipeline. Re-run verbatim after --fix applies
    corrections (see `run()`), so a fixed finding must actually disappear."""
    canonical = _resolve_canonical_slugs(repos)
    findings = _step1_findings(repos, canonical, cfg.get("_scalar_shape_keys"))
    findings += _step2_findings(repos, canonical)
    findings += _step3_findings(repos, canonical, cfg)
    walkable, _ = _notes_root_status(cfg)
    findings += _step4_findings(cfg, repos, canonical, walkable)
    return findings


def _apply_config_fixes(findings: list) -> list:
    """Applies every fixable github_rename_detected finding to config.yml.
    Returns the attempt ledger (one entry per attempt, in the order given)."""
    ledger = []
    for f in findings:
        if f["type"] != "github_rename_detected" or not f["fixable"]:
            continue
        entry = {"type": f["type"], "key": f["key"], "folder": None, "track": None,
                  "old": f["old"], "new": f["new"], "fixed": False, "error": None}
        try:
            write_repo_field(f["key"], {"github": f["new"]}, path=DEFAULT_CONFIG_PATH)
            entry["fixed"] = True
        except subprocess.CalledProcessError as e:
            entry["error"] = (e.stderr or str(e)).strip()
        ledger.append(entry)
    return ledger


def _apply_frontmatter_fixes(notes_root: Path, findings: list, auto_commit_enabled: bool):
    """Applies every fixable stale_frontmatter finding, subject to the
    dirty-file policy. Returns (ledger, skipped_due_to_unknown_dirty_state).
    """
    ok_before, dirty_before = dirty_paths_checked(notes_root)
    if not ok_before:
        return [], True  # fail closed: no writes at all this run

    ledger = []
    changed_paths = []
    for f in findings:
        if f["type"] != "stale_frontmatter" or not f["fixable"]:
            continue
        rel = f"{f['folder']}/{f['track']}"
        entry = {"type": f["type"], "key": None, "folder": f["folder"], "track": f["track"],
                  "old": f["old"], "new": f["new"], "fixed": False, "error": None}
        if rel in dirty_before:
            entry["error"] = "file has uncommitted changes; commit/stash first or fix by hand"
            ledger.append(entry)
            continue
        md_path = notes_root / f["folder"] / f["track"]
        try:
            meta, body = parse_file(md_path)
            # Defensive re-check: `folder`/`track` on a finding lose any
            # intermediate path segment (e.g. `known/archive/old.md` reports
            # folder="known", track="old.md"), so a same-named file elsewhere
            # under `folder` (archived vs. not) could otherwise collide here.
            # Confirm the file we resolved still carries the OLD value this
            # finding was raised against before writing — a mismatch means
            # we resolved the wrong file, not that the finding is stale.
            current = meta.get("github") if isinstance(meta, dict) else None
            current_repo = current.get("repo") if isinstance(current, dict) else None
            if current_repo != f["old"]:
                entry["error"] = (
                    f"resolved path {md_path} does not carry the expected old "
                    f"value ({f['old']!r}, found {current_repo!r}) — refusing "
                    "to write; likely a nested/archived track name collision"
                )
                ledger.append(entry)
                continue
            meta["github"]["repo"] = f["new"]
            write_file(md_path, meta, body)
            entry["fixed"] = True
            changed_paths.append(rel)
        except Exception as e:
            entry["error"] = str(e)
        ledger.append(entry)

    if auto_commit_enabled and changed_paths:
        ok_after, dirty_after = dirty_paths_checked(notes_root)
        if ok_after:
            delta = sorted(set(dirty_after) - dirty_before)
            if delta:
                auto_commit(notes_root, "doctor: fix stale repo identity in track frontmatter",
                            paths=delta)
    return ledger, False


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
    attempts = []

    if want_fix:
        attempts += _apply_config_fixes(findings)
        notes_root_raw = cfg.get("notes_root")
        walkable, _ = _notes_root_status(cfg)
        if walkable:
            notes_root = Path(notes_root_raw).expanduser()
            auto_enabled = notes_vcs_auto_commit(cfg)
            fm_ledger, snapshot_failed = _apply_frontmatter_fixes(notes_root, findings, auto_enabled)
            attempts += fm_ledger
            if snapshot_failed:
                print("WARN: notes-vcs status check failed — cannot safely determine "
                      "which files are already dirty; no frontmatter fixes applied this run.",
                      file=sys.stderr)

        # Mandatory post-fix rescan, from disk.
        cfg2, fatal2 = _load_config_safely()
        if fatal2 is not None:
            if want_json:
                _print_json({"fatal": f"{fatal2} (residual state indeterminate after --fix)",
                              "attempts": attempts, "findings": []})
                return 0
            print(f"ERROR: post-fix rescan failed ({fatal2}) — residual state indeterminate.")
            return 1
        repos2, shape_findings2 = _validate_repo_field_shapes(cfg2)
        findings = list(shape_findings2) + _scan(cfg2, repos2)

    if want_json:
        _print_json({"attempts": attempts, "findings": findings})
        return 0

    for a in attempts:
        thing = a["key"] or f"{a['folder']}/{a['track']}"
        if a["fixed"]:
            print(f"FIXED: {thing}: {a['old']} -> {a['new']}")
        else:
            print(f"ERROR fixing {thing}: {a['error']}")
    if not findings:
        if attempts:
            print(f"{sum(1 for a in attempts if a['fixed'])} fixed, all clear.")
        else:
            print("No drift found.")
        return 0
    for f in findings:
        prefix = "WARN (unfixed)" if attempts else "WARN"
        print(f"{prefix}: {f['message']}")
    print(f"{len(findings)} issue(s) found.")
    return 1
