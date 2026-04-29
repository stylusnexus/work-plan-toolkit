"""Compose terminal output strings."""


def time_aware_framing(gap_seconds: int, current_hour: int, handoff_today: bool = True) -> str:
    """Adapt framing to gap-since-last-activity + hour."""
    six_hours = 6 * 3600
    one_hour = 3600

    if gap_seconds > six_hours or current_hour < 11:
        line = "Fresh start. Here's what changed since you stepped away."
    elif gap_seconds >= one_hour:
        line = "Picking back up. Here's what was active when you stepped away."
    else:
        line = "Continuing. Drift since last brief:"

    if current_hour >= 23 and not handoff_today:
        line += "\n  Want a handoff before bed? Run /work-plan handoff [track]."

    return line


def render_track_row(t: dict) -> str:
    """Render one track block in the brief output."""
    lines = []

    badge_parts = []
    if t["operational_status"] == "in-progress":
        badge_parts.append("in-progress")
    elif t["operational_status"] == "blocked":
        badge_parts.append("blocked")
    badge_parts.append(t["launch_priority"])
    badge_parts.append(t["milestone_alignment"])
    badge_parts.append(f"last touched {t['last_touched_label']}, last handoff {t['last_handoff_label']}")
    lines.append(f"▸ {t['name']} ({' · '.join(badge_parts)})")

    if t["next_up"]:
        for idx, item in enumerate(t["next_up"]):
            label = f"#{item['number']} {item['title']} ({item['priority']}, {item['state']})"
            prefix = "    Up next:    " if idx == 0 else "                "
            lines.append(prefix + label)
    else:
        lines.append("    Up next:    <empty — set 'next_up:' or all items show backlog>")

    for b in t["active_branches"]:
        ahead = f"ahead {b['ahead']}" if b["ahead"] else "no commits ahead"
        uc = f", uncommitted: {b['uncommitted_files']} file(s)" if b["uncommitted_files"] else ""
        lines.append(f"    Active:     {b['name']} ({ahead}{uc})")

    for n in t["new_issues"]:
        lines.append(f"    New:        #{n['number']} {n['title']} — slot? [run: /work-plan slot {n['number']}]")

    if t["blockers"]:
        for b in t["blockers"]:
            reason = b.get("reason", "manually flagged")
            lines.append(f"    Blocker:    #{b['number']} — {reason}")
    else:
        lines.append("    Blockers:   none")

    if t["drift_items"]:
        items = ", ".join(f"#{d['issue']}" for d in t["drift_items"])
        lines.append(f"    Drift:      {items} — body says open but GitHub says closed (or vice versa). "
                     f"Run /work-plan refresh-md {t['name']}")

    if t["closure_ready"]:
        lines.append(f"    Closure?:   YES — run /work-plan close {t['name']}")
    elif t.get("closure_signals_summary"):
        lines.append(f"    Closure?:   {t['closure_signals_summary']}")

    return "\n".join(lines)


def render_archived_reopen(repo: str, slug: str, issue: dict) -> str:
    return (f"⚠  archive/{slug}.md (shipped) — new issue #{issue['number']} "
            f"matches this slug. Re-open or slot into a different track?")
