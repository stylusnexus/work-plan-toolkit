/**
 * Pure HTML/CSP builder for the Work Plan webview.
 *
 * NO vscode imports — this module is 100% testable offline.
 * All content embedding relies on caller-supplied escaped strings:
 *   - graphDef is entity-safe (from toMermaid)
 *   - detailHtml is HTML-escaped (from renderDetail)
 */

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface WebviewHtmlOptions {
  /** webview.cspSource — the VS Code webview origin, e.g. "vscode-resource:" */
  cspSource: string;
  /** Caller-generated random nonce (A-Za-z0-9, length 32). */
  nonce: string;
  /** asWebviewUri(...).toString() for the local mermaid UMD bundle. */
  mermaidUri: string;
  /** Mermaid graph definition (output of toMermaid — already entity-safe). */
  graphDef: string;
  /** Inner HTML for the detail card (output of renderDetail — already escaped). */
  detailHtml: string;
  /** Selected track name for the heading (will be HTML-escaped here). */
  trackName: string;
  /**
   * true  → mermaid bundle is ESM → <script type="module" nonce>
   * false → mermaid bundle is UMD → <script nonce> (global `mermaid`)
   *
   * We ship mermaid.min.js (UMD), so this is always false in practice.
   * The flag is kept for forward-compatibility and test coverage.
   */
  isModule: boolean;
  /**
   * Whether the graph is currently in focused mode (showing only the selected
   * track's dependency neighbourhood).
   * true  → button label is "Show full map"  (click reveals full graph)
   * false → button label is "Focus on track" (click zooms in on selection)
   */
  focused: boolean;
}

// ---------------------------------------------------------------------------
// buildHtml
// ---------------------------------------------------------------------------

/**
 * Assembles the complete HTML document for the Work Plan webview panel.
 *
 * Security guarantees:
 *  - CSP forbids all network sources; only local resources and nonce'd scripts.
 *  - Every <script> element carries nonce="${nonce}".
 *  - mermaid is loaded exclusively from the caller-supplied local URI.
 *  - graphDef and detailHtml are embedded verbatim (callers are responsible
 *    for pre-escaping, per the contract above).
 *  - trackName is escaped here at the call-site boundary.
 */
