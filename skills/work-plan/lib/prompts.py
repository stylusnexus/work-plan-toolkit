"""Shared CLI helpers: prompts and arg parsing."""
import sys


def _stdin_is_interactive() -> bool:
    """True only when stdin is a real terminal we can block on for a reply.

    When the CLI is launched with stdin wired to a pipe or socket that stays
    open but never delivers a line — e.g. the VS Code extension spawning
    `work_plan.py` — `input()` blocks forever (no data, no EOF). A closed pipe
    raises EOFError and is handled; an *idle open* one hangs. Guarding on
    `isatty()` lets the prompt helpers fall back to their default instead of
    deadlocking. Non-interactive callers should pass an explicit flag
    (`--yes`, `--draft`) rather than rely on the prompt.
    """
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (ValueError, AttributeError):
        # stdin closed/detached, or replaced by an object without isatty.
        return False


def prompt_input(message: str, default: str = "") -> str:
    """Print prompt and read a free-form line. Treats EOF (no stdin) as default.

    Returns the stripped input, or `default` if EOF, blank, or there is no
    interactive terminal to read from.
    """
    print(message)
    if not _stdin_is_interactive():
        print(f"(no interactive terminal — using default {default!r})")
        return default
    try:
        line = input().strip()
    except EOFError:
        return default
    return line if line else default


def prompt_lines() -> list[str]:
    """Read lines from stdin until blank line or EOF. Returns list of non-blank lines.

    With no interactive terminal, returns an empty list rather than blocking.
    """
    if not _stdin_is_interactive():
        return []
    out = []
    try:
        while True:
            line = input().rstrip()
            if not line:
                break
            out.append(line)
    except EOFError:
        pass
    return out


def prompt_yes_no(message: str = "Apply? [y/N]") -> bool:
    """Print prompt and read y/N. Treats EOF or no terminal as no.

    Returns True only if user explicitly types 'y' (case-insensitive).
    """
    print(message)
    if not _stdin_is_interactive():
        print("(no interactive terminal — defaulting to no)")
        return False
    try:
        choice = input().strip().lower()
    except EOFError:
        print("(no input — cancelled)")
        return False
    return choice == "y"


def parse_flags(args: list[str], known: set[str]) -> tuple[dict, list[str]]:
    """Split CLI args into recognized flags + positional args.

    `known` is the set of flag names this command supports (e.g. {"--all", "--yes"}).
    For `--key=value` flags, key.split("=", 1)[0] is matched against `known`.

    Returns: (flags_dict, positional_list).
      - flags_dict: {"--all": True, "--repo": "myproject", ...} for flags found.
      - positional_list: args that aren't flags.

    Unknown flags are passed through as positional args (caller decides what to do).
    """
    flags = {}
    positional = []
    end_of_opts = False
    for arg in args:
        # A bare `--` ends option parsing: everything after it is positional,
        # even if it begins with `--`. Lets callers (e.g. the VS Code extension)
        # pass a GitHub-derived value like a `--repo`-named track as a plain
        # positional instead of having it misparsed as a flag (#194).
        if end_of_opts:
            positional.append(arg)
            continue
        if arg == "--":
            end_of_opts = True
            continue
        if not arg.startswith("--"):
            positional.append(arg)
            continue
        key, _, val = arg.partition("=")
        if key in known:
            flags[key] = val if val else True
        else:
            positional.append(arg)
    return flags, positional
