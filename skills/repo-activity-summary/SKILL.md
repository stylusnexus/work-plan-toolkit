---
name: repo-activity-summary
description: Use when the user asks to summarize repo activity, check project status, gauge progress, list open issues and PRs, or see CI health. Triggers on "activity summary", "what's open", "project status", "progress check", "CI status".
---

# Repo Activity Summary

Summarize current repository activity — open issues, pull requests, and CI status — in one structured report. Uses the `gh` CLI against the current repo.

## Data Gathering

Run all three `gh` commands in parallel:

### Open Issues (top 15)

```bash
gh issue list --state open --limit 15 \
  --json number,title,labels,milestone,updatedAt \
  --jq '.[] | "\(.number)\t\(.title)\t\(.labels | map(.name) | join(","))\t\(.milestone.title // "none")\t\(.updatedAt[:10])"'
```

### Open Pull Requests

```bash
gh pr list --state open --limit 10 \
  --json number,title,headRefName,createdAt,isDraft,statusCheckRollup \
  --jq '.[] | "\(.number)\t\(.title)\t\(.headRefName)\t\(.createdAt[:10])\t\(.isDraft)\t\(.statusCheckRollup | map(.conclusion // .status) | join(","))"'
```

### Recent CI Runs (last 8)

```bash
gh run list --limit 8 \
  --json name,status,conclusion,headBranch,createdAt,event \
  --jq '.[] | "\(.conclusion // .status)\t\(.name)\t\(.headBranch)\t\(.createdAt[:10])\t\(.event)"'
```

## Output Format

Present results as three markdown tables with a planning summary:

```
## Open Issues (N)
| # | Title | Milestone | Labels |
[sorted by number descending — newest first]

Breakdown: X on milestone-A, Y on milestone-B. Highlight P0/P1 items.

## Open Pull Requests (N)
| # | Title | Branch | Draft? | CI |
[note any failing checks]

## CI Status (Recent Runs)
| Status | Workflow | Branch |
[flag any failures prominently]

## Current Branch Context
[git branch name + uncommitted file count from git status]

## Planning Takeaways
[2-4 bullet points: blockers, active work, items needing attention]
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using `checks` field on `gh pr list` | Use `statusCheckRollup` instead — `checks` is not a valid JSON field |
| Not handling empty results | If no open PRs, say "No open pull requests" instead of an empty table |
| Forgetting current branch context | Always include `git branch --show-current` and uncommitted file count |
