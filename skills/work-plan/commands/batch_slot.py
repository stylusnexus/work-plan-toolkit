"""batch-slot subcommand — slot multiple issues into a track at once."""
import json
import subprocess
import sys

from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError
from lib.membership_guard import (
    guarded_membership_write, guarded_reference_write, shared_rebase_guard,
)
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags


def _find_prior_owners(issue_num: int, repo: str, target_name: str, tracks):
    """Active tracks in `repo` (excluding `target_name`) whose frontmatter
    already lists `issue_num`. Shared with slot.py."""
    owners = []
    for t in tracks:
        if not t.has_frontmatter or t.name == target_name or t.repo != repo:
            continue
        if t.meta.get("status") not in ("active", "in-progress", "blocked"):
            continue
        if issue_num in (t.meta.get("github", {}).get("issues") or []):
            owners.append(t)
    return owners


def run(args: list[str]) -> int:
    flags, positional = parse_flags(
        args, {"--confirm", "--move", "--no-move", "--reference", "--repo", "--expect"}
    )

    if len(positional) < 2:
        print(
            "usage: work_plan.py batch-slot <issue-num>... <track | track@repo>"
            " [--repo=<key>]"
        )
        return 2

    # Last positional is the track; everything before is an issue number.
    *issue_strs, target_arg = positional

    issue_nums: list[int] = []
    for s in issue_strs:
        try:
            issue_nums.append(int(s))
        except ValueError:
            print(f"ERROR: '{s}' is not an issue number.")
            return 2

    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None

    target_name = target_arg
    repo_qualifier = repo_flag
    if target_arg:
        name_from_arg, repo_from_arg = parse_track_repo_arg(target_arg)
        target_name = name_from_arg
        if repo_from_arg:
            repo_qualifier = repo_from_arg

    if "--move" in flags and "--no-move" in flags:
        print("ERROR: --move and --no-move are mutually exclusive.")
        return 2
    if "--reference" in flags and "--move" in flags:
        print("ERROR: --reference cannot be combined with --move.")
        return 2

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    tracks = discover_tracks(cfg)

    try:
        target = find_track_by_name(
            target_name, tracks, active_only=True, repo=repo_qualifier
        )
    except AmbiguousTrackError as e:
        print(str(e))
        return 1
    if not target:
        print(f"No active track matching '{target_name}'.")
        return 1

    # Confirm gate — fire once for the whole batch.
    confirm = flags.get("--confirm")
    if target.repo and needs_confirm(target.repo, cfg) and not (
        isinstance(confirm, str) and valid_token(confirm, target.repo, target.name)
    ):
        print(
            json.dumps(
                {
                    "needs_confirm": True,
                    "reason": (
                        f"{target.repo} is PUBLIC (or visibility unknown); "
                        f"batch-slotting {len(issue_nums)} issue(s) will be"
                        f" written there."
                    ),
                    "token": make_token(target.repo, target.name),
                }
            )
        )
        return 0

    # Shared-tier rebase (#241): pull + rebase the plan_branch worktree onto
    # origin before writing; an un-rebasable divergence aborts cleanly.
    ok, reason = shared_rebase_guard(target, cfg)
    if not ok:
        print(json.dumps({"needs_rebase": True, "reason": reason, "track": target.name}))
        return 0

    do_move = "--move" in flags
    as_reference = "--reference" in flags

    # --expect=<fp> opts into the compare-and-swap staleness guard (#241). When
    # present (the assisted/viewer path) advisory notes go to stderr so stdout
    # stays pure for the {stale} abort signal the caller parses.
    expect = flags.get("--expect")
    expect = expect if isinstance(expect, str) else None
    notes = sys.stderr if expect is not None else sys.stdout

    # Collect source tracks that need issue removal (consolidated per source).
    source_removals: dict[str, tuple] = {}  # source_name -> (source_track, set[issue_num])

    issues = list(target.meta.get("github", {}).get("issues") or [])
    references = list(target.meta.get("github", {}).get("references") or [])
    skipped: list[int] = []
    slotted: list[int] = []

    for issue_num in issue_nums:
        if as_reference:
            if issue_num in references:
                skipped.append(issue_num)
                continue
            references.append(issue_num)
            slotted.append(issue_num)
            continue
        if issue_num in issues:
            skipped.append(issue_num)
            continue

        # Milestone mismatch check (non-blocking warning). Never let gh being
        # absent/odd crash the command — it's advisory and sits before the write.
        try:
            proc = subprocess.run(
                ["gh", "issue", "view", str(issue_num),
                 "--repo", target.repo, "--json", "milestone"],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                info = json.loads(proc.stdout)
                m = info.get("milestone", {})
                if (
                    m and m.get("title")
                    and m["title"] != target.meta.get("milestone_alignment")
                ):
                    print(
                        f"⚠  #{issue_num} is on milestone '{m['title']}', "
                        f"track '{target.name}' aligned to"
                        f" '{target.meta.get('milestone_alignment')}'.",
                        file=notes,
                    )
        except (OSError, json.JSONDecodeError):
            pass

        # Prior-owner detection.
        sources = _find_prior_owners(
            issue_num, target.repo, target.name, tracks
        )

        issues.append(issue_num)
        slotted.append(issue_num)

        if sources and do_move:
            for src in sources:
                if src.name not in source_removals:
                    source_removals[src.name] = (src, set())
                source_removals[src.name][1].add(issue_num)
        elif sources and not do_move:
            names = ", ".join(f"'{t.name}'" for t in sources)
            print(
                f"ℹ #{issue_num} still listed in {names}"
                f" — re-run with --move to relocate.",
                file=notes,
            )

    if not slotted:
        if skipped:
            print(
                f"All {len(skipped)} issue(s) already in track"
                f" '{target.name}'."
            )
        return 0

    # Write source tracks (consolidated removals), each re-read + merged onto
    # fresh disk so a concurrent edit to a source track isn't clobbered.
    if do_move:
        for src_name, (src, removals) in source_removals.items():
            guarded_membership_write(src.path, remove_nums=removals)
            removed_str = ", ".join(f"#{n}" for n in sorted(removals))
            print(f"  ✓ Removed {removed_str} from '{src_name}'.", file=notes)

    # Write target track once. Carries `expect`: on a detected concurrent change
    # to the membership list it aborts with {stale} instead of clobbering.
    result = (
        guarded_reference_write(target.path, add_nums=slotted)
        if as_reference
        else guarded_membership_write(target.path, add_nums=slotted, expect=expect)
    )
    if result.get("stale"):
        print(json.dumps({
            "stale": True,
            "reason": result["reason"],
            "current": result["current"],
            "track": target.name,
        }))
        return 0

    slotted_str = ", ".join(f"#{n}" for n in slotted)
    verb = "Referenced" if as_reference else "Slotted"
    print(f"✓ {verb} {slotted_str} in '{target.name}'.")
    if skipped:
        skipped_str = ", ".join(f"#{n}" for n in skipped)
        print(f"ℹ Skipped (already in track): {skipped_str}.")
    return 0
