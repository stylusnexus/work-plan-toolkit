"""plan-branch subcommand — bootstrap + share a repo's canonical plan branch (#260).

The shared (`.work-plan/`) tier is pinned to ONE per-repo `plan_branch`, read and
written through a dedicated git worktree (Phases 1+2). This command sets that up
and shares it:

  init <repo>   Create the plan branch + `.work-plan/` skeleton for <repo>, or
                connect to a teammate's already-published one, and record
                `plan_branch` in config. LOCAL ONLY — no network push. Default
                branch is an ORPHAN `work-plan/plan` (zero shared history with
                code, like gh-pages); override with --branch=<name>.
  status <repo> Report the configured plan_branch: does it exist, is it
                published to origin, how many local commits are unpushed.
                Add --json for the machine shape.
  push <repo>   Push the plan branch to origin to share it. This is the exposure
                point: on a PUBLIC repo it prints a confirm heads-up + token and
                exits; re-run with --confirm=<token>. --dry-run previews the
                commits that would be pushed without pushing.

Usage:
  plan-branch <init|status|push> <repo> [--branch=<name>] [--confirm=<token>]
                                        [--dry-run] [--json]
"""
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from lib.config import (
    load_config, ConfigError, DEFAULT_CONFIG_PATH, is_valid_git_repo,
)
from lib.git_state import is_safe_ref
from lib.notes_readme import seed_readme
from lib.prompts import parse_flags
from lib.write_guard import needs_confirm, make_token, valid_token
from lib import plan_worktree as pw

_ACTIONS = ("init", "status", "push")
_DEFAULT_BRANCH = "work-plan/plan"
# A git refname segment: starts alnum, then alnum / . _ - and / separators. We
# additionally reject `..`, leading/trailing `/`, and `//` below.
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")  # safe for the yq config path


def _valid_branch(name: str) -> bool:
    return (
        is_safe_ref(name)
        and bool(_BRANCH_RE.fullmatch(name))
        and ".." not in name
        and "//" not in name
        and not name.startswith("/")
        and not name.endswith("/")
        and not name.endswith(".lock")
    )


