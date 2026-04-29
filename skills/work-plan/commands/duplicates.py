"""duplicates subcommand: find likely-duplicate GitHub issues by title similarity.

Uses difflib.SequenceMatcher (stdlib) on normalized titles. No deps.
"""
import json
import re
import subprocess
from difflib import SequenceMatcher

from lib.config import load_config, ConfigError

# Common conventional-commit prefixes to strip before comparison
PREFIX_RE = re.compile(
    r"^(feat|fix|chore|docs|test|refactor|perf|ci|spec|style|build|infra|epic|assets|fix-up)"
    r"(\([^)]+\))?:\s*",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")


def run(args: list[str]) -> int:
    repo_arg = next((a for a in args if a.startswith("--repo=")), None)
    threshold_arg = next((a for a in args if a.startswith("--min-similarity=")), None)
    limit_arg = next((a for a in args if a.startswith("--limit=")), None)
    state_arg = next((a for a in args if a.startswith("--state=")), None)

    threshold = float(threshold_arg.split("=", 1)[1]) if threshold_arg else 0.70
    limit = int(limit_arg.split("=", 1)[1]) if limit_arg else 20
    state = state_arg.split("=", 1)[1] if state_arg else "open"

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"ERROR: {e}")
        return 1

    repos = list(cfg["repos"].keys())
    if repo_arg:
        repo_folder = repo_arg.split("=", 1)[1]
        if repo_folder not in cfg["repos"]:
            print(f"ERROR: repo folder '{repo_folder}' not in config.yml.")
            return 1
        repos = [repo_folder]
    elif len(repos) > 1:
        print("Multiple repos in config. Specify with --repo=<folder-name>.")
        return 1

    folder = repos[0]
    repo = cfg["repos"][folder]["github"]

    print(f"Fetching {state} issues from {repo}...")
    proc = subprocess.run(
        ["gh", "issue", "list", "--repo", repo,
         "--state", state, "--limit", "1000",
         "--json", "number,title,url"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"ERROR fetching issues: {proc.stderr}")
        return 1
    issues = json.loads(proc.stdout) if proc.stdout.strip() else []
    if len(issues) < 2:
        print("Not enough issues to compare.")
        return 0

    print(f"Comparing {len(issues)} issues (threshold: {threshold:.0%}, limit: {limit})...")

    normalized = [(i, _normalize(i["title"])) for i in issues]

    # Pairwise similarity (O(n²) but fine for n<=1000)
    pairs = []
    for idx_a in range(len(normalized)):
        a, norm_a = normalized[idx_a]
        if len(norm_a) < 5:
            continue
        for idx_b in range(idx_a + 1, len(normalized)):
            b, norm_b = normalized[idx_b]
            if len(norm_b) < 5:
                continue
            ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
            if ratio >= threshold:
                pairs.append((ratio, a, b))

    pairs.sort(key=lambda x: -x[0])
    pairs = pairs[:limit]

    if not pairs:
        print(f"No pairs above {threshold:.0%} similarity.")
        return 0

    print(f"\nLikely duplicates (top {len(pairs)}):\n")
    for ratio, a, b in pairs:
        print(f"  {ratio:.0%}  #{a['number']:5}  {a['title']}")
        print(f"        #{b['number']:5}  {b['title']}")
        print(f"        {a['url']}")
        print(f"        {b['url']}")
        print()

    print(f"\nReview these manually. To consolidate, close one and reference the other:")
    print(f"  gh issue close <newer> --comment 'Duplicate of #<older>' --repo {repo}")
    return 0


def _normalize(title: str) -> str:
    """Strip common prefixes + lowercase + collapse whitespace for comparison."""
    s = title.strip()
    # Remove conventional-commit prefix
    s = PREFIX_RE.sub("", s)
    s = s.lower()
    s = WHITESPACE_RE.sub(" ", s)
    return s
