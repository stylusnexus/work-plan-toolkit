/**
 * Pure HTML detail-panel renderer for a single work-plan Track.
 *
 * No vscode imports. All user-supplied text is HTML-escaped.
 */

import type { Track } from "../model.ts";

// ---------------------------------------------------------------------------
// Public surface
// ---------------------------------------------------------------------------

/**
 * Renders the inner HTML for the track detail panel.
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
  // Issues table
  // -------------------------------------------------------------------------

  parts.push('<table class="issues">');
  parts.push("<thead><tr><th>Num</th><th>Title</th><th>State</th><th>Assignee</th></tr></thead>");
  parts.push("<tbody>");

  for (const issue of track.issues) {
    parts.push(
      `<tr>` +
        `<td class="num">#${issue.number}</td>` +
        `<td>${esc(issue.title)}</td>` +
        `<td><span class="pill ${esc(issue.state)}">${esc(issue.state)}</span></td>` +
        `<td class="who">${esc(issue.assignee)}</td>` +
        `</tr>`,
    );
  }

  parts.push("</tbody></table>");

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
