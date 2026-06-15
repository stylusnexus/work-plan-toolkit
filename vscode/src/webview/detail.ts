/**
 * Pure HTML detail-panel renderer for a single work-plan Track.
 *
 * No vscode imports. All user-supplied text is HTML-escaped.
 */

import type { Track, Issue, TrackPlan, IssueDep } from "../model.ts";

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
 * @param opts  - Optional rendering flags.
 * @param opts.showNextUpPreset - When true (and `track.next_up_preset` is set),
 *   render a "Next-up order:" meta row below the next-up steps (#326).
 * @returns     HTML string (safe to set as innerHTML — all text is escaped).
 */
export function renderDetail(track: Track, opts?: { showNextUpPreset?: boolean }): string {
  const parts: string[] = [];

  // -------------------------------------------------------------------------
  // Rollup line
  // -------------------------------------------------------------------------

  parts.push(
    `<p class="rollup"><b>${track.rollup.open}</b> open · <b>${track.rollup.closed}</b> closed</p>`,
  );

  // Closed/total progress bar (#220) — a redundant visual of the rollup text
  // above (which is the WCAG 1.4.1 label), with role=progressbar for AT. Tokens
  // are theme-guaranteed to contrast (a11y audit). Omitted for an empty track.
  const ptotal = track.rollup.open + track.rollup.closed;
  if (ptotal > 0) {
    const pct = Math.round((track.rollup.closed / ptotal) * 100);
    parts.push(
      `<div class="progress" role="progressbar" aria-valuemin="0" ` +
      `aria-valuemax="${ptotal}" aria-valuenow="${track.rollup.closed}" ` +
      `aria-label="${track.rollup.closed} of ${ptotal} issues closed (${pct}%)">` +
      `<div class="progress-fill" style="width:${pct}%"></div></div>`,
    );
  }

  // -------------------------------------------------------------------------
  // Issues table (with milestone bands when multiple groups exist)
  // -------------------------------------------------------------------------

  const groups = groupByMilestone(track.issues, track.milestone_alignment);

  parts.push('<table class="issues">');
  parts.push(`<caption class="sr-only">Issues in ${esc(track.name)}</caption>`);
  parts.push(
    '<thead><tr>' +
      '<th scope="col">Num</th>' +
      '<th scope="col">Title</th>' +
      '<th scope="col">State</th>' +
      '<th scope="col">Assignee</th>' +
      '<th scope="col"><span class="sr-only">Actions</span></th>' +
      '</tr></thead>',
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
      parts.push(renderCapToggle(allIssues.length, hidden.length));
      for (const issue of hidden) {
        parts.push(renderIssueRow(track, issue));
      }
      parts.push("</tbody>");
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
      const expanded = first ? "true" : "false";
      // The caret + name + count is ONE collapse button (the dominant "click a
      // section header to collapse" expectation, #248). Filtering the whole view
      // by this milestone is a separate, explicit control to its right — only for
      // real milestones (the "No milestone" group has no lens). Both are real
      // <button>s (keyboard-operable, aria-labelled, #244).
      const filterBtn = label
        ? ` <button class="milestone-filter-btn" data-milestone="${esc(label)}"` +
          ` title="Filter the view to ${heading}" aria-label="Filter the view to ${heading}">filter</button>`
        : "";
      parts.push(`<tbody class="milestone-band${collapsedClass}">`);
      parts.push(
        `<tr class="milestone-band-header"><td colspan="5">` +
          `<button class="milestone-toggle-btn" aria-expanded="${expanded}" aria-label="Toggle ${heading} issues">` +
          `<span class="milestone-toggle">▸</span> <b>${heading}</b> <span class="milestone-count">(${count})</span>` +
          `</button>` +
          filterBtn +
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
      parts.push(renderCapToggle(track.issues.length, hiddenIssues.length));
      for (const issue of hiddenIssues) {
        parts.push(renderIssueRow(track, issue));
      }
      parts.push("</tbody>");
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
      `<button type="button" class="depends-chip" data-track="${esc(name)}">${esc(name)}</button>`,
    );
    parts.push(depChips.join(" "));
  }

  parts.push("</div>");

  // -------------------------------------------------------------------------
  // Plan link + execution badge (#285)
  // -------------------------------------------------------------------------

  parts.push(renderPlanSection(track.plan));

  // -------------------------------------------------------------------------
  // Next-up steps
  // -------------------------------------------------------------------------

  parts.push(
    '<div class="next-up"><b>Next up:</b> ' +
    `<button id="work-plan-set-next" class="open-file-btn" ` +
    `title="Set which issues are next up for this track" ` +
    `aria-label="Set which issues are next up for this track">Set Next-Up</button>`,
  );

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

  // -------------------------------------------------------------------------
  // Next-up ordering preset (#326)
  // -------------------------------------------------------------------------

  if (opts?.showNextUpPreset && track.next_up_preset) {
    const autoSuffix = track.next_up_auto ? " · auto" : "";
    parts.push(
      `<div class="next-up-preset"><b>Next-up order:</b> ${esc(track.next_up_preset)}${autoSuffix}</div>`,
    );
  }

  return parts.join("\n");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Renders the "Plan:" row from the track's declared plan link (#285).
 *
 * - No link → "None linked."
 * - Declared but unresolved → the path + a quiet "not found" note (no open
 *   affordance — there's nothing to open).
 * - Resolved → a clickable button (posts `openPlan`) carrying the execution
 *   badge: glyph + verdict + files/phases, with lie-gap / ✋ confirmed markers.
 *
 * Exported for direct unit testing.
 */
export function renderPlanSection(plan: Track["plan"]): string {
  if (!plan) {
    return '<div class="plan"><b>Plan:</b> None linked.</div>';
  }
  const file = plan.rel.split("/").pop() ?? plan.rel;
  if (!plan.resolved) {
    return (
      '<div class="plan"><b>Plan:</b> ' +
      `<span class="plan-unresolved" title="${esc(plan.rel)}">${esc(file)} ` +
      "— not found (no local clone or file missing)</span></div>"
    );
  }
  return (
    '<div class="plan"><b>Plan:</b> ' +
    `<button type="button" class="plan-open" title="Open ${esc(plan.rel)}">` +
    `${planBadgeLabel(plan)} — ${esc(file)}</button></div>`
  );
}

/** Compact badge label for a resolved plan: "✅ shipped · 9/9 files · 0/24 phases". */
function planBadgeLabel(plan: TrackPlan): string {
  const glyph = plan.glyph ? `${esc(plan.glyph)} ` : "";
  const bits = [`${glyph}${esc(plan.verdict ?? "")}`.trim()];
  if (typeof plan.files_present === "number" && typeof plan.files_declared === "number") {
    bits.push(`${plan.files_present}/${plan.files_declared} files`);
  }
  if (typeof plan.checkboxes_done === "number" && typeof plan.checkboxes_total === "number") {
    bits.push(`${plan.checkboxes_done}/${plan.checkboxes_total} phases`);
  }
  if (plan.override) bits.push("✋ confirmed");
  else if (plan.lie_gap) bits.push("⚠ lie-gap");
  if (plan.stalled) bits.push("stalled");
  return bits.join(" · ");
}

/** Renders a single <tr> for an issue, with a Move button, and an optional
 *  sibling dep-detail-row for blocked_by/blocking edges (#257 B3). */
function renderIssueRow(track: Track, issue: Issue): string {
  const numCell = track.repo
    ? `<td class="num"><a href="https://github.com/${esc(track.repo)}/issues/${issue.number}" data-repo="${esc(track.repo)}" data-issue="${issue.number}">#${issue.number}</a></td>`
    : `<td class="num">#${issue.number}</td>`;
  // Move + Close-on-GitHub + in-progress toggle actions (#305, #271). Close and
  // toggle show only for tracked issues in a repo'd track. Close additionally
  // requires the issue to be open (nothing to close on a closed issue).
  const closeBtn = track.repo && issue.state === "open"
    ? ` <button class="close-issue-btn" data-close="${issue.number}" title="Close #${issue.number} on GitHub" aria-label="Close issue #${issue.number} on GitHub">✕</button>`
    : "";
  // Toggle is shown for any tracked issue in a repo'd track (open or closed),
  // since a closed issue can still carry the in-progress label. data-clear drives
  // which direction the CLI call takes: "1" removes the label, "0" adds it.
  // NOTE: the toggle controls the LABEL, so it uses in_progress_label (label
  // presence only) — NOT in_progress (the union of hot-branch OR label). An
  // issue hot-branch-only (no label) correctly shows "Mark", not "Clear".
  const inProgBtn = track.repo
    ? ` <button class="inprogress-btn" data-inprogress="${issue.number}" data-clear="${issue.in_progress_label ? "1" : "0"}" title="${issue.in_progress_label ? "Clear" : "Mark"} in-progress" aria-label="${issue.in_progress_label ? "Clear" : "Mark"} issue #${issue.number} in-progress">▶</button>`
    : "";
  const moveBtn = track.repo
    ? `<td class="move-col"><button class="move-btn" data-move="${issue.number}" title="Move to another track" aria-label="Move issue #${issue.number} to another track">↗</button>${closeBtn}${inProgBtn}</td>`
    : `<td class="move-col"></td>`;
  const inProgressPill = issue.in_progress
    ? ` <span class="pill in-progress" title="In progress (hot branch or work-plan:in-progress label)">in-progress</span>`
    : "";

  // Dep disclosure button (#257 B3): deduped blocked_by + all blocking.
  // Same-repo blocked_by numbers already in track.blockers are skipped — the
  // manual ⛔ chip already owns them. Cross-repo deps with the same number keep.
  const dedupedBlockedBy = (issue.blocked_by ?? []).filter(dep =>
    !(dep.repo === track.repo && track.blockers.includes(dep.number)),
  );
  const blockingDeps = issue.blocking ?? [];
  const hasDepEdges = dedupedBlockedBy.length > 0 || blockingDeps.length > 0;

  const depToggleBtn = hasDepEdges
    ? ` <button class="dep-toggle-btn" data-depissue="${issue.number}" aria-expanded="false"` +
      ` aria-label="Show issue dependencies for #${issue.number}">⛓</button>`
    : "";

  const depDetailRow = hasDepEdges
    ? renderDepDetailRow(track, issue.number, dedupedBlockedBy, blockingDeps)
    : "";

  return (
    `<tr>` +
    numCell +
    `<td>${esc(issue.title)}${depToggleBtn}</td>` +
    `<td><span class="pill ${esc(issue.state)}">${esc(issue.state)}</span>${inProgressPill}</td>` +
    `<td class="who">${esc(issue.assignee)}</td>` +
    moveBtn +
    `</tr>` +
    depDetailRow
  );
}

/** Renders the hidden dep-detail sub-row carrying the dep chips (#257 B3). */
function renderDepDetailRow(
  track: Track,
  issueNumber: number,
  blockedBy: IssueDep[],
  blocking: IssueDep[],
): string {
  const chips: string[] = [];

  if (blockedBy.length > 0) {
    const links = blockedBy.map(dep => renderDepLink(track, dep)).join(" ");
    chips.push(
      `<span class="dep-chip dep-chip--blockedby">` +
      `<span aria-hidden="true">⊘</span>` +
      `<span class="sr-only">blocked by </span>` +
      links +
      `</span>`,
    );
  }

  if (blocking.length > 0) {
    const links = blocking.map(dep => renderDepLink(track, dep)).join(" ");
    chips.push(
      `<span class="dep-chip dep-chip--blocking">` +
      `<span aria-hidden="true">⇒</span>` +
      `<span class="sr-only">blocking </span>` +
      links +
      `</span>`,
    );
  }

  return (
    `<tr class="dep-detail-row" data-depissue="${issueNumber}" hidden>` +
    `<td colspan="5">${chips.join(" ")}</td>` +
    `</tr>`
  );
}

/** Renders a single dep link: same-repo → "#N title"; cross-repo → "owner/repo#N". */
function renderDepLink(track: Track, dep: IssueDep): string {
  const label = dep.repo === track.repo
    ? `#${dep.number}${dep.title ? " " + esc(dep.title) : ""}`
    : `${esc(dep.repo)}#${dep.number}`;
  return `<a href="https://github.com/${esc(dep.repo)}/issues/${dep.number}" data-repo="${esc(dep.repo)}" data-issue="${dep.number}">${label}</a>`;
}

/**
 * Opens an issue-cap overflow `<tbody>`: a disclosure button row that reveals the
 * capped-off rows when toggled. The caller appends the hidden `<tr>`s and the
 * closing `</tbody>`. Uses a real `<button>` (natively keyboard-operable) and
 * keeps the rows inside the same table — no invalid nested `<table>`/`<details>`.
 * The `.issue-cap-row` class marks the toggle row so the collapse CSS keeps it
 * visible while hiding the rest of the band.
 */
function renderCapToggle(total: number, hidden: number): string {
  return (
    `<tbody class="issue-cap-band collapsed">` +
    `<tr class="issue-cap-row"><td colspan="5">` +
    `<button type="button" class="issue-cap-toggle" aria-expanded="false">` +
    `<span class="issue-cap-marker">▸</span> Show all ${total} issues (${hidden} more)` +
    `</button></td></tr>`
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
 *
 * Mirrors the Python `milestone_sort_key` (lib/export_model.py): the track's
 * active milestone (`milestone_alignment`) comes first, then other non-null
 * milestones grouped by label, then the no-milestone group last; ties broken
 * by issue number. This is THE shared ordering — both surfaces derive from the
 * same rule so they cannot drift. The input issues array is NOT mutated.
 *
 * Graceful fallback: if all issues share the same milestone (or all lack
 * one), returns a single-group result — callers can use this to skip
 * rendering section headings.
 */
function groupByMilestone(
  issues: Issue[],
  milestoneAlignment: string | null = null,
): [string | null, Issue[]][] {
  if (issues.length === 0) return [];

  // Tier mirrors milestone_sort_key: 0 = active milestone, 1 = other non-null
  // milestone, 2 = no milestone. Lower tier sorts first.
  const tier = (ms: string | null): number => {
    if (ms === null || ms === "") return 2;
    if (ms === milestoneAlignment) return 0;
    return 1;
  };

  const sorted = [...issues].sort((a, b) => {
    const msA = a.milestone ?? null;
    const msB = b.milestone ?? null;
    const tierA = tier(msA);
    const tierB = tier(msB);
    if (tierA !== tierB) return tierA - tierB;
    // Same tier: within tier 1, order distinct labels lexicographically so
    // groups are stable; within any tier, ties break by issue number.
    if (tierA === 1 && msA !== msB) {
      return (msA as string).localeCompare(msB as string);
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
