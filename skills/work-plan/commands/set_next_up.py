"""set-next-up subcommand — guarded edit of a track's next_up ranking preset.

Usage:
  work_plan.py set-next-up <track> [--repo=<key>]
      (--preset=<name> | --order=a,b,c | --clear | --auto=on|off)
      [--confirm=<token>]

Writes `next_up_order` and/or `next_up_auto` into the track's frontmatter.
Does NOT touch the `next_up` issue-list key.

  --preset=<name>   Set one of the named ranking presets (flow, priority-driven,
                    backlog) or 'custom' (which requires --order).
  --order=a,b,c     Set a custom comma-separated criterion list.
  --clear           Remove the next_up_order key (reverts to global/default).
  --auto=on|off     Toggle the next_up_auto flag. When on, brief/orient/export
                    auto-derive the next-up list via the ranking preset (#326).
                    Can be used standalone or combined with --preset/--order/--clear.

Public-repo gated: without --confirm it prints {needs_confirm, reason, token}
and makes no change. The VS Code extension surfaces that as a modal then
re-invokes with --confirm=<token>.
"""
import json
import sys
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags
from lib.next_up import CRITERIA, PRESETS


def run(args: list[str]) -> int:
    flags, positional = parse_flags(
        args, {"--confirm", "--repo", "--clear", "--preset", "--order", "--auto"}
    )
    if not positional:
        print(
            "usage: work_plan.py set-next-up <track> "
            "(--preset=<name> | --order=a,b,c | --clear | --auto=on|off) "
            "[--repo=<key>] [--confirm=<token>]"
        )
        return 2

    track_arg = positional[0]
    name_from_arg, repo_from_arg = parse_track_repo_arg(track_arg)
    name = name_from_arg
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    repo_qualifier = repo_from_arg or repo_flag

    clear = bool(flags.get("--clear"))
    preset_flag = flags.get("--preset") if flags.get("--preset") is not True else None
    order_flag = flags.get("--order") if flags.get("--order") is not True else None
    auto_raw = flags.get("--auto") if flags.get("--auto") is not True else None

    # Parse and validate --auto value
    auto_value = None  # None means not specified
    if auto_raw is not None:
        auto_lower = auto_raw.lower() if isinstance(auto_raw, str) else ""
        if auto_lower == "on":
            auto_value = True
        elif auto_lower == "off":
            auto_value = False
        else:
            print(
                f"ERROR: --auto must be 'on' or 'off', got {auto_raw!r}",
                file=sys.stderr,
            )
            return 2

    # Must have at least one of --preset, --order, --clear, or --auto
    if not clear and preset_flag is None and order_flag is None and auto_value is None:
        print(
            "ERROR: specify --preset=<name>, --order=a,b,c, --clear, or --auto=on|off",
            file=sys.stderr,
        )
        return 2

    # Validate preset name
    if preset_flag is not None:
        valid_presets = set(PRESETS.keys()) | {"custom"}
        if preset_flag not in valid_presets:
            print(
                f"ERROR: unknown preset {preset_flag!r} "
                f"(allowed: {sorted(valid_presets)})",
                file=sys.stderr,
            )
            return 2
        # 'custom' requires --order
        if preset_flag == "custom" and order_flag is None:
            print(
                "ERROR: --preset=custom requires --order=<criteria>",
                file=sys.stderr,
            )
            return 2

    # Validate order criteria
    order_list = None
    if order_flag is not None:
        raw_criteria = [c.strip() for c in order_flag.split(",") if c.strip()]
        invalid = [c for c in raw_criteria if c not in CRITERIA]
        if invalid:
            print(
                f"ERROR: unknown criteria {invalid!r} "
                f"(allowed: {list(CRITERIA)})",
                file=sys.stderr,
            )
            return 2
        if not raw_criteria:
            print("ERROR: --order requires at least one criterion", file=sys.stderr)
            return 2
        order_list = raw_criteria

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    try:
        track = find_track_by_name(name, discover_tracks(cfg), repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e))
        return 1
    if not track:
        print(f"No track matching {name!r}.")
        return 1

    # Public-repo confirm gate
    confirm = flags.get("--confirm")
    if (
        track.repo
        and needs_confirm(track.repo, cfg)
        and not (isinstance(confirm, str) and valid_token(confirm, track.repo, track.name))
    ):
        print(
            json.dumps(
                {
                    "needs_confirm": True,
                    "reason": (
                        f"{track.repo} is PUBLIC (or visibility unknown); "
                        "edit will be written there."
                    ),
                    "token": make_token(track.repo, track.name),
                }
            )
        )
        return 0

    if clear:
        track.meta.pop("next_up_order", None)
        if auto_value is not None:
            _apply_auto(track, auto_value)
        write_file(track.path, track.meta, track.body)
        print(f"✓ cleared next_up_order on {track.name}")
        if auto_value is not None:
            _print_auto_result(track, auto_value)
        return 0

    # If --auto is the only flag (no preset/order/clear), write just the auto flag.
    if preset_flag is None and order_list is None and auto_value is not None:
        _apply_auto(track, auto_value)
        write_file(track.path, track.meta, track.body)
        _print_auto_result(track, auto_value)
        return 0

    # Build the next_up_order mapping
    if preset_flag == "custom" or (preset_flag is None and order_list is not None):
        # Custom order (either explicit --preset=custom or bare --order)
        nuo = {"preset": "custom", "order": order_list}
    else:
        # Named preset. A named preset supplies its own criterion order, so a
        # co-supplied --order has no effect — warn (advisory, don't reject) so
        # the user isn't surprised it was dropped.
        nuo = {"preset": preset_flag}
        if order_list is not None:
            print(
                f"WARN: --order is ignored when a named preset "
                f"(--preset={preset_flag}) is given; use --preset=custom "
                "to supply your own order.",
                file=sys.stderr,
            )

    track.meta["next_up_order"] = nuo
    if auto_value is not None:
        _apply_auto(track, auto_value)
    write_file(track.path, track.meta, track.body)

    if preset_flag and preset_flag != "custom":
        print(f"✓ set next_up_order preset={preset_flag!r} on {track.name}")
    elif order_list is not None:
        print(f"✓ set next_up_order custom order={order_list!r} on {track.name}")
    if auto_value is not None:
        _print_auto_result(track, auto_value)
    return 0


def _apply_auto(track: "SimpleNamespace", auto_value: bool) -> None:
    """Mutate track.meta to set or remove next_up_auto."""
    if auto_value:
        track.meta["next_up_auto"] = True
    else:
        track.meta.pop("next_up_auto", None)


def _print_auto_result(track: "SimpleNamespace", auto_value: bool) -> None:
    if auto_value:
        print(f"✓ set next_up_auto=true on {track.name}")
    else:
        print(f"✓ cleared next_up_auto on {track.name}")
