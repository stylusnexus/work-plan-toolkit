"""Join the two issue-level in-progress signals into one boolean (#271).

GitHub is canonical; nothing here is cached. `hot_nums` comes from live git
(lib.git_state.hot_issue_numbers); the label is read from a live `gh` fetch.
"""

IN_PROGRESS_LABEL = "work-plan:in-progress"


def issue_in_progress(issue_row: dict, hot_nums) -> bool:
    """True iff the issue is OPEN and (its number is hot OR it carries the label).

    Closed/merged always returns False (closed wins). `issue_row` is a fetched
    gh issue dict ({number, state, labels:[{name}]}); `hot_nums` is a set of ints.
    """
    state = (issue_row.get("state") or "OPEN").upper()
    if state != "OPEN":
        return False
    number = issue_row.get("number")
    if number in hot_nums:
        return True
    names = {l.get("name") for l in (issue_row.get("labels") or [])}
    return IN_PROGRESS_LABEL in names
