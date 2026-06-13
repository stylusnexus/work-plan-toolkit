"""set subcommand — guarded edit of a track's frontmatter scalar/list fields."""
import json
import sys
from lib.config import load_config, ConfigError, resolve_local_path_for_folder
from lib.tracks import discover_tracks, find_track_by_name, parse_track_repo_arg, AmbiguousTrackError
from lib.frontmatter import write_file
from lib.write_guard import needs_confirm, make_token, valid_token
from lib.prompts import parse_flags

ALLOWED = {"status", "launch_priority", "milestone_alignment", "blockers", "next_up", "depends_on", "plan"}
LIST_FIELDS = {"blockers", "next_up"}
STATUSES = {"active", "in-progress", "blocked", "parked", "shipped", "abandoned"}

def run(args: list[str]) -> int:
    # Confirm token is passed as --confirm=<token> (equals form: parse_flags only
    # understands --key=value or bare --key, so a space-separated token would be
    # mis-read as a positional). The VS Code extension invokes the equals form.
    flags, positional = parse_flags(args, {"--confirm", "--repo"})
    if len(positional) < 2:
        print("usage: work_plan.py set <track> field=value [field=value …] [--confirm=<token>] [--repo=<key>]"); return 2
    track_arg, assignments = positional[0], positional[1:]
    name_from_arg, repo_from_arg = parse_track_repo_arg(track_arg)
    name = name_from_arg
    repo_flag = flags.get("--repo") if flags.get("--repo") is not True else None
    repo_qualifier = repo_from_arg or repo_flag
    parsed = {}
    for a in assignments:
        if "=" not in a:
            print(f"ERROR: bad assignment {a!r} (expected field=value)"); return 2
        k, v = a.split("=", 1)
        if k not in ALLOWED:
            print(f"ERROR: field {k!r} not settable (allowed: {sorted(ALLOWED)})"); return 2
        if k == "depends_on":
            # Comma-separated track slugs (strings, not issue numbers).
            parsed[k] = [x.strip() for x in v.split(",") if x.strip()] if v.strip() else []
        elif k in LIST_FIELDS:
            try:
                parsed[k] = [int(x) for x in v.split(",") if x.strip()] if v.strip() else []
            except ValueError:
                print(f"ERROR: {k} takes comma-separated integers (got {v!r})"); return 2
        elif k == "status" and v not in STATUSES:
            print(f"ERROR: status {v!r} invalid (allowed: {sorted(STATUSES)})"); return 2
        elif k == "plan":
            # Repo-relative path to the track's plan/spec doc (#285). Empty value
            # clears the link. Stored as a scalar string; validated (advisory) below.
            parsed[k] = v.strip()
        else:
            parsed[k] = v
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}"); return 1
    try:
        track = find_track_by_name(name, discover_tracks(cfg), repo=repo_qualifier)
    except AmbiguousTrackError as e:
        print(str(e)); return 1
    if not track:
        print(f"No track matching {name!r}."); return 1
    # Public-repo confirm gate (the extension surfaces this as a modal).
    confirm = flags.get("--confirm")
    if track.repo and needs_confirm(track.repo, cfg) and not (isinstance(confirm, str) and valid_token(confirm, track.repo, track.name)):
        print(json.dumps({"needs_confirm": True,
                          "reason": f"{track.repo} is PUBLIC (or visibility unknown); edit will be written there.",
                          "token": make_token(track.repo, track.name)}))
        return 0
    # An empty `plan=` clears the link rather than writing `plan: ""` (#285).
    if "plan" in parsed and parsed["plan"] == "":
        parsed.pop("plan")
        track.meta.pop("plan", None)
    # Advisory validation: a non-empty plan path that doesn't resolve to a file in
    # the track's repo checkout is saved anyway (the doc may not exist yet, or the
    # repo may have no local clone) but flagged so a typo is caught early.
    if parsed.get("plan") and track.folder:
        local = resolve_local_path_for_folder(track.folder, cfg)
        if local and local.exists() and not (local / parsed["plan"]).is_file():
            print(f"WARN: plan path {parsed['plan']!r} does not resolve to a file "
                  f"under {local} — link saved anyway.", file=sys.stderr)

    track.meta.update(parsed)
    write_file(track.path, track.meta, track.body)
    fields = ", ".join(parsed) if parsed else "plan (cleared)"
    print(f"✓ set {fields} on {track.name}")
    return 0
