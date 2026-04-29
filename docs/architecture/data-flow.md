# Data Flow

> Companion to: [overview.md](overview.md) · [components.md](components.md)

Sequence diagrams for the four flows that carry the most complexity:

1. [`brief`](#brief--multi-track-snapshot) — multi-track snapshot
2. [`handoff`](#handoff--with-claude-driven-next_up) — wrap up a work block + Claude-driven `next_up`
3. [`orient` (track mode)](#orient--track-mode) — re-orient on a track
4. [Two-step AI subcommands](#two-step-ai-subcommands-group--suggest-priorities) — `group` and `suggest-priorities`

A brief note on the lifecycle gap is at the [end](#install-time-vs-run-time).

---

## `brief` — multi-track snapshot

Read-only. Walks every track, hits GitHub for state, and prints a sorted snapshot. Output is the deliverable — the LLM relays it verbatim into chat.

```mermaid
sequenceDiagram
    actor User
    participant LLM as Claude Code
    participant CLI as work_plan.py brief
    participant FS as Track files (.md)
    participant gh
    participant git

    User->>LLM: /work-plan brief
    LLM->>CLI: Bash(python3 ... brief)
    CLI->>FS: load_config() → notes_root, repos
    CLI->>FS: discover_tracks() — walk *.md, parse frontmatter
    loop per active track
        CLI->>gh: gh issue view (parallel-ish, one per issue)
        gh-->>CLI: issue state, labels, milestone
        opt local clone configured
            CLI->>git: branch / uncommitted / ahead-of-upstream
            git-->>CLI: state
        end
        CLI->>CLI: detect_drift(body, github_issues)
        CLI->>CLI: closure.is_closure_ready(signals)
    end
    CLI->>CLI: render.time_aware_framing(gap, hour)
    CLI-->>LLM: full snapshot text (stdout)
    LLM-->>User: relay verbatim in fenced code block
```

**Why `gh` per issue, not per repo**: tracks reference specific issue numbers; fetching only those is cheaper than `gh issue list` and avoids label-filter drift.

---

## `handoff` — with Claude-driven `next_up`

The most complex flow in the system. The CLI does the deriving; the LLM does the picking. Two CLI invocations bracket one LLM reasoning step.

```mermaid
sequenceDiagram
    actor User
    participant LLM as Claude Code
    participant CLI as work_plan.py handoff
    participant FS as Track file
    participant gh
    participant git

    User->>LLM: /work-plan handoff <track>
    LLM->>CLI: Bash(python3 ... handoff <track>)

    CLI->>FS: parse_file → meta, body
    CLI->>FS: extract last_session, open_items from canonical table

    Note over CLI,git: Attribution rules (handoff.py _recent_commits)
    alt frontmatter has github.branches
        CLI->>git: git log <branch> --since=<last_handoff>
    else no branches listed
        CLI->>git: git log --all --since=<last_handoff>
        CLI->>CLI: filter to commits mentioning #NNNN<br/>where NNNN ∈ track.github.issues
    end

    CLI->>git: uncommitted (only if current branch ∈ track.github.branches)
    CLI->>gh: fetch_issues(track.repo, issue_nums)
    gh-->>CLI: issues incl. closedAt
    CLI->>CLI: filter to closed-since-last_handoff
    CLI->>CLI: find_new_issues_for_tracks (recent unlinked)

    CLI->>FS: append_session_log(### Session — <ts>)
    CLI->>FS: update_row_status for each issue (canonical table)
    CLI->>FS: write_file with new last_handoff timestamp
    CLI-->>LLM: full handoff output + fresh-session prompt block

    Note over LLM: Claude reads output + project memory<br/>(MEMORY.md, ~/.claude/projects/.../memory/)<br/>Picks next single issue OR tight cluster (2-4)<br/>Justifies the pick in 1-2 sentences

    LLM->>CLI: Bash(... handoff <track> --set-next 4167,4148)
    CLI->>FS: write next_up: [4167, 4148] to frontmatter
    CLI-->>LLM: ✓ next_up set to [4167, 4148]
    LLM-->>User: relay handoff output + show pick + invite override
```

**Body-first principle**: when `git`/`gh` data is missing or unattributable, the output still lands meaningfully because the canonical body table + last session log are always available. See `handoff.py:_open_items_from_canonical`.

**Branch-attribution conservatism**: if no branches are listed in frontmatter and the current branch isn't recognized, `_uncommitted_files` returns empty rather than misattributing another track's work-in-progress. This is deliberate — false attribution is worse than missing data.

---

## `orient` — track mode

Read-only. Produces a ~15-line paste block designed to be pasted into a fresh terminal in another Claude Code session. No writes.

```mermaid
sequenceDiagram
    actor User
    participant LLM as Claude Code
    participant CLI as work_plan.py orient
    participant FS as Track file
    participant gh
    participant git

    User->>LLM: /work-plan orient <track>
    LLM->>CLI: Bash(python3 ... orient <track>)

    alt track arg given
        CLI->>FS: find_track_by_name(name, tracks)
    else no arg
        CLI->>git: branch + recent commits + modified files for cwd
        Note over CLI: Falls through to cwd-snapshot mode<br/>(non-track-bound work)
    end

    CLI->>FS: parse_file → meta, body
    CLI->>gh: fetch_issues(track.repo, track.meta.github.issues)
    opt local clone configured
        CLI->>git: branch / ahead / uncommitted
    end

    CLI->>CLI: extract last_session block from body
    CLI->>CLI: format paste block (priority · last session · next pick · git state)
    CLI-->>LLM: ~15-line paste block (stdout)
    LLM-->>User: relay verbatim in fenced code block
```

The cwd-fallthrough is what makes `orient` viable for non-track work — drop into a directory that isn't yet a track, run `/work-plan orient`, get a useful snapshot anyway.

---

## Two-step AI subcommands (`group` / `suggest-priorities`)

Both run as **CLI → LLM → CLI** with a `/tmp/` JSON file as the handoff format. The CLI never makes an LLM call directly.

```mermaid
sequenceDiagram
    actor User
    participant LLM as Claude Code
    participant CLI as work_plan.py
    participant gh
    participant Tmp as /tmp/work_plan_*.answers.json

    User->>LLM: /work-plan group --milestone=v1.0.0
    LLM->>CLI: Bash(... group --milestone=v1.0.0)
    CLI->>gh: gh issue list (matching milestone/label/repo)
    gh-->>CLI: issues (number + title only)
    CLI-->>LLM: prompt block: "cluster these issues into thematic tracks; write JSON to /tmp/work_plan_groups.answers.json"

    Note over LLM: Read titles, decide clusters,<br/>generate slug + member-issue-list per cluster
    LLM->>Tmp: Write tool → JSON
    LLM-->>User: show proposed clusters BEFORE applying

    User->>LLM: looks good
    LLM->>CLI: Bash(... group --apply)
    CLI->>Tmp: read JSON
    CLI->>CLI: write <repo>/<slug>.md per cluster<br/>(frontmatter + canonical issue table)
    CLI-->>LLM: ✓ created N tracks
    LLM-->>User: confirmation
```

Identical structure for `suggest-priorities`, except the JSON contains `{issue_num: "P0|P1|P2|P3"}` and `--apply` runs `gh issue edit --add-label priority/PN`.

**Privacy note**: only issue **titles** are sent to the model. Issue bodies, code, and PR contents are not.

---

## Install-time vs run-time

The flows above describe **run-time** — what happens when a subcommand executes. The **install-time** path is separate and only relevant when developing the toolkit itself:

```mermaid
sequenceDiagram
    actor Dev
    participant SH as install.sh / .ps1
    participant Repo as ./skills/
    participant Home as ~/.claude/
    participant CLI as /work-plan slash command

    Dev->>Repo: edit code in skills/work-plan/...
    Dev->>SH: ./install.sh
    SH->>SH: verify gh + git + yq + python3 on PATH
    SH->>Home: cp -R skills/work-plan ~/.claude/skills/
    SH->>Home: drop .installed-from marker
    SH->>Home: cp commands/work-plan.md ~/.claude/commands/
    opt config doesn't exist
        SH->>Home: seed ~/.claude/work-plan/config.yml
    end
    SH->>SH: smoke test (work_plan.py --help)
    Note over Dev,CLI: Now the slash command sees the new code

    Dev->>CLI: /work-plan brief
```

This is what the [overview](overview.md#two-distinct-lifecycles) refers to as the source-vs-runtime gap. Direct CLI invocation (`python3 skills/work-plan/work_plan.py ...`) bypasses this gap entirely and is the recommended dev-loop shortcut.
