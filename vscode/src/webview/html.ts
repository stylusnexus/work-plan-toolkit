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
   * Whether the selected track has a resolvable .md path in the export (#211).
   * true  → the header's "Open file" button is enabled (posts openTrackFile).
   * false → the button renders disabled with an explanatory tooltip, so the
   *         affordance stays visible on a path-less / stale export rather than
   *         vanishing. The webview never sees the path itself — resolution and
   *         opening happen host-side in panel.ts / the command handler.
   */
  hasTrackFile: boolean;
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
  /**
   * Whether the editor is on a dark (or high-contrast-dark) colour theme.
   * Drives the Mermaid theme so the graph follows the editor instead of being
   * hardcoded dark (#207). Detail-card colours adapt via --vscode-* tokens and
   * don't need this flag.
   */
  isDark: boolean;
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
  const { cspSource, nonce, mermaidUri, graphDef, detailHtml, isModule, focused, isDark, hasTrackFile } = o;
  const trackNameEsc = esc(o.trackName);

  // Header "Open file" button. Text label (not a $(codicon) — the codicon font
  // isn't loaded in this webview; the package.json command keeps the icon for
  // the native tree menu). Disabled state stays visible per the UX review.
  const openFileButton = hasTrackFile
    ? `<button id="work-plan-open-file" class="open-file-btn" title="Open this track's markdown file in an editor">Open file</button>`
    : `<button class="open-file-btn" disabled aria-disabled="true" title="Track file path not available — try refreshing the view">Open file</button>`;
  // Mermaid can't read CSS vars inside its own SVG, so pick its built-in theme
  // from the editor's light/dark kind instead of hardcoding "dark" (#207).
  const mermaidTheme = isDark ? "dark" : "default";

  // CSP: no network; scripts only via nonce or from cspSource; wasm for mermaid.
  const csp = [
    `default-src 'none'`,
    `img-src ${cspSource} data:`,
    `style-src ${cspSource} 'unsafe-inline'`,
    `font-src ${cspSource} data:`,
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
  // After Mermaid renders the SVG, signal the controller (#216) so it can wire
  // pan/zoom/export to the now-present <svg>. Promise.resolve() guards a mermaid
  // build whose run() is synchronous; a render failure still must not throw.
  const afterRun = `Promise.resolve(mermaid.run()).then(function () { document.dispatchEvent(new Event("workplan:graph-rendered")); }).catch(function () { document.dispatchEvent(new Event("workplan:graph-rendered")); });`;
  if (isModule) {
    loaderScript = `${scriptOpenTag}
import mermaid from "${mermaidUri}";
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "${mermaidTheme}" });
${afterRun}
</script>`;
  } else {
    loaderScript = `<script nonce="${nonce}" src="${mermaidUri}"></script>
<script nonce="${nonce}">
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "${mermaidTheme}" });
${afterRun}
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

  // Open-file button (absent when disabled — no id, so no handler binds).
  var openFileBtn = document.getElementById("work-plan-open-file");
  if (openFileBtn) {
    openFileBtn.addEventListener("click", function () {
      post({ type: "openTrackFile" });
    });
  }

  // Set Next-Up button in the detail panel next-up section.
  var setNextBtn = document.getElementById("work-plan-set-next");
  if (setNextBtn) {
    setNextBtn.addEventListener("click", function () {
      post({ type: "setNextUp" });
    });
  }

  // Track selector buttons
  document.addEventListener("click", function (e) {
    var target = e.target;
    if (!target) { return; }

    // Milestone filter button → apply that milestone's lens to the whole view
    var msFilter = target.closest(".milestone-filter-btn");
    if (msFilter) {
      post({ type: "filterMilestone", milestone: msFilter.getAttribute("data-milestone") });
      return;
    }

    // Move button
    var moveBtn = target.closest(".move-btn");
    if (moveBtn) {
      var issueNum = parseInt(moveBtn.getAttribute("data-move"), 10);
      if (issueNum) { post({ type: "moveIssue", number: issueNum }); }
      return;
    }

    // Plan-open button → open the track's linked plan doc (#285)
    var planBtn = target.closest(".plan-open");
    if (planBtn) {
      post({ type: "openPlan" });
      return;
    }

    // Close-on-GitHub button → close the issue (#305)
    var closeBtn = target.closest(".close-issue-btn");
    if (closeBtn) {
      var closeNum = parseInt(closeBtn.getAttribute("data-close"), 10);
      if (closeNum) { post({ type: "closeIssue", number: closeNum }); }
      return;
    }

    // In-progress toggle button → mark or clear the in-progress label (#271 B4)
    var ipBtn = target.closest("[data-inprogress]");
    if (ipBtn) {
      var ipNum = parseInt(ipBtn.getAttribute("data-inprogress"), 10);
      var ipClear = ipBtn.getAttribute("data-clear") === "1";
      if (ipNum) { post({ type: "toggleInProgress", number: ipNum, clear: ipClear }); }
      return;
    }

    // Milestone band collapse toggle (keyboard-operable <button>)
    var msToggle = target.closest(".milestone-toggle-btn");
    if (msToggle) {
      var band = msToggle.closest(".milestone-band");
      if (band) {
        var collapsed = band.classList.toggle("collapsed");
        msToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      }
      return;
    }

    // Issue-cap "Show all" disclosure toggle
    var capToggle = target.closest(".issue-cap-toggle");
    if (capToggle) {
      var capBand = capToggle.closest(".issue-cap-band");
      if (capBand) {
        var capCollapsed = capBand.classList.toggle("collapsed");
        capToggle.setAttribute("aria-expanded", capCollapsed ? "false" : "true");
      }
      return;
    }

    // Dep disclosure toggle (#257 B3) — pure DOM, no postMessage.
    // Finds the dep-toggle-btn by data-depissue, then the sibling dep-detail-row.
    var depToggle = target.closest(".dep-toggle-btn");
    if (depToggle) {
      var depIssue = depToggle.getAttribute("data-depissue");
      var depRow = document.querySelector(".dep-detail-row[data-depissue=\"" + depIssue + "\"]");
      if (depRow) {
        var depHidden = depRow.hasAttribute("hidden");
        if (depHidden) { depRow.removeAttribute("hidden"); } else { depRow.setAttribute("hidden", ""); }
        depToggle.setAttribute("aria-expanded", depHidden ? "true" : "false");
      }
      return;
    }

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

  // -------------------------------------------------------------------------
  // Dependency-graph pan / zoom / fit / export (#216). Vanilla — no extra dep,
  // CSP-clean (this script already carries the nonce). Wired after Mermaid
  // finishes rendering (the loader dispatches "workplan:graph-rendered").
  // -------------------------------------------------------------------------
  function setupGraphControls() {
    var figure = document.querySelector(".graph-figure");
    var svg = figure ? figure.querySelector("svg") : null;
    if (!figure || !svg) { return; }

    var state = { scale: 1, tx: 0, ty: 0 };
    function clamp(s) { return Math.min(8, Math.max(0.1, s)); }
    function apply() {
      svg.style.transform = "translate(" + state.tx + "px," + state.ty + "px) scale(" + state.scale + ")";
    }
    function zoomAt(factor, cx, cy) {
      var ns = clamp(state.scale * factor);
      var r = ns / state.scale;
      state.tx = cx - r * (cx - state.tx);
      state.ty = cy - r * (cy - state.ty);
      state.scale = ns;
      apply();
    }
    // Intrinsic graph size from the SVG viewBox (Mermaid always emits one);
    // fall back to the rendered box divided by the current scale.
    function graphSize() {
      var vb = svg.viewBox && svg.viewBox.baseVal;
      if (vb && vb.width > 0 && vb.height > 0) { return { w: vb.width, h: vb.height }; }
      var r = svg.getBoundingClientRect();
      return { w: r.width / state.scale, h: r.height / state.scale };
    }
    function fit() {
      var box = figure.getBoundingClientRect();
      var g = graphSize();
      var pad = 24;
      var s = clamp(Math.min((box.width - pad) / g.w, (box.height - pad) / g.h));
      state.scale = s;
      state.tx = Math.max(pad / 2, (box.width - g.w * s) / 2);
      state.ty = pad / 2;
      apply();
    }
    function reset() { state.scale = 1; state.tx = 0; state.ty = 0; apply(); }

    figure.addEventListener("wheel", function (e) {
      e.preventDefault();
      var r = figure.getBoundingClientRect();
      zoomAt(e.deltaY < 0 ? 1.12 : 0.89, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });

    var dragging = false, lastX = 0, lastY = 0;
    figure.addEventListener("pointerdown", function (e) {
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      figure.classList.add("grabbing");
      try { figure.setPointerCapture(e.pointerId); } catch (err) {}
    });
    figure.addEventListener("pointermove", function (e) {
      if (!dragging) { return; }
      state.tx += e.clientX - lastX; state.ty += e.clientY - lastY;
      lastX = e.clientX; lastY = e.clientY; apply();
    });
    function endDrag() { dragging = false; figure.classList.remove("grabbing"); }
    figure.addEventListener("pointerup", endDrag);
    figure.addEventListener("pointercancel", endDrag);

    function on(id, fn) {
      var el = document.getElementById(id);
      if (el) { el.addEventListener("click", fn); }
    }
    function center() { var r = figure.getBoundingClientRect(); return [r.width / 2, r.height / 2]; }
    on("graph-zoom-in", function () { var c = center(); zoomAt(1.2, c[0], c[1]); });
    on("graph-zoom-out", function () { var c = center(); zoomAt(0.8, c[0], c[1]); });
    on("graph-fit", fit);
    on("graph-reset", reset);

    // Export: clone the SVG, strip our live transform, serialize. PNG rasterizes
    // the cloned SVG onto a canvas (self-contained SVG → canvas isn't tainted).
    function cleanSvg() {
      var clone = svg.cloneNode(true);
      clone.style.transform = "";
      clone.removeAttribute("style");
      var g = graphSize();
      clone.setAttribute("width", g.w);
      clone.setAttribute("height", g.h);
      // Mermaid's SVG already carries the xmlns namespace; cloneNode preserves
      // it, so we don't re-add the literal (keeping the doc free of network URLs).
      return new XMLSerializer().serializeToString(clone);
    }
    on("graph-export-svg", function () {
      post({ type: "exportGraph", format: "svg", data: cleanSvg() });
    });
    on("graph-export-png", function () {
      var g = graphSize();
      var scale = 2; // 2x for a crisp raster
      var svgStr = cleanSvg();
      var url = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svgStr)));
      var img = new Image();
      img.onload = function () {
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(g.w * scale));
        canvas.height = Math.max(1, Math.round(g.h * scale));
        var ctx = canvas.getContext("2d");
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0);
        post({ type: "exportGraph", format: "png", data: canvas.toDataURL("image/png") });
      };
      img.onerror = function () { post({ type: "exportGraph", format: "svg", data: svgStr }); };
      img.src = url;
    });

    fit(); // initial fit-to-width so a dense map is navigable from the start
  }

  document.addEventListener("workplan:graph-rendered", setupGraphControls);
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
      /* Semantic colours follow the editor theme via --vscode-charts-* tokens;
         backgrounds are a faint tint of the same token so they read on both
         light and dark themes (#207). Hex fallbacks keep it sane if a theme
         omits a chart token. The text label (open/closed, #num) carries the
         meaning too, so colour is never the sole signal. */
      --pill-open-fg: var(--vscode-charts-blue, #4fa3ff);
      --pill-open-bg: color-mix(in srgb, var(--pill-open-fg) 18%, transparent);
      --pill-closed-fg: var(--vscode-charts-green, #3fa45e);
      --pill-closed-bg: color-mix(in srgb, var(--pill-closed-fg) 18%, transparent);
      --chip-fg: var(--vscode-charts-red, #e05252);
      --chip-bg: color-mix(in srgb, var(--chip-fg) 18%, transparent);
      --step-fg: var(--vscode-charts-blue, #4fa3ff);
      --step-bg: color-mix(in srgb, var(--step-fg) 18%, transparent);
      --depends-fg: var(--vscode-charts-yellow, #d6a012);
      --depends-bg: color-mix(in srgb, var(--depends-fg) 18%, transparent);
      --dep-blocking-fg: var(--vscode-charts-purple, #b267e6);
      --dep-blocking-bg: color-mix(in srgb, var(--dep-blocking-fg) 18%, transparent);
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
    .track-header { display: flex; align-items: center; gap: 10px; margin: 0 0 12px 0; }
    .track-header h1 { margin: 0; }
    .open-file-btn {
      font-size: 0.8em;
      padding: 2px 8px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--card-bg);
      color: var(--link);
      cursor: pointer;
      flex-shrink: 0;
    }
    .open-file-btn[disabled] { opacity: 0.5; cursor: default; color: var(--fg); }
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
    /* Zoom / fit / export controls (#216). margin-left:auto pushes the group to
       the right edge of the header; each button is small + keyboard-focusable. */
    .graph-controls { display: flex; gap: 4px; margin-left: auto; flex-shrink: 0; }
    .graph-ctl {
      font-size: 0.8em;
      min-width: 28px;
      padding: 2px 8px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--card-bg);
      color: var(--fg);
      cursor: pointer;
    }
    .graph-ctl:hover { color: var(--link); border-color: var(--link); }
    .graph-ctl:focus-visible { outline: 2px solid var(--link); outline-offset: 1px; }
    /* The graph-figure is the pan/zoom VIEWPORT (#216): fixed-height, clipped,
       grab cursor. The card chrome moved here from .mermaid so the SVG can be
       transformed freely inside without fighting padding/scrollbars. */
    .graph-figure {
      position: relative;
      height: 60vh;
      min-height: 280px;
      overflow: hidden;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      cursor: grab;
      touch-action: none;
    }
    .graph-figure.grabbing { cursor: grabbing; }
    .mermaid {
      padding: 12px;
      /* svg is positioned + transformed by the pan/zoom controller; origin at
         top-left so button/wheel zoom math is simple. */
    }
    .mermaid svg { transform-origin: 0 0; max-width: none; will-change: transform; }
    .detail-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 12px;
      margin-top: 12px;
    }
    .rollup { margin: 0 0 4px 0; }
    /* Closed/total progress bar (#220). Filled = the canonical progress token
       (vivid in every theme); track = a faint foreground tint with a panel
       border so its extent stays visible even when the tint washes out. The
       numeric meaning lives in the rollup text + aria-label, not the colour. */
    .progress {
      height: 4px;
      margin: 0 0 10px 0;
      border-radius: 2px;
      overflow: hidden;
      background: color-mix(in srgb, var(--vscode-foreground) 12%, transparent);
      border: 1px solid var(--vscode-panel-border, var(--border));
    }
    .progress-fill {
      height: 100%;
      background: var(--vscode-progressBar-background, #0e70c0);
    }
    @media (forced-colors: active) {
      .progress { background: Canvas; border: 1px solid CanvasText; }
      .progress-fill { background: Highlight; }
    }
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
    /* Use the theme-tuned de-emphasized token directly rather than opacity —
       opacity compounds on an already-reduced foreground and can dip below
       4.5:1 in dark themes (a11y pass). */
    table.issues th { color: var(--vscode-descriptionForeground); font-weight: 600; }
    .num { white-space: nowrap; }
    .who { white-space: nowrap; color: var(--vscode-descriptionForeground); }
    .pill {
      display: inline-block;
      padding: 1px 6px;
      border-radius: 10px;
      font-size: 0.85em;
      font-weight: 600;
    }
    .pill.open        { background: var(--pill-open-bg);   color: var(--pill-open-fg); }
    .pill.closed      { background: var(--pill-closed-bg); color: var(--pill-closed-fg); }
    .pill.in-progress { background: var(--vscode-charts-orange, #d18616); color: var(--vscode-editor-background); }
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
    .depends-on { margin-top: 8px; }
    /* A real <button> (keyboard-operable, #244) styled as the old chip. */
    .depends-chip {
      display: inline-block;
      background: var(--depends-bg);
      color: var(--depends-fg);
      border: none;
      padding: 2px 8px;
      border-radius: 12px;
      margin: 2px;
      font: inherit;
      font-size: 0.9em;
      cursor: pointer;
      text-decoration: underline;
    }
    .depends-chip:hover { opacity: 0.8; }
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
    .milestone-band-header td {
      background: var(--bg);
      border-bottom: 1px solid var(--border);
      padding: 6px 6px;
      user-select: none;
    }
    /* Both band-header controls are real <button>s (keyboard-operable); strip
       the native chrome so they read as the old inline header. */
    /* The whole caret+name+count is the collapse button — left-aligned, no chrome. */
    .milestone-toggle-btn {
      background: none;
      border: none;
      color: inherit;
      font: inherit;
      cursor: pointer;
      padding: 0;
      text-align: left;
    }
    /* The filter control reads as a distinct, explicit affordance (a small pill),
       not a second click target hiding in the header text (#248). */
    .milestone-filter-btn {
      background: none;
      border: 1px solid var(--border);
      border-radius: 10px;
      color: var(--link);
      cursor: pointer;
      font: inherit;
      font-size: 0.8em;
      margin-left: 8px;
      padding: 0 7px;
      vertical-align: 1px;
    }
    .milestone-filter-btn:hover { background: var(--card-bg); }
    .milestone-toggle {
      display: inline-block;
      transition: transform 0.15s;
      font-size: 0.85em;
      margin-right: 2px;
    }
    .milestone-band:not(.collapsed) .milestone-toggle { transform: rotate(90deg); }
    .milestone-count {
      color: var(--vscode-descriptionForeground);
      font-weight: normal;
      margin-left: 4px;
    }
    .milestone-band.collapsed tr:not(.milestone-band-header) { display: none; }
    .move-col { width: 56px; text-align: center; white-space: nowrap; }
    .move-btn, .close-issue-btn, .inprogress-btn {
      background: none;
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--link);
      cursor: pointer;
      font-size: 0.85em;
      padding: 0 4px;
      /* Legible at rest (was 0.65 → too faint for low-vision users on dark, the
         reported issue); hover/focus still bumps to full as an emphasis cue. */
      opacity: 0.9;
      transition: opacity 0.1s;
    }
    /* Reveal on row-hover AND on keyboard focus — never opacity:0, or the
       button is invisible to keyboard/touch/AT users (#214). */
    tr:hover .move-btn, tr:hover .close-issue-btn, tr:hover .inprogress-btn,
    .move-btn:focus, .move-btn:focus-visible,
    .close-issue-btn:focus, .close-issue-btn:focus-visible,
    .inprogress-btn:focus, .inprogress-btn:focus-visible { opacity: 1; }
    .move-btn:hover, .close-issue-btn:hover, .inprogress-btn:hover { background: var(--card-bg); }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .issue-cap-band.collapsed tr:not(.issue-cap-row) { display: none; }
    .issue-cap-row td {
      background: var(--bg);
      border-bottom: 1px solid var(--border);
      padding: 6px;
    }
    .issue-cap-toggle {
      background: none;
      border: none;
      color: var(--link);
      cursor: pointer;
      font: inherit;
      padding: 0;
      text-align: left;
    }
    .issue-cap-toggle:hover { text-decoration: underline; }
    .issue-cap-marker {
      display: inline-block;
      transition: transform 0.15s;
      font-size: 0.85em;
      margin-right: 2px;
    }
    .issue-cap-band:not(.collapsed) .issue-cap-marker { transform: rotate(90deg); }
    /* Dep disclosure button (#257 B3): inline in the title cell, chrome-free like
       the other inline action buttons; keyboard-operable as a real <button>. */
    .dep-toggle-btn {
      background: none;
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--link);
      cursor: pointer;
      font-size: 0.85em;
      padding: 0 4px;
      opacity: 0.9;
      margin-left: 4px;
      transition: opacity 0.1s;
    }
    .dep-toggle-btn:hover, .dep-toggle-btn:focus, .dep-toggle-btn:focus-visible { opacity: 1; background: var(--card-bg); }
    /* Dep detail sub-row — hidden by default; revealed when dep-toggle-btn is clicked. */
    .dep-detail-row td { padding: 4px 6px 6px 24px; background: var(--bg); border-bottom: 1px solid var(--border); }
    /* Dep chips: blocked-by reuses chip (red) tokens; blocking uses purple dep tokens. */
    .dep-chip {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      margin: 2px;
      font-size: 0.9em;
      background: var(--chip-bg);
      color: var(--chip-fg);
    }
    .dep-chip--blocking {
      background: var(--dep-blocking-bg);
      color: var(--dep-blocking-fg);
    }
    .dep-chip a { color: inherit; }
    /* Windows High Contrast / forced-colors: the charts-token tints are ignored
       by the forced palette and read as faint washes, so drop them and let the
       system colours + a CanvasText border carry the chip boundary (#207). The
       text label already carries the meaning. */
    @media (forced-colors: active) {
      .pill, .chip, .step, .depends-chip, .dep-chip {
        background: transparent;
        border: 1px solid CanvasText;
      }
      .move-btn, .close-issue-btn, .inprogress-btn { opacity: 1; }
    }

  </style>
</head>
<body>
  <div class="track-header">
  <h1>Track: ${trackNameEsc}</h1>
  ${openFileButton}
  </div>

  <div class="graph-header">
    <h2>Dependency graph</h2>
    <button id="work-plan-focus-toggle" class="focus-toggle">${toggleLabel}</button>
    <div class="graph-controls" role="group" aria-label="Graph zoom and export controls">
      <button type="button" class="graph-ctl" id="graph-zoom-out" title="Zoom out" aria-label="Zoom out">&minus;</button>
      <button type="button" class="graph-ctl" id="graph-zoom-in" title="Zoom in" aria-label="Zoom in">+</button>
      <button type="button" class="graph-ctl" id="graph-fit" title="Fit graph to width" aria-label="Fit graph to width">Fit</button>
      <button type="button" class="graph-ctl" id="graph-reset" title="Reset to 100%" aria-label="Reset zoom to 100 percent">100%</button>
      <button type="button" class="graph-ctl" id="graph-export-svg" title="Export graph as SVG" aria-label="Export graph as SVG">SVG</button>
      <button type="button" class="graph-ctl" id="graph-export-png" title="Export graph as PNG" aria-label="Export graph as PNG">PNG</button>
    </div>
  </div>
  <div class="graph-figure" role="img" aria-label="Dependency graph for ${trackNameEsc}">
    <pre class="mermaid">${graphDef}</pre>
  </div>

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
// Shared helpers
// ---------------------------------------------------------------------------

/**
 * Escapes the five HTML special characters (`& < > " '`) for safe embedding in
 * text nodes and attribute values. Exported so every webview sink uses the same
 * full 5-char escaper rather than ad-hoc 3-char variants.
 */
export function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
