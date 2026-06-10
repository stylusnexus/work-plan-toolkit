# UX Designer Memory — work-plan-toolkit

## Milestone grouping in canonical markdown table (issue #101)

Recommendation delivered 2026-06-10. Key findings:

- `_render_canonical_table` in `commands/canonicalize.py` already has a multi-section
  heading path (the `len(groups) > 1` branch) that is latently broken — refresh machinery
  (`sync_missing_rows`, `update_row_status`) is single-table-centric and will drop new
  issues into the first section only.

- Recommended approach: single ordered table with a `Milestone` column and a blank data
  row (`| | | | | |`) as a visual divider between active-milestone block and the rest.
  The blank row is invisible to the refresh parser (no `#NNNN` refs) and survives all
  markdown renderers without breaking table parsing.

- Multi-section heading approach explicitly rejected: structurally incompatible with the
  current round-trip. VS Code viewer already handles rich milestone banding via `<tbody>`
  groups — the markdown file does not need to duplicate that structure.

- `render_issue_row` in `lib/status_table.py` has a 4-column signature and does not need
  to change for the refresh path. Canonicalize constructs the 5-column row inline.

- `sync_missing_rows` appended rows will lack Milestone value until next `--force`
  canonicalize; acceptable as a known gap.

## Key file paths

- `skills/work-plan/commands/canonicalize.py` — canonical table rendering
- `skills/work-plan/lib/status_table.py` — row shape, refresh parser
- `skills/work-plan/lib/export_model.py` — milestone sort/group logic (reusable as-is)
