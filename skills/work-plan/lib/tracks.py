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
from lib.git_state import parse_iso_timestamp

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def priority_rank(meta: dict) -> int:
    """Rank a track's launch_priority for ascending sort: P0<P1<P2<P3<anything.

    Unknown / missing values (e.g. "—" or absent) sort after all known ranks.
    """
    return _PRIORITY_RANK.get(meta.get("launch_priority"), len(_PRIORITY_RANK))


def recency_sort_key(meta: dict) -> float:
    """Sort key for last_touched recency (most recent first when sorted ascending).

    Returns the negative POSIX timestamp so that a plain ascending sort puts the
    most-recently-touched track first. Tracks with no (or unparseable)
    last_touched return +inf, sorting them LAST.
    """
    raw = meta.get("last_touched")
    if not raw:
        return float("inf")
    try:
        return -parse_iso_timestamp(raw).timestamp()
    except (ValueError, TypeError):
        return float("inf")


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


def discover_tracks(cfg: dict) -> list[Track]:
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
                file=sys.stderr,
            )
        else:
            merged.append(t)

    return merged


def filter_tracks_by_repo(tracks: list[Track], key: str) -> list[Track]:
    """Filter tracks by repo. Matches the config-key folder name OR the
    `org/repo` GitHub slug, so users can pass either. Case-insensitive."""
    k = key.lower()
    return [t for t in tracks
            if (t.folder and t.folder.lower() == k)
            or (t.repo and t.repo.lower() == k)]


class AmbiguousTrackError(Exception):
    """Raised when a track name matches more than one track across repos."""

    def __init__(self, name: str, candidates: list[Track]):
        self.name = name
        self.candidates = candidates
        repos = [f"  {t.name} (repo: {t.repo or t.folder!r})" for t in candidates]
        super().__init__(
            f"Track {name!r} is ambiguous — found in {len(candidates)} repos:\n"
            + "\n".join(repos)
            + f"\nUse --repo=<key> or '{name}@<repo>' to disambiguate."
        )


def parse_track_repo_arg(arg: str) -> tuple:
    """Split 'trackname@repokey' into (trackname, repokey); return (arg, None) if no @."""
    if "@" in arg:
        name, _, repo = arg.rpartition("@")
        return (name, repo) if name else (arg, None)
    return (arg, None)


def find_track_by_name(
    name: str, tracks: list[Track],
    *, active_only: bool = False, repo: Optional[str] = None
) -> Optional[Track]:
    """Find a single Track matching `name` (filename stem OR frontmatter `track`).

    If repo is given, first filter to tracks matching that repo (folder key or
    GitHub slug, case-insensitive). Then find a single name match.

    If active_only=True, only considers tracks with status active/in-progress/blocked.

    Returns the single match or None (0 matches).
    Raises AmbiguousTrackError if 2+ matches remain after filtering.
    """
    candidates = tracks
    if repo:
        candidates = filter_tracks_by_repo(candidates, repo)
    if active_only:
        candidates = [t for t in candidates if t.has_frontmatter
                      and t.meta.get("status") in ("active", "in-progress", "blocked")]
    matching = [t for t in candidates if t.has_frontmatter
                and (t.name == name or t.meta.get("track") == name)]
    if len(matching) <= 1:
        return matching[0] if matching else None
    raise AmbiguousTrackError(name, matching)


def discover_archived_tracks(cfg: dict) -> list[Track]:
    """Walk notes_root for archived .md files, and also scan each repo's
    .work-plan/archive/ for shared archived tracks.

    Deduplicates by (repo, name): shared wins over private, same as
    discover_tracks for active tracks.
    """
    notes_root = Path(cfg["notes_root"]).expanduser()
    private_archived: list[Track] = []
    if notes_root.exists():
        for md_path in sorted(notes_root.rglob("*.md")):
            if "archive" not in md_path.parts:
                continue
            # '-' prefix rejected so a `--repo.md` file can't become a `--repo`
            # track that the CLI misparses as a flag (#194).
            if md_path.name.startswith((".", "_", "-")):
                continue
            private_archived.append(_build_track(md_path, notes_root, cfg))

    shared_archived = _discover_shared_tracks(cfg, include_archive=True,
                                              archive_only=True)

    # Build lookup for shared tracks keyed by (repo, name)
    shared_keys: dict = {}
    for t in shared_archived:
        key = (t.repo, t.name)
        shared_keys[key] = t

    # Merge: shared wins on collision
    merged = list(shared_archived)
    for t in private_archived:
        key = (t.repo, t.name)
        if key in shared_keys:
            print(
                f"WARN: archived track {t.name!r} (repo={t.repo!r}) exists in"
                f" both shared ({shared_keys[key].path}) and private"
                f" ({t.path}); using shared.",
                file=sys.stderr,
            )
        else:
            merged.append(t)

    return merged


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _discover_private_tracks(cfg: dict, include_archive: bool) -> list[Track]:
    notes_root = Path(cfg["notes_root"]).expanduser()
    if not notes_root.exists():
        return []
    return _walk(notes_root, cfg, include_archive=include_archive)


def _discover_shared_tracks(cfg: dict, include_archive: bool = False,
                             archive_only: bool = False) -> list[Track]:
    """Walk each configured repo's local clone .work-plan/ directory."""
    out: list[Track] = []
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
            # Skip dotfiles, README, and dash-led names (a `--repo.md` file
            # would otherwise become a `--repo` track the CLI misparses, #194).
            if md_path.name.startswith((".", "-")) or md_path.name == "README.md":
                continue
            in_archive = "archive" in md_path.relative_to(notes_dir).parts
            if archive_only and not in_archive:
                continue
            if not include_archive and in_archive:
                continue
            out.append(_build_shared_track(
                md_path, folder_key, github_repo, local_path
            ))
    return out


def _build_shared_track(md_path: Path, folder_key: str,
                         github_repo: Optional[str], local_path: Path) -> Track:
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


def _walk(notes_root: Path, cfg: dict, include_archive: bool) -> list[Track]:
    out = []
    for md_path in sorted(notes_root.rglob("*.md")):
        if not include_archive and "archive" in md_path.parts:
            continue
        # '-' prefix rejected so a `--repo.md` file can't become a `--repo`
        # track that the CLI misparses as a flag (#194).
        if md_path.name.startswith((".", "_", "-")):
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
