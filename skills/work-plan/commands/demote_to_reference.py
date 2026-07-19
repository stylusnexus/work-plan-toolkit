"""demote-to-reference subcommand — migrate issues a track lists in
github.issues purely to surface counts into github.references, once a
specialist track has taken real ownership (cross-track references, #458; this
migration command, #462).

All-or-nothing preflight: if ANY requested issue would be orphaned (no other
active owner in the same repo) or isn't currently owned by the target track,
the WHOLE batch is refused and no write happens — this is a migration tool,
not a best-effort batch op, so a partial run that silently drops an issue's
only owner is worse than an explicit refusal the caller can act on.
"""
import json

from lib.config import load_config, ConfigError
from lib.tracks import (
    discover_tracks, find_track_by_name, parse_track_repo_arg,
    AmbiguousTrackError, active_owning_tracks,
)
from lib.membership_guard import guarded_demote_write, shared_rebase_guard
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags


def run(args: list[str]) -> int:
    flags, positional = parse_flags(args, {"--confirm", "--repo", "--expect"})

    if len(positional) < 2:
        print(
            "usage: work_plan.py demote-to-reference <issue-num>..."
            " <track | track@repo> [--repo=<key>]"
        )
        return 2

    *issue_strs, target_arg = positional

    issue_nums: list[int] = []
    for s in issue_strs:
        try:
            issue_nums.append(int(s))
        except ValueError:
            print(f"ERROR: '{s}' is not an issue number.")
            return 2

    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None

    target_name, repo_from_arg = parse_track_repo_arg(target_arg)
    repo_qualifier = repo_from_arg or repo_flag

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

    # Confirm gate — mirrors slot/batch-slot: PUBLIC (or unknown-visibility)
    # writes need an explicit heads-up before landing.
    confirm = flags.get("--confirm")
    if target.repo and needs_confirm(target.repo, cfg) and not (
        isinstance(confirm, str) and valid_token(confirm, target.repo, target.name)
    ):
        print(json.dumps({
            "needs_confirm": True,
            "reason": (
                f"{target.repo} is PUBLIC (or visibility unknown); demoting"
                f" {len(issue_nums)} issue(s) to reference will be written there."
            ),
            "token": make_token(target.repo, target.name),
        }))
        return 0

    # Shared-tier rebase (#241): pull + rebase the plan_branch worktree onto
    # origin before writing; an un-rebasable divergence aborts cleanly.
    ok, reason = shared_rebase_guard(target, cfg)
    if not ok:
        print(json.dumps({"needs_rebase": True, "reason": reason, "track": target.name}))
        return 0

    owned = set(int(n) for n in (target.meta.get("github", {}).get("issues") or []))
    referenced = set(int(n) for n in (target.meta.get("github", {}).get("references") or []))

    skipped: list[int] = []          # already a reference — idempotent no-op
    to_demote: list[int] = []        # passes preflight
    refused: list[tuple[int, str]] = []

    for n in issue_nums:
        if n in referenced and n not in owned:
            skipped.append(n)
            continue
        if n not in owned:
            refused.append((n, "not currently owned by this track"))
            continue
        owners = active_owning_tracks(n, target.repo, target.name, tracks)
        if not owners:
            refused.append((n, "no other active owning track — would orphan the issue"))
            continue
        to_demote.append(n)

    # All-or-nothing: any refusal aborts the whole batch, target untouched.
    if refused:
        print(f"✗ Refused — {len(refused)} issue(s) failed preflight; no changes made.")
        for n, reason in refused:
            print(f"  #{n}: {reason}")
        if skipped:
            skipped_str = ", ".join(f"#{n}" for n in skipped)
            print(f"ℹ Already referenced (unaffected): {skipped_str}.")
        return 1

    if not to_demote:
        if skipped:
            skipped_str = ", ".join(f"#{n}" for n in skipped)
            print(
                f"All {len(skipped)} issue(s) already referenced in track"
                f" '{target.name}': {skipped_str}."
            )
        return 0

    expect = flags.get("--expect")
    expect = expect if isinstance(expect, str) else None

    result = guarded_demote_write(target.path, nums=to_demote, expect=expect)
    if result.get("stale"):
        print(json.dumps({
            "stale": True,
            "reason": result["reason"],
            "current_issues": result["current_issues"],
            "current_references": result["current_references"],
            "track": target.name,
        }))
        return 0

    demoted_str = ", ".join(f"#{n}" for n in to_demote)
    print(f"✓ Demoted {demoted_str} to reference in '{target.name}'.")
    if skipped:
        skipped_str = ", ".join(f"#{n}" for n in skipped)
        print(f"ℹ Already referenced: {skipped_str}.")
    return 0
