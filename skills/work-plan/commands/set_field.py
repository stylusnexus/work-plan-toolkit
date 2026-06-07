"""set subcommand — guarded edit of a track's frontmatter scalar/list fields."""
import json
from lib.config import load_config, ConfigError
from lib.tracks import discover_tracks, find_track_by_name
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags

ALLOWED = {"status", "launch_priority", "milestone_alignment", "blockers", "next_up"}
LIST_FIELDS = {"blockers", "next_up"}
STATUSES = {"active", "in-progress", "blocked", "parked", "shipped", "abandoned"}

def run(args: list[str]) -> int:
    # Confirm token is passed as --confirm=<token> (equals form: parse_flags only
    # understands --key=value or bare --key, so a space-separated token would be
    # mis-read as a positional). The VS Code extension invokes the equals form.
    flags, positional = parse_flags(args, {"--confirm"})
    if len(positional) < 2:
        print("usage: work_plan.py set <track> field=value [field=value …] [--confirm=<token>]"); return 2
    name, assignments = positional[0], positional[1:]
    parsed = {}
    for a in assignments:
        if "=" not in a:
            print(f"ERROR: bad assignment {a!r} (expected field=value)"); return 2
        k, v = a.split("=", 1)
        if k not in ALLOWED:
            print(f"ERROR: field {k!r} not settable (allowed: {sorted(ALLOWED)})"); return 2
        if k in LIST_FIELDS:
            try:
                parsed[k] = [int(x) for x in v.split(",") if x.strip()] if v.strip() else []
            except ValueError:
                print(f"ERROR: {k} takes comma-separated integers (got {v!r})"); return 2
        elif k == "status" and v not in STATUSES:
            print(f"ERROR: status {v!r} invalid (allowed: {sorted(STATUSES)})"); return 2
        else:
            parsed[k] = v
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}"); return 1
    track = find_track_by_name(name, discover_tracks(cfg))
    if not track:
        print(f"No track matching {name!r}."); return 1
    # Public-repo confirm gate (the extension surfaces this as a modal).
    confirm = flags.get("--confirm")
    if track.repo and needs_confirm(track.repo) and not (isinstance(confirm, str) and valid_token(confirm, track.repo, track.name)):
        print(json.dumps({"needs_confirm": True,
                          "reason": f"{track.repo} is PUBLIC (or visibility unknown); edit will be written there.",
                          "token": make_token(track.repo, track.name)}))
        return 0
    track.meta.update(parsed)
    write_file(track.path, track.meta, track.body)
    print(f"✓ set {', '.join(parsed)} on {track.name}")
    return 0