def _set_plan_branch(key: str, branch: str) -> bool:
    """Persist .repos.<key>.plan_branch=<branch> into config via yq. The branch
    travels as an opaque env value (strenv), never interpolated. `key` is the
    config repo key (validated by the caller). Returns True on success."""
    env = {**os.environ, "WP_PLAN_BRANCH": branch}
    expr = f".repos.{key}.plan_branch = strenv(WP_PLAN_BRANCH)"
    try:
        subprocess.run(
            ["yq", "-i", expr, str(DEFAULT_CONFIG_PATH)],
            check=True, capture_output=True, text=True, env=env,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: yq failed to update config: {e.stderr}")
        return False


def _resolve_repo(cfg: dict, repo_arg: Optional[str]):
    """Return (key, entry, github, local_path) for a CONFIGURED repo, or print an
    error and return None. plan-branch writes into a repo's config entry, so the
    repo must be registered (init-repo) and have a local clone path."""
    repos = cfg.get("repos") or {}
    if repo_arg is None:
        if len(repos) == 1:
            key = next(iter(repos))
        else:
            print("ERROR: specify which repo — e.g. `plan-branch init <key>`. "
                  f"Configured: {', '.join(repos) or '(none)'}.")
            return None
    elif repo_arg in repos:
        key = repo_arg
    else:
        print(f"ERROR: '{repo_arg}' is not a configured repo. Register it first "
              "with `init-repo <key> --github=org/repo --local=<path>`.")
        return None

    if not _KEY_RE.fullmatch(key):
        print(f"ERROR: repo key '{key}' has unexpected characters; refusing to "
              "edit config for it.")
        return None
    entry = repos[key] or {}
    github = entry.get("github")
    local_raw = entry.get("local")
    if not local_raw:
        print(f"ERROR: repo '{key}' has no local clone path in config. Add one "
              f"with `init-repo {key} --github={github or 'org/repo'} --local=<path>`.")
        return None
    local_path = Path(local_raw).expanduser()
    if not is_valid_git_repo(local_path):
        print(f"ERROR: {local_path} is not a git repository.")
        return None
    return key, entry, github, local_path


def _do_init(cfg, key, entry, github, local_path, flags) -> int:
    raw = flags.get("--branch")
    branch = raw if isinstance(raw, str) and raw else _DEFAULT_BRANCH
    if not _valid_branch(branch):
        print(f"ERROR: '{branch}' is not a valid branch name.")
        return 2

    existing = entry.get("plan_branch")
    if existing and existing != branch:
        print(f"ERROR: repo '{key}' already has plan_branch '{existing}'. "
              "Refusing to silently switch it — edit config to change.")
        return 1

    # Fetch so the connect-vs-create decision sees a teammate's published branch.
    pw.fetch_branch(local_path, branch)

    if pw._branch_exists(local_path, branch):
        # Connect: a branch already exists (local or origin) — reuse it.
        wt = pw.ensure_worktree(local_path, branch)
        if wt is None:
            print(f"ERROR: branch '{branch}' exists but its worktree could not be "
                  "created. Resolve any conflicting worktree and retry.")
            return 1
        # The branch already carries its own .work-plan/ — connecting just wires
        # it up; no seeding (and no write into a possibly-absent dir).
        print(f"✓ Connected repo '{key}' to existing plan branch '{branch}'.")
        published = pw.is_published(local_path, branch)
        print(f"  Source: {'origin (a teammate published it)' if published else 'local'}.")
    else:
        # Create a fresh orphan branch with only .work-plan/.
        dest = pw.create_orphan_worktree(local_path, branch)
        if dest is None:
            print(f"ERROR: could not create the plan worktree for '{branch}'. "
                  "Is there a stale worktree at the cache path, or no commits in "
                  "the repo yet?")
            return 1
        seed_readme(dest / ".work-plan")
        paths = pw.dirty_work_plan_paths(dest)
        sha = pw.commit_shared_tier(
            dest, f"work-plan: initialize plan branch {branch}", paths)
        if sha is None:
            print(f"ERROR: created the worktree but the initial commit failed.")
            return 1
        print(f"✓ Created orphan branch '{branch}' for '{key}' ({sha}, local only).")
        print("  It holds only plan data — no shared history with your code, so "
              "it won't appear in pull requests or deploys.")

    if not _set_plan_branch(key, branch):
        return 1
    print(f"✓ Recorded plan_branch '{branch}' in config for '{key}'.")
    print()
    print("Next:")
    print(f"  • Add a shared track:  /work-plan new-track {key} <slug>")
    print(f"  • Share the branch:    /work-plan plan-branch push {key}")
    if github and needs_confirm(github, cfg):
        print(f"    ⚠ {github} is public — `push` will make the plan visible to anyone.")
    return 0


def _do_status(cfg, key, entry, github, local_path, flags) -> int:
    branch = entry.get("plan_branch")
    want_json = "--json" in flags
    if not branch:
        if want_json:
            print(json.dumps({"repo": key, "plan_branch": None,
                              "configured": False}))
        else:
            print(f"repo '{key}': no plan_branch configured.")
            print(f"  Run `plan-branch init {key}` to set one up.")
        return 0

    pw.fetch_branch(local_path, branch)  # best-effort: accurate published/unpushed
    local_exists = pw.local_branch_exists(local_path, branch)
    published = pw.is_published(local_path, branch)
    unpushed = pw.unpushed_oneline(local_path, branch)

    if want_json:
        print(json.dumps({
            "repo": key, "plan_branch": branch, "configured": True,
            "local_exists": local_exists, "published": published,
            "unpushed_count": len(unpushed),
        }))
        return 0

    print(f"repo '{key}': plan_branch '{branch}'")
    print(f"  local branch: {'✓ present' if local_exists else '✗ missing (run init)'}")
    print(f"  published:    {'✓ on origin' if published else '✗ local only — not shared yet'}")
    if unpushed:
        print(f"  unpushed:     {len(unpushed)} commit(s) — run "
              f"`plan-branch push {key}` to share:")
        for line in unpushed[:10]:
            print(f"      {line}")
        if len(unpushed) > 10:
            print(f"      … and {len(unpushed) - 10} more")
    else:
        print("  unpushed:     none — origin is up to date.")
    return 0


def _do_push(cfg, key, entry, github, local_path, flags) -> int:
    branch = entry.get("plan_branch")
    if not branch:
        print(f"ERROR: repo '{key}' has no plan_branch. Run `plan-branch init "
              f"{key}` first.")
        return 1
    if not pw.local_branch_exists(local_path, branch):
        print(f"ERROR: plan branch '{branch}' doesn't exist locally. Run "
              f"`plan-branch init {key}` first.")
        return 1

    pw.fetch_branch(local_path, branch)
    commits = pw.unpushed_oneline(local_path, branch)

    if "--dry-run" in flags:
        if not commits:
            print(f"Nothing to push — origin/{branch} is up to date.")
            return 0
        print(f"Would push {len(commits)} commit(s) to origin/{branch}:")
        for line in commits:
            print(f"  {line}")
        return 0

    if not commits:
        print(f"Nothing to push — origin/{branch} is up to date.")
        return 0

    # Exposure gate: publishing planning notes to a PUBLIC repo is a meaningful,
    # effectively-permanent disclosure. Same confirm-token flow as other public
    # writes, with concrete wording about what becomes visible.
    if github and needs_confirm(github, cfg):
        confirm = flags.get("--confirm")
        if not (isinstance(confirm, str) and valid_token(confirm, github, branch)):
            print(json.dumps({
                "needs_confirm": True,
                "reason": (
                    f"{github} is PUBLIC (or its visibility is unknown). Pushing "
                    f"'{branch}' makes your plan files — issue notes, priorities, "
                    "and planning text — visible to anyone on the internet, and "
                    "they remain in public git history even if the branch is "
                    "later deleted."
                ),
                "token": make_token(github, branch),
            }))
            return 0

    proc = pw.push_plan_branch(local_path, branch)
    if proc is None:
        print("ERROR: could not run git to push.")
        return 1
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "protected" in err.lower() or "pull request" in err.lower():
            print(f"ERROR: origin rejected the push — '{branch}' looks protected. "
                  f"Exempt '{branch.split('/')[0]}/**' from PR/branch-protection "
                  "rules for the plan branch, or push it manually once.")
        else:
            print(f"ERROR: push failed: {err or 'unknown git error'}")
        return 1
    print(f"✓ Pushed '{branch}' to origin ({len(commits)} commit(s)). "
          "Teammates can `plan-branch init` to connect.")
    return 0


def run(args: list[str]) -> int:
    flags, positional = parse_flags(
        args, {"--branch", "--confirm", "--dry-run", "--json"})

    action = positional[0] if positional else None
    if action not in _ACTIONS:
        print(f"usage: work_plan.py plan-branch <{'|'.join(_ACTIONS)}> <repo> "
              "[--branch=<name>] [--confirm=<token>] [--dry-run] [--json]")
        return 2

    repo_arg = positional[1] if len(positional) > 1 else None

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    resolved = _resolve_repo(cfg, repo_arg)
    if resolved is None:
        return 1
    key, entry, github, local_path = resolved

    if action == "init":
        return _do_init(cfg, key, entry, github, local_path, flags)
    if action == "status":
        return _do_status(cfg, key, entry, github, local_path, flags)
    return _do_push(cfg, key, entry, github, local_path, flags)
