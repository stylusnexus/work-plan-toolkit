/**
 * Pure HTML detail-panel renderer for a single work-plan Track.
 *
 * No vscode imports. All user-supplied text is HTML-escaped.
 */

import type { Track, Issue } from "../model.ts";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Maximum issues to show in the detail panel before collapsing the rest. */
const DETAIL_ISSUE_CAP = 50;

// ---------------------------------------------------------------------------
// Public surface
// ---------------------------------------------------------------------------

/**
 * Renders the inner HTML for the track detail panel.
 *
 * When the track's issues span multiple distinct milestone groups the table
 * includes milestone band rows between groups.  The first group (active
 * milestone) is expanded by default; future-milestone and no-milestone
 * groups start collapsed.  A single-group track renders flat — no bands,
 * same behaviour as before #101.
 *
 * @param track - The track to render.
 * @returns     HTML string (safe to set as innerHTML — all text is escaped).
 */
export function renderDetail(track: Track): string {
  const parts: string[] = [];

  // -------------------------------------------------------------------------
  // Rollup line
  // -------------------------------------------------------------------------

  parts.push(
    `<p class="rollup"><b>${track.rollup.open}</b> open · <b>${track.rollup.closed}</b> closed</p>`,
  );

  // -------------------------------------------------------------------------
  // Issues table (with milestone bands when multiple groups exist)
  // -------------------------------------------------------------------------

  const groups = groupByMilestone(track.issues);

  parts.push('<table class="issues">');
  parts.push(
    "<thead><tr><th>Num</th><th>Title</th><th>State</th><th>Assignee</th><th></th></tr></thead>",
  );

  if (groups.length <= 1) {
    // Flat table — single milestone group (or all null).
    const allIssues = track.issues;
    const visible = allIssues.slice(0, DETAIL_ISSUE_CAP);
    const hidden = allIssues.slice(DETAIL_ISSUE_CAP);

    parts.push("<tbody>");
    for (const issue of visible) {
      parts.push(renderIssueRow(track, issue));
    }
    parts.push("</tbody>");

    if (hidden.length > 0) {
      parts.push(
        `<tbody class="issue-cap-band collapsed"><tr class="issue-cap-toggle"><td colspan="5">` +
          `<details><summary>Show all ${allIssues.length} issues (${hidden.length} more)</summary>` +
          `<table>`
      );
      for (const issue of hidden) {
        parts.push(renderIssueRow(track, issue));
      }
      parts.push(`</table></details></td></tr></tbody>`);
    }
  } else {
    // Milestone bands.
    let first = true;
    let totalRendered = 0;
    const hiddenIssues: Issue[] = [];

    for (const [label, issues] of groups) {
      const heading = label ? esc(label) : "No milestone";
      const count = String(issues.length);
      const collapsedClass = first ? "" : " collapsed";
      parts.push(`<tbody class="milestone-band${collapsedClass}">`);
      parts.push(
        `<tr class="milestone-band-header"><td colspan="4">` +
          `<span class="milestone-toggle">▸</span> ` +
          `<b>${heading}</b> <span class="milestone-count">(${count})</span>` +
          `</td></tr>`,
      );

      for (const issue of issues) {
        if (totalRendered < DETAIL_ISSUE_CAP) {
          parts.push(renderIssueRow(track, issue));
          totalRendered++;
        } else {
          hiddenIssues.push(issue);
        }
      }
      parts.push("</tbody>");
      first = false;
    }

    if (hiddenIssues.length > 0) {
      parts.push(
        `<tbody class="issue-cap-band collapsed"><tr class="issue-cap-toggle"><td colspan="5">` +
          `<details><summary>Show all ${track.issues.length} issues (${hiddenIssues.length} more)</summary>` +
          `<table>`
      );
      for (const issue of hiddenIssues) {
        parts.push(renderIssueRow(track, issue));
      }
      parts.push(`</table></details></td></tr></tbody>`);
    }
  }

  parts.push("</table>");

  // -------------------------------------------------------------------------
  // Blocker chips
  // -------------------------------------------------------------------------

  parts.push('<div class="blockers"><b>Blockers:</b> ');

  if (track.blockers.length === 0) {
    parts.push("None.");
  } else {
    const chips = track.blockers.map(n => {
      const title = lookupTitle(track, n);
      const label = title !== "" ? `#${n} ${esc(title)}` : `#${n}`;
      return `<span class="chip">⛔ ${label}</span>`;
    });
    parts.push(chips.join(" "));
  }

  parts.push("</div>");

  // -------------------------------------------------------------------------
  // Depends on (cross-track dependencies, #102)
  // -------------------------------------------------------------------------

  parts.push('<div class="depends-on"><b>Depends on:</b> ');

  if (track.depends_on.length === 0) {
    parts.push("None.");
  } else {
    const depChips = track.depends_on.map(name =>
      `<span class="depends-chip" data-track="${esc(name)}">${esc(name)}</span>`,
    );
    parts.push(depChips.join(" "));
  }

  parts.push("</div>");

  // -------------------------------------------------------------------------
  // Next-up steps
  // -------------------------------------------------------------------------

  parts.push('<div class="next-up"><b>Next up:</b> ');

  if (track.next_up.length === 0) {
    parts.push("empty");
  } else {
    const steps = track.next_up.map(n => {
      const title = lookupTitle(track, n);
      const label = title !== "" ? `#${n} ${esc(title)}` : `#${n}`;
      return `<span class="step">${label}</span>`;
    });
    parts.push(steps.join(" → "));
  }

  parts.push("</div>");

  return parts.join("\n");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Renders a single <tr> for an issue, with a Move button. */
function renderIssueRow(track: Track, issue: Issue): string {
  const numCell = track.repo
    ? `<td class="num"><a href="#" data-repo="${esc(track.repo)}" data-issue="${issue.number}">#${issue.number}</a></td>`
    : `<td class="num">#${issue.number}</td>`;
  const moveBtn = track.repo
    ? `<td class="move-col"><button class="move-btn" data-move="${issue.number}" title="Move to another track">↗</button></td>`
    : `<td class="move-col"></td>`;
  return (
    `<tr>` +
    numCell +
    `<td>${esc(issue.title)}</td>` +
    `<td><span class="pill ${esc(issue.state)}">${esc(issue.state)}</span></td>` +
    `<td class="who">${esc(issue.assignee)}</td>` +
    moveBtn +
    `</tr>`
  );
}

/**
 * Escapes HTML special characters in a string.
 * Handles & < > " ' — sufficient for attribute values and text nodes.
 */
function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Looks up an issue title from the track's issues[] by number.
 * Returns empty string if not found.
 */
function lookupTitle(track: Track, num: number): string {
  const issue = track.issues.find(i => i.number === num);
  return issue !== undefined ? issue.title : "";
}

/**
 * Groups issues by milestone in the canonical sort order.
 *
 * Returns [(label, [Issue, ...]), ...] where label is the compact milestone
 * string (as from short_milestone) or null for the no-milestone group.
 * Issues are already sorted by milestone_sort_key (active first, future
 * milestones grouped, null last).  The input issues array is NOT mutated.
 *
 * Graceful fallback: if all issues share the same milestone (or all lack
 * one), returns a single-group result — callers can use this to skip
 * rendering section headings.
 */
function groupByMilestone(
  issues: Issue[],
): [string | null, Issue[]][] {
  if (issues.length === 0) return [];

  // Sort by milestone: null last, then by milestone label, then by number.
  const sorted = [...issues].sort((a, b) => {
    const msA = a.milestone ?? null;
    const msB = b.milestone ?? null;
    if (msA === null && msB !== null) return 1;
    if (msB === null && msA !== null) return -1;
    if (msA !== null && msB !== null && msA !== msB) {
      return msA.localeCompare(msB);
    }
    return a.number - b.number;
  });

  const groups: [string | null, Issue[]][] = [];
  let currentLabel: string | null = undefined as unknown as null;
  let currentGroup: Issue[] = [];
  for (const issue of sorted) {
    const label = issue.milestone ?? null;
    if (label !== currentLabel) {
      if (currentGroup.length > 0) {
        groups.push([currentLabel, currentGroup]);
      }
      currentLabel = label;
      currentGroup = [issue];
    } else {
      currentGroup.push(issue);
    }
  }
  if (currentGroup.length > 0) {
    groups.push([currentLabel, currentGroup]);
  }
  return groups;
}
