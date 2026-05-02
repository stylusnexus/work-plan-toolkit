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
    folder: Optional[str] = None
    local_path: Optional[Path] = None
    meta: dict = field(default_factory=dict)
    body: str = ""


def discover_tracks(cfg: dict) -> list[Track]:
    """Walk notes_root for active (non-archived) .md files."""
    notes_root = Path(cfg["notes_root"])
    if not notes_root.exists():
        return []
    return _walk(notes_root, cfg, include_archive=False)


def filter_tracks_by_repo(tracks: list[Track], key: str) -> list[Track]:
    """Filter tracks by repo. Matches the config-key folder name OR the
    `org/repo` GitHub slug, so users can pass either. Case-insensitive."""
    k = key.lower()
    return [t for t in tracks
            if (t.folder and t.folder.lower() == k)
            or (t.repo and t.repo.lower() == k)]


def find_track_by_name(name: str, tracks: list[Track],
                       *, active_only: bool = False) -> Optional[Track]:
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
    )