export function buildHtml(o: WebviewHtmlOptions): string {
  const { cspSource, nonce, mermaidUri, graphDef, detailHtml, isModule, focused } = o;
  const trackNameEsc = esc(o.trackName);

  // CSP: no network; scripts only via nonce or from cspSource; wasm for mermaid.
  const csp = [
    `default-src 'none'`,
    `img-src ${cspSource} data:`,
    `style-src ${cspSource} 'unsafe-inline'`,
    `script-src 'nonce-${nonce}' ${cspSource} 'wasm-unsafe-eval'`,
  ].join("; ");

  // Script tag attributes differ for ESM vs UMD.
  const scriptOpenTag = isModule
    ? `<script type="module" nonce="${nonce}">`
    : `<script nonce="${nonce}">`;

  // Loader script: load mermaid bundle then initialize + run.
  // UMD path: <script nonce> loads the bundle (exposes global `mermaid`), then
  // a second nonce'd inline script initialises it.
  // ESM path: import + initialize in a single module script.
  let loaderScript: string;
  if (isModule) {
    loaderScript = `${scriptOpenTag}
import mermaid from "${mermaidUri}";
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark" });
mermaid.run();
</script>`;
  } else {
    loaderScript = `<script nonce="${nonce}" src="${mermaidUri}"></script>
<script nonce="${nonce}">
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark" });
mermaid.run();
</script>`;
  }

  // Toggle button label depends on focused state.
  const toggleLabel = focused ? "Show full map" : "Focus on track";
  const nextFocus = focused ? "false" : "true";

  // Message-passing script: click handlers → postMessage to extension host.
  // acquireVsCodeApi() must be called EXACTLY ONCE per document, so the focus
  // toggle wiring lives here alongside the track/issue handlers.
  const messagingScript = `<script nonce="${nonce}">
(function () {
  var vscode = typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null;

  function post(msg) {
    if (vscode) { vscode.postMessage(msg); }
  }

  // Focus toggle button
  var btn = document.getElementById("work-plan-focus-toggle");
  if (btn) {
    btn.addEventListener("click", function () {
      post({ type: "setFocus", focus: ${nextFocus} });
    });
  }

  // Track selector buttons
  document.addEventListener("click", function (e) {
    var target = e.target;
    if (!target) { return; }

    // data-track → selectTrack
    var trackBtn = target.closest("[data-track]");
    if (trackBtn) {
      post({ type: "selectTrack", name: trackBtn.getAttribute("data-track") });
      return;
    }

    // data-repo + data-issue → openIssue
    var issueLink = target.closest("[data-repo][data-issue]");
    if (issueLink) {
      e.preventDefault();
      post({
        type: "openIssue",
        repo: issueLink.getAttribute("data-repo"),
        number: parseInt(issueLink.getAttribute("data-issue"), 10)
      });
    }
  });
}());
</script>`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${csp}" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Work Plan — ${trackNameEsc}</title>
  <style>
    :root {
      --bg: var(--vscode-editor-background, #1e1e1e);
      --fg: var(--vscode-foreground, #d4d4d4);
      --border: var(--vscode-panel-border, #333);
      --card-bg: var(--vscode-sideBar-background, #252526);
      --pill-open-bg: #1e3a5f;
      --pill-open-fg: #60a5fa;
      --pill-closed-bg: #1a2e1a;
      --pill-closed-fg: #86efac;
      --chip-bg: #3b1f1f;
      --chip-fg: #fca5a5;
      --step-bg: #1e2d3d;
      --step-fg: #93c5fd;
      --link: var(--vscode-textLink-foreground, #4fc1ff);
    }
    * { box-sizing: border-box; }
    body {
      background: var(--bg);
      color: var(--fg);
      font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
      font-size: var(--vscode-font-size, 13px);
      margin: 0;
      padding: 12px 16px;
    }
    h1 { font-size: 1.1em; margin: 0 0 12px 0; }
    h2 { font-size: 1em; margin: 16px 0 8px 0; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
    .graph-header {
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin: 16px 0 8px 0;
      border-bottom: 1px solid var(--border);
      padding-bottom: 4px;
    }
    .graph-header h2 { margin: 0; border: none; padding: 0; }
    .focus-toggle {
      font-size: 0.8em;
      padding: 2px 8px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--card-bg);
      color: var(--link);
      cursor: pointer;
      flex-shrink: 0;
    }
    .mermaid {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 12px;
      overflow: auto;
    }
    .detail-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 12px;
      margin-top: 12px;
    }
    .rollup { margin: 0 0 8px 0; }
    table.issues {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95em;
    }
    table.issues th, table.issues td {
      text-align: left;
      padding: 4px 6px;
      border-bottom: 1px solid var(--border);
    }
    table.issues th { opacity: 0.7; font-weight: 600; }
    .num { white-space: nowrap; }
    .who { white-space: nowrap; opacity: 0.8; }
    .pill {
      display: inline-block;
      padding: 1px 6px;
      border-radius: 10px;
      font-size: 0.85em;
      font-weight: 600;
    }
    .pill.open   { background: var(--pill-open-bg);   color: var(--pill-open-fg); }
    .pill.closed { background: var(--pill-closed-bg); color: var(--pill-closed-fg); }
    .blockers { margin-top: 8px; }
    .chip {
      display: inline-block;
      background: var(--chip-bg);
      color: var(--chip-fg);
      padding: 2px 8px;
      border-radius: 12px;
      margin: 2px;
      font-size: 0.9em;
    }
    .next-up { margin-top: 8px; }
    .step {
      display: inline-block;
      background: var(--step-bg);
      color: var(--step-fg);
      padding: 2px 8px;
      border-radius: 12px;
      margin: 2px;
      font-size: 0.9em;
    }
  </style>
</head>
<body>
  <h1>Track: ${trackNameEsc}</h1>

  <div class="graph-header">
    <h2>Dependency graph</h2>
    <button id="work-plan-focus-toggle" class="focus-toggle">${toggleLabel}</button>
  </div>
  <pre class="mermaid">${graphDef}</pre>

  <h2>Detail</h2>
  <div class="detail-card">
    ${detailHtml}
  </div>

  ${loaderScript}
  ${messagingScript}
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

/** Escapes HTML special characters for embedding in text nodes and attributes. */
function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
