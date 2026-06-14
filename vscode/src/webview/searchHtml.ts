/**
 * Pure HTML builder for the issue-search results panel (#272).
 *
 * No vscode imports — `nonce` and `cspSource` are passed in so the output can be
 * unit-tested without a webview host. Theme-adaptive via --vscode-* CSS vars;
 * CSP forbids network sources and allows scripts only via the nonce.
 */

import type { SearchHit } from "./search.ts";
import { esc } from "./html.ts";

export interface SearchHtmlOptions {
  /** The raw query the user typed (echoed verbatim, escaped). */
  query: string;
  hits: SearchHit[];
  /** Export `generated_at` ISO string — surfaced so the user knows the snapshot age. */
  generatedAt: string;
  /** webview.cspSource. */
  cspSource: string;
  /** Caller-generated random nonce. */
  nonce: string;
}

/** Open issues sort before closed; within a state, ascending by issue number. */
function sortHits(hits: SearchHit[]): SearchHit[] {
  return [...hits].sort((a, b) => {
    if (a.state !== b.state) return a.state === "open" ? -1 : 1;
    return a.number - b.number;
  });
}

/** Groups hits by repo, preserving first-seen repo order. */
function groupByRepo(hits: SearchHit[]): { repo: string; hits: SearchHit[] }[] {
  const order: string[] = [];
  const byRepo = new Map<string, SearchHit[]>();
  for (const h of hits) {
    if (!byRepo.has(h.repo)) {
      byRepo.set(h.repo, []);
      order.push(h.repo);
    }
    byRepo.get(h.repo)!.push(h);
  }
  return order.map(repo => ({ repo, hits: sortHits(byRepo.get(repo)!) }));
}

function rowHtml(h: SearchHit): string {
  const stateGlyph = h.state === "open" ? "◆" : "◇";
  const stateClass = h.state === "open" ? "open" : "closed";
  const trackCell = h.track === null
    ? `<span class="muted">untracked</span>`
    : esc(h.track);
  // Reveal-in-tree only applies to tracked issues.
  const revealBtn = h.track === null
    ? ""
    : `<button class="reveal-btn" data-repo="${esc(h.repo)}" data-track="${esc(h.track)}"
        title="Reveal owning track in the Tracks view" aria-label="Reveal track ${esc(h.track)} in the Tracks view">⤢</button>`;
  return `<tr>
    <td class="num"><a href="https://github.com/${esc(h.repo)}/issues/${h.number}" class="issue-link" data-repo="${esc(h.repo)}" data-number="${h.number}"
        aria-label="Open issue ${h.number} on GitHub">#${h.number}</a></td>
    <td class="title">${esc(h.title)}</td>
    <td class="state ${stateClass}"><span aria-hidden="true">${stateGlyph}</span> ${h.state}</td>
    <td class="track">${trackCell}${revealBtn}</td>
  </tr>`;
}

function repoSectionHtml(group: { repo: string; hits: SearchHit[] }): string {
  const rows = group.hits.map(rowHtml).join("\n");
  return `<section class="repo-group">
    <h2 class="repo-heading">${esc(group.repo)} <span class="muted">(${group.hits.length})</span></h2>
    <table>
      <caption class="sr-only">Search results in ${esc(group.repo)}</caption>
      <thead>
        <tr><th scope="col">#</th><th scope="col">Title</th><th scope="col">State</th><th scope="col">Track</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </section>`;
}

