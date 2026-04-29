"""Shared CLI helpers: prompts and arg parsing."""


def prompt_input(message: str, default: str = "") -> str:
    """Print prompt and read a free-form line. Treats EOF (no stdin) as default.

    Returns the stripped input, or `default` if EOF or blank.
    """
    print(message)
    try:
        line = input().strip()
    except EOFError:
        return default
    return line if line else default


def prompt_lines() -> list[str]:
    """Read lines from stdin until blank line or EOF. Returns list of non-blank lines."""
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
    """Print prompt and read y/N. Treats EOF (no stdin) as no.

    Returns True only if user explicitly types 'y' (case-insensitive).
    """
    print(message)
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
      - flags_dict: {"--all": True, "--repo": "critforge", ...} for flags found.
      - positional_list: args that aren't flags.

    Unknown flags are passed through as positional args (caller decides what to do).
    """
    flags = {}
    positional = []
    for arg in args:
        if not arg.startswith("--"):
            positional.append(arg)
            continue
        key, _, val = arg.partition("=")
        if key in known:
            flags[key] = val if val else True
        else:
            positional.append(arg)
    return flags, positional
