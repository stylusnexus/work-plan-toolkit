"""Append session log entries to track body."""

SESSION_LOG_HEADER = "## Session log"


def append_session_log(body: str, timestamp: str,
                       touched: list[str], next_up: list[str],
                       blockers: list[dict]) -> str:
    """Append a `### Session — <timestamp>` block under the Session log section."""
    block_lines = [f"### Session — {timestamp}\n"]
    if touched:
        for t in touched:
            block_lines.append(f"- Touched: {t}")
    else:
        block_lines.append("- Touched: (nothing committed)")
    if next_up:
        for n in next_up:
            block_lines.append(f"- Next: {n}")
    else:
        block_lines.append("- Next: (open)")
    if blockers:
        for b in blockers:
            block_lines.append(f"- Blocker: #{b['number']} — {b['reason']}")
    block_lines.append("")
    block = "\n".join(block_lines)

    if SESSION_LOG_HEADER in body:
        idx = body.index(SESSION_LOG_HEADER)
        rest = body[idx + len(SESSION_LOG_HEADER):]
        next_h2 = rest.find("\n## ")
        if next_h2 == -1:
            insertion = rest + "\n" + block
        else:
            insertion = rest[:next_h2] + "\n" + block + rest[next_h2:]
        return body[:idx] + SESSION_LOG_HEADER + insertion

    if not body.endswith("\n"):
        body += "\n"
    return body + f"\n{SESSION_LOG_HEADER}\n\n{block}"
