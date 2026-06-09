"""Discover tracks under notes_root and shared .work-plan/ dirs."""
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib.frontmatter import parse_file
from lib.config import (
    resolve_github_for_folder,
    resolve_local_path_for_folder,
    is_valid_git_repo,
)


@dataclass
class Track:
    path: Path
    name: str
    has_frontmatter: bool
    needs_init: bool
    needs_filing: bool
    repo: Optional[str] = None
    folder: Optional[str] = None
    local_path: Optional[Path] = None
    meta: dict = field(default_factory=dict)
    body: str = ""
    tier: Optional[str] = None


def discover_tracks(cfg: dict) -> list:
    """Walk notes_root for active (non-archived) .md files, then union with
    shared tracks from each configured repo's .work-plan/ directory.
    Shared wins on (repo, name) collisions.
    """
    private = _discover_private_tracks(cfg, include_archive=False)
    shared = _discover_shared_tracks(cfg, include_archive=False)

    # Build lookup for shared tracks keyed by (repo, name)
    shared_keys: dict = {}
    for t in shared:
        key = (t.repo, t.name)
        shared_keys[key] = t

    # Merge: private tracks that have no colliding shared track are kept
    merged = list(shared)
    for t in private:
        key = (t.repo, t.name)
        if key in shared_keys:
            print(
                f"WARN: track {t.name!r} (repo={t.repo!r}) exists in both shared"
                f" ({shared_keys[key].path}) and private ({t.path}); using shared.",
            )
        else:
            merged.append(t)

    return merged


def filter_tracks_by_repo(tracks: list, key: str) -> list:
    """Filter tracks by repo. Matches the config-key folder name OR the
    `org/repo` GitHub slug, so users can pass either. Case-insensitive."""
    k = key.lower()
    return [t for t in tracks
            if (t.folder and t.folder.lower() == k)
            or (t.repo and t.repo.lower() == k)]


def find_track_by_name(name: str, tracks: list,
                       *, active_only: bool = False) -> Optional["Track"]:
    """Find a single Track matching `name` (filename stem OR frontmatter `track`).

    If active_only=True, only considers tracks with status active/in-progress/blocked.
    Returns the single match or None. Used by every command that takes a track arg.
    """
    candidates = tracks
    if active_only:
        candidates = [t for t in candidates if t.has_frontmatter
                      and t.meta.get("status") in ("active", "in-progress", "blocked")]
    matching = [t for t in candidates if t.has_frontmatter
                and (t.name == name or t.meta.get("track") == name)]
    return matching[0] if len(matching) == 1 else None


def discover_archived_tracks(cfg: dict) -> list:
    """Walk notes_root for archived .md files, and also scan each repo's
    .work-plan/archive/ for shared archived tracks."""
    notes_root = Path(cfg["notes_root"]).expanduser()
    out = []
    if notes_root.exists():
        for md_path in sorted(notes_root.rglob("*.md")):
            if "archive" not in md_path.parts:
                continue
            if md_path.name.startswith((".", "_")):
                continue
            out.append(_build_track(md_path, notes_root, cfg))

    # Also scan shared repos' .work-plan/archive/
    out.extend(_discover_shared_tracks(cfg, include_archive=True,
                                        archive_only=True))
    return out


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _discover_private_tracks(cfg: dict, include_archive: bool) -> list:
    notes_root = Path(cfg["notes_root"]).expanduser()
    if not notes_root.exists():
        return []
    return _walk(notes_root, cfg, include_archive=include_archive)


def _discover_shared_tracks(cfg: dict, include_archive: bool = False,
                             archive_only: bool = False) -> list:
    """Walk each configured repo's local clone .work-plan/ directory."""
    out = []
    repos = cfg.get("repos", {})
    for folder_key, entry in repos.items():
        if not entry or not entry.get("local"):
            continue
        local_path = Path(entry["local"]).expanduser()
        if not is_valid_git_repo(local_path):
            continue
        github_repo = entry.get("github")
        notes_dir = local_path / ".work-plan"
        if not notes_dir.is_dir():
            continue
        for md_path in sorted(notes_dir.rglob("*.md")):
            # Skip dotfiles and README
            if md_path.name.startswith(".") or md_path.name == "README.md":
                continue
            in_archive = "archive" in md_path.relative_to(notes_dir).parts
            if archive_only and not in_archive:
                continue
            if not include_archive and in_archive:
                continue
            out.append(_build_shared_track(
                md_path, notes_dir, folder_key, github_repo, local_path, cfg
            ))
    return out


def _build_shared_track(md_path: Path, notes_dir: Path, folder_key: str,
                         github_repo: Optional[str], local_path: Path,
                         cfg: dict) -> "Track":
    """Build a Track from a shared .work-plan/ markdown file."""
    meta, body = parse_file(md_path)
    has_fm = bool(meta)

    # Single-owner rule: if frontmatter disagrees with folder config, warn and
    # use the folder's configured github repo (never the frontmatter value).
    if has_fm and meta.get("github", {}).get("repo"):
        fm_repo = meta["github"]["repo"]
        if fm_repo != github_repo:
            print(
                f"WARN: shared track {md_path.name!r} frontmatter github.repo"
                f" differs from folder config; using folder {github_repo!r}",
                file=sys.stderr,
            )

    rel = md_path.relative_to(notes_dir)
    in_archive = "archive" in rel.parts

    return Track(
        path=md_path,
        name=md_path.stem,
        has_frontmatter=has_fm,
        needs_init=False,
        needs_filing=False,
        repo=github_repo,
        folder=folder_key,
        local_path=local_path,
        meta=meta,
        body=body,
        tier="shared",
    )


def _walk(notes_root: Path, cfg: dict, include_archive: bool) -> list:
    out = []
    for md_path in sorted(notes_root.rglob("*.md")):
        if not include_archive and "archive" in md_path.parts:
            continue
        if md_path.name.startswith((".", "_")):
            continue
        out.append(_build_track(md_path, notes_root, cfg))
    return out


def _build_track(md_path: Path, notes_root: Path, cfg: dict) -> "Track":
    meta, body = parse_file(md_path)
    has_fm = bool(meta)
    rel = md_path.relative_to(notes_root)
    in_subfolder = len(rel.parts) > 1
    folder_name = rel.parts[0] if in_subfolder else None

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
        folder=folder_name,
        local_path=local,
        meta=meta,
        body=body,
        tier="private",
    )