export function buildSearchHtml(o: SearchHtmlOptions): string {
  const { query, hits, generatedAt, cspSource, nonce } = o;
  const queryEsc = esc(query);
  const count = hits.length;

  const csp = [
    `default-src 'none'`,
    `img-src ${cspSource}`,
    `style-src ${cspSource} 'unsafe-inline'`,
    `script-src 'nonce-${nonce}'`,
  ].join("; ");

  const headingText = count === 0
    ? `No issues matched “${queryEsc}”`
    : `${count} issue${count === 1 ? "" : "s"} matching “${queryEsc}”`;

  const body = count === 0
    ? `<div class="empty">
         <p class="empty-head">${headingText}</p>
         <p class="muted">Try a shorter pattern, or remove <code>%</code> to search for a bare word.</p>
       </div>`
    : groupByRepo(hits).map(repoSectionHtml).join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Issue Search</title>
  <style>
    :root {
      --bg: var(--vscode-editor-background, #1e1e1e);
      --fg: var(--vscode-foreground, #d4d4d4);
      --muted: var(--vscode-descriptionForeground, #8c8c8c);
      --border: var(--vscode-panel-border, #333);
      --link: var(--vscode-textLink-foreground, #4fc1ff);
      --open-fg: var(--vscode-charts-blue, #4fa3ff);
      --closed-fg: var(--vscode-charts-green, #3fa45e);
      --row-hover: var(--vscode-list-hoverBackground, #2a2d2e);
      --focus: var(--vscode-focusBorder, #007fd4);
    }
    body {
      background: var(--bg); color: var(--fg);
      font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
      font-size: var(--vscode-font-size, 13px);
      margin: 0; padding: 12px 16px;
    }
    .sr-only {
      position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
      overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
    }
    .muted { color: var(--muted); }
    h1.results-heading { font-size: 1.1em; margin: 0 0 4px; }
    .hint { color: var(--muted); margin: 0 0 2px; font-size: 0.92em; }
    .snapshot { color: var(--muted); margin: 0 0 14px; font-size: 0.88em; }
    .snapshot button.refresh {
      background: none; border: none; color: var(--link); cursor: pointer;
      padding: 0 0 0 6px; font: inherit; text-decoration: underline;
    }
    .snapshot button.refresh:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
    .repo-group { margin-bottom: 18px; }
    .repo-heading { font-size: 0.95em; font-weight: 600; margin: 0 0 6px; border-bottom: 1px solid var(--border); padding-bottom: 3px; }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-weight: 600; color: var(--muted); padding: 2px 8px; font-size: 0.85em; }
    td { padding: 3px 8px; vertical-align: top; }
    tbody tr:hover { background: var(--row-hover); }
    td.num { white-space: nowrap; }
    a.issue-link { color: var(--link); text-decoration: none; }
    a.issue-link:hover { text-decoration: underline; }
    a.issue-link:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; border-radius: 2px; }
    td.state.open { color: var(--open-fg); font-weight: 600; }
    td.state.closed { color: var(--closed-fg); font-weight: 600; }
    .reveal-btn {
      background: none; border: none; color: var(--link); cursor: pointer;
      margin-left: 8px; padding: 0 3px; font: inherit; opacity: 0; border-radius: 2px;
    }
    tr:hover .reveal-btn, .reveal-btn:focus-visible { opacity: 1; }
    .reveal-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
    .empty { padding: 24px 4px; }
    .empty-head { font-size: 1.05em; margin: 0 0 6px; }
    code { background: var(--row-hover); padding: 0 4px; border-radius: 3px; }
  </style>
</head>
<body>
  <h1 class="results-heading" tabindex="-1" id="results-heading" aria-live="polite">${headingText}</h1>
  <p class="hint">Bare words match anywhere in the title. Use <code>%</code> as a wildcard: <code>fix%</code> = starts-with, <code>%audit</code> = ends-with.</p>
  <p class="snapshot">As of ${esc(generatedAt)}<button class="refresh" id="refresh">Refresh &amp; re-run</button></p>
  ${body}
  <script nonce="${nonce}">
    var vscode = typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null;
    function post(msg) { if (vscode) { vscode.postMessage(msg); } }
    document.querySelectorAll("a.issue-link").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        post({ type: "openIssue", repo: a.getAttribute("data-repo"), number: Number(a.getAttribute("data-number")) });
      });
    });
    document.querySelectorAll("button.reveal-btn").forEach(function (b) {
      b.addEventListener("click", function () {
        post({ type: "revealTrack", repo: b.getAttribute("data-repo"), track: b.getAttribute("data-track") });
      });
    });
    var refresh = document.getElementById("refresh");
    if (refresh) { refresh.addEventListener("click", function () { post({ type: "refreshAndSearch" }); }); }
    // Move focus into the results when the panel opens/updates so keyboard users
    // aren't stranded in the tree.
    window.addEventListener("message", function (e) {
      if (e.data && e.data.type === "focusResults") {
        var h = document.getElementById("results-heading");
        if (h) { h.focus(); }
      }
    });
  </script>
</body>
</html>`;
}
