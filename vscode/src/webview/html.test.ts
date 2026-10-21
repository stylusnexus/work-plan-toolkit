/**
 * Tests for src/webview/html.ts — pure HTML/CSP builder.
 *
 * All assertions are offline; no vscode import anywhere in this test or the
 * module under test.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildHtml, buildHtmlIfChanged } from "./html.ts";
import type { WebviewHtmlOptions } from "./html.ts";
import type { GraphMode } from "./messages.ts";
import type { Export, Track } from "../model.ts";
import { trackKey } from "../model.ts";
import { toMermaid } from "./graph.ts";
import { renderDetail } from "./detail.ts";
import { makeIssue } from "../testFixtures.ts";
import { makeTrack } from "../testFixtures.ts";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const BASE: WebviewHtmlOptions = {
  cspSource: "vscode-resource:",
  nonce: "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
  mermaidUri: "vscode-resource:/ext/dist/mermaid.min.js",
  graphDef: "graph LR\n  t_alpha --> t_beta",
  detailHtml: '<p class="rollup"><b>3</b> open &middot; <b>2</b> closed</p>',
  trackName: "alpha",
  isModule: false,
  mode: "full",
  isDark: true,
  hasTrackFile: true,
};

// ---------------------------------------------------------------------------
// CSP tests
// ---------------------------------------------------------------------------

describe("buildHtml — CSP meta tag", () => {
  it("contains Content-Security-Policy meta tag", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes("Content-Security-Policy"),
      `Missing CSP meta tag:\n${html.slice(0, 500)}`,
    );
  });

  it("CSP includes default-src 'none'", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes("default-src 'none'"),
      `CSP must have default-src 'none':\n${html.slice(0, 800)}`,
    );
  });

  it("CSP locks down sources: default-src 'none' + nonce'd script-src, no network", () => {
    const html = buildHtml(BASE);
    // Directly assert the CSP shape (always runs — no conditional branch).
    assert.ok(
      html.includes("default-src 'none'"),
      `CSP must include default-src 'none':\n${html.slice(0, 800)}`,
    );
    assert.ok(
      html.includes(`script-src 'nonce-${BASE.nonce}'`),
      `script-src must begin with the nonce source:\n${html.slice(0, 800)}`,
    );
    // The whole document must reference no http/https URLs (no CDN/network).
    // The test fixture's mermaidUri is vscode-resource:, so this holds.
    assert.ok(
      !html.includes("http://"),
      `Document must not reference http:// URLs`,
    );
    assert.ok(
      !html.includes("https://"),
      `Document must not reference https:// URLs`,
    );
  });

  it("script-src includes the nonce", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes(`'nonce-${BASE.nonce}'`),
      `script-src must include nonce-<value>:\n${html.slice(0, 800)}`,
    );
  });

  it("script-src includes 'wasm-unsafe-eval'", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes("'wasm-unsafe-eval'"),
      `script-src must include wasm-unsafe-eval for mermaid:\n${html.slice(0, 800)}`,
    );
  });
});

// ---------------------------------------------------------------------------
// Nonce completeness — every <script must carry the nonce
// ---------------------------------------------------------------------------

describe("buildHtml — nonce on every script element", () => {
  it("every <script occurrence has nonce=\"<nonce>\" (UMD path)", () => {
    const html = buildHtml({ ...BASE, isModule: false });
    assertAllScriptsHaveNonce(html, BASE.nonce);
  });

  it("every <script occurrence has nonce=\"<nonce>\" (ESM path)", () => {
    const html = buildHtml({ ...BASE, isModule: true });
    assertAllScriptsHaveNonce(html, BASE.nonce);
  });

  it("there is at least one <script element", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("<script"), "Expected at least one <script element");
  });
});

// ---------------------------------------------------------------------------
// Content embedding
// ---------------------------------------------------------------------------

describe("buildHtml — graphDef embedding", () => {
  it("graphDef appears verbatim inside the output", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes(BASE.graphDef),
      `graphDef missing from output:\n${html.slice(0, 1000)}`,
    );
  });

  it("graphDef is inside a <pre class=\"mermaid\" …> element", () => {
    const html = buildHtml(BASE);
    // The pre.mermaid wraps graphDef (now carries a11y attrs, so match the prefix).
    const preStart = html.indexOf('<pre class="mermaid"');
    const preEnd = html.indexOf("</pre>");
    assert.ok(preStart !== -1, "Missing <pre class=\"mermaid\"> element");
    assert.ok(preEnd > preStart, "Missing </pre> after mermaid pre");
    const inside = html.slice(preStart, preEnd);
    assert.ok(
      inside.includes(BASE.graphDef),
      `graphDef not inside the mermaid <pre>: ${inside.slice(0, 300)}`,
    );
  });

  it("the mermaid graph has a text alternative on a wrapper that survives mermaid.run() (#217/#244)", () => {
    const html = buildHtml({ ...BASE, trackName: "platform-health" });
    // The alt text lives on a parent <div>, not the <pre> — Mermaid replaces the
    // <pre>'s content with its own SVG, so a label on the pre would be lost.
    assert.ok(
      html.includes('<div class="graph-figure" role="img" aria-label="Dependency graph for platform-health">'),
      `graph wrapper missing role/aria-label:\n${html}`,
    );
    // The pre itself no longer carries role/aria-label (avoids nested role=img).
    assert.ok(!/<pre class="mermaid"[^>]*role=/.test(html), "pre should not carry role anymore");
  });

  it("the move button reveals on focus, not just hover (#214)", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes(".move-btn:focus") && html.includes(".move-btn:focus-visible"),
      "move-btn must reveal on :focus / :focus-visible, not hover-only",
    );
    // Resting state is dim-but-visible, never fully transparent.
    assert.ok(!/\.move-btn\s*\{[^}]*opacity:\s*0;/.test(html), "move-btn must not rest at opacity:0");
  });

  it("renders keyboard-operable zoom/fit/export controls (#216)", () => {
    const html = buildHtml(BASE);
    for (const id of ["graph-zoom-out", "graph-zoom-in", "graph-fit", "graph-reset", "graph-export-svg", "graph-export-png"]) {
      assert.ok(html.includes(`id="${id}"`), `missing control button #${id}`);
    }
    // Real <button>s with aria-labels (keyboard + screen-reader operable), and a
    // labelled group wrapper.
    assert.ok(html.includes('class="graph-controls" role="group"'), "controls need a labelled group");
    assert.ok(/<button type="button" class="graph-ctl"[^>]*aria-label=/.test(html), "control buttons need aria-labels");
  });

  it("wires the controller to a post-render hook (#216)", () => {
    const html = buildHtml(BASE);
    // The loader signals render-completion; the messaging IIFE listens for it.
    assert.ok(html.includes('dispatchEvent(new Event("workplan:graph-rendered"))'), "loader must signal render done");
    assert.ok(html.includes('addEventListener("workplan:graph-rendered"'), "controller must listen for render done");
  });

  it("the loader marks the render done before it signals", () => {
    const html = buildHtml(BASE);
    const flag = html.indexOf("window.__workplanGraphRendered = true");
    assert.ok(flag !== -1, "loader must set the done flag");
    assert.ok(flag < html.indexOf('dispatchEvent(new Event("workplan:graph-rendered"))'));
  });
});

// ---------------------------------------------------------------------------
// Graph controls, run against a minimal fake DOM (#216 race, zoom base, tooltips)
// ---------------------------------------------------------------------------

type Listener = (e?: unknown) => void;
interface FakeEl {
  id: string; isConnected: boolean; children: FakeEl[]; tag: string;
  attrs: Record<string, string>; style: Record<string, string>; textContent: string;
  listeners: Record<string, Listener[]>;
  viewBox?: { baseVal: { width: number; height: number } };
  namespaceURI?: string;
}

function fakeEl(tag: string, extra: Partial<FakeEl> = {}): FakeEl {
  return { id: "", isConnected: true, children: [], tag, attrs: {}, style: {}, textContent: "", listeners: {}, ...extra };
}

/** Runs the messaging IIFE with a fake document; returns hooks to drive it. */
function runControls(
  html: string,
  opts: { flagSetEarly?: boolean; vb?: [number, number]; nodeIds?: string[]; throwOnTitle?: boolean } = {},
) {
  const bodies = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)]
    .filter(m => !/\bsrc=/.test(m[1]) && m[2].includes("setupGraphControls"))
    .map(m => m[2]);
  assert.equal(bodies.length, 1, "messaging script not found");
  const nodes = (opts.nodeIds ?? ["mermaid-1-flowchart-i_7-0", "mermaid-1-flowchart-i_8-1"]).map(id => fakeEl("g", { id }));
  const [vbW, vbH] = opts.vb ?? [2000, 1000];
  const finalSvg = fakeEl("svg", {
    viewBox: { baseVal: { width: vbW, height: vbH } }, namespaceURI: "svg-ns", children: nodes,
  });
  const tempSvg = fakeEl("svg", { viewBox: { baseVal: { width: 0, height: 0 } } });
  let current: FakeEl = tempSvg; // Mermaid's in-progress svg
  const figure = fakeEl("div");
  const docListeners: Record<string, Listener[]> = {};
  const add = (el: FakeEl | null) => (type: string, fn: Listener) => {
    const bag = el ? el.listeners : docListeners;
    (bag[type] ??= []).push(fn);
  };
  const methods = (el: FakeEl): FakeEl => Object.assign(el, {
    addEventListener: add(el),
    setAttribute: (k: string, v: unknown) => { el.attrs[k] = String(v); },
    getAttribute: (k: string) => el.attrs[k] ?? null,
    removeAttribute: (k: string) => { delete el.attrs[k]; },
    insertBefore: (c: FakeEl) => { el.children.unshift(c); },
    appendChild: (c: FakeEl) => { el.children.push(c); },
    classList: { add() {}, remove() {}, toggle() { return false; } },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 540 }),
    setPointerCapture() {},
    querySelectorAll: (sel: string) => (sel === "g.node" ? el.children.filter(c => c.tag === "g") : []),
    querySelector: (sel: string) => {
      if (el === figure && sel.includes("svg")) return methods(current);
      return null;
    },
  });
  methods(figure); methods(finalSvg); methods(tempSvg);
  nodes.forEach(methods);
  const doc = {
    addEventListener: add(null),
    querySelector: (sel: string) => (sel === ".graph-figure" ? figure : sel === ".graph-figure svg" ? current : null),
    querySelectorAll: () => [],
    getElementById: () => null,
    createElementNS: (ns: string, tag: string) => {
      if (opts.throwOnTitle) throw new Error("boom");
      return methods(fakeEl(tag, { namespaceURI: ns }));
    },
    dispatchEvent: () => true,
  };
  const win: Record<string, unknown> = {};
  if (opts.flagSetEarly) { current = finalSvg; win.__workplanGraphRendered = true; }
  new Function("document", "window", bodies[0])(doc, win);
  const errors: unknown[] = [];
  return {
    figure, finalSvg, tempSvg, nodes, errors,
    bound: () => (figure.listeners.wheel ?? []).length,
    wheelUp: () => figure.listeners.wheel[0]({ preventDefault() {}, deltaY: -1, clientX: 500, clientY: 270 }),
    finishRender: () => {
      tempSvg.isConnected = false;
      current = finalSvg;
      win.__workplanGraphRendered = true;
      // Like a browser: a throwing listener is reported, not propagated.
      for (const fn of docListeners["workplan:graph-rendered"] ?? []) {
        try { fn(); } catch (e) { errors.push(e); }
      }
    },
  };
}

describe("buildHtml — graph controls bind to the final svg", () => {
  it("does not bind to Mermaid's temporary svg; binds once when the render finishes", () => {
    const c = runControls(buildHtml(BASE));
    assert.equal(c.bound(), 0, "bound before the render finished");
    c.finishRender();
    assert.equal(c.bound(), 1);
    assert.ok(c.finalSvg.style.transform, "initial fit must transform the final svg");
    assert.equal(c.tempSvg.style.transform, undefined);
    c.finishRender(); // a second signal never binds twice
    assert.equal(c.bound(), 1);
  });

  it("binds immediately when the render finished before the script ran", () => {
    const c = runControls(buildHtml(BASE), { flagSetEarly: true });
    assert.equal(c.bound(), 1);
  });

  it("the same wiring serves focus and full modes", () => {
    for (const mode of ["focus", "full"] as const) {
      const c = runControls(buildHtml({ ...BASE, mode }));
      assert.equal(c.bound(), 0);
      c.finishRender();
      assert.equal(c.bound(), 1, mode);
    }
  });

  it("scale 1 is the viewBox size, and the initial fit uses that same base", () => {
    const c = runControls(buildHtml(BASE));
    c.finishRender();
    assert.equal(c.finalSvg.attrs.width, "2000");
    assert.equal(c.finalSvg.attrs.height, "1000");
    assert.equal(c.finalSvg.style.width, "2000px");
    assert.equal(c.finalSvg.style.maxWidth, "none");
    // figure 1000x540, pad 24: min(976/2000, 516/1000) = 0.488
    assert.match(c.finalSvg.style.transform, /scale\(0\.488\)/);
  });

  it("Fit never enlarges a graph smaller than the viewport", () => {
    const c = runControls(buildHtml(BASE), { vb: [300, 200] });
    c.finishRender();
    assert.match(c.finalSvg.style.transform, /scale\(1\)/);
  });
});

describe("buildHtml — critical node tooltips", () => {
  const hostile = '#7 </script><b>"x"</b> & \u2028 it\'s';
  const crit = (nodeTitles?: Record<string, string>): WebviewHtmlOptions => ({
    ...BASE, mode: "critical", critical: { ...CRIT, ...(nodeTitles ? { nodeTitles } : {}) },
  });

  it("embeds the titles so no title text can break out of the script", () => {
    const html = buildHtml(crit({ i_7: hostile }));
    assert.ok(!html.includes("</script><b>"), "title closed the script");
    assert.ok(html.includes("\\u003c/script\\u003e"));
    const bodies = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)]
      .filter(m => !/\bsrc=/.test(m[1]) && m[2].trim() !== "");
    for (const m of bodies) assert.doesNotThrow(() => { new Function(m[2]); });
  });

  it("puts the full text in an svg <title> on the matching node, as text", () => {
    const c = runControls(buildHtml(crit({ i_7: hostile })));
    c.finishRender();
    const tip = c.nodes[0].children.find(x => x.tag === "title");
    assert.ok(tip, "node i_7 has no <title>");
    assert.equal(tip!.textContent, hostile);
    assert.equal(tip!.namespaceURI, "svg-ns");
    assert.ok(!c.nodes[1].children.some(x => x.tag === "title"), "i_8 has no title entry");
  });

  it("matches plain and prefixed Mermaid node ids", () => {
    const c = runControls(buildHtml(crit({ i_7: "seven" })), {
      nodeIds: ["flowchart-i_7-0", "x-flowchart-i_7-1", "notflowchart-i_7-2"],
    });
    c.finishRender();
    const tip = (k: number) => c.nodes[k].children.find(x => x.tag === "title")?.textContent;
    assert.equal(tip(0), "seven");
    assert.equal(tip(1), "seven");
    assert.equal(tip(2), undefined);
  });

  it("a tooltip error cannot leave the zoom controls dead", () => {
    const c = runControls(buildHtml(crit({ i_7: "seven" })), { throwOnTitle: true });
    c.finishRender();
    assert.equal(c.bound(), 1, "controls not bound");
    const fitted = c.finalSvg.style.transform;
    assert.match(fitted, /scale\(0\.488\)/, "initial fit missing");
    c.wheelUp();
    assert.notEqual(c.finalSvg.style.transform, fitted, "wheel did nothing");
  });

  it("uses textContent, never innerHTML, and strips tooltips from exports", () => {
    const html = buildHtml(crit({ i_7: "x" }));
    assert.ok(html.includes("t.textContent = nodeTitles[m[1]]"));
    assert.ok(!/innerHTML/.test(html));
    assert.ok(html.includes('clone.querySelectorAll("title.wp-tip")'));
  });

  it("focus and full modes carry no titles", () => {
    for (const mode of ["focus", "full"] as const) {
      const html = buildHtml({ ...BASE, mode, critical: { ...CRIT, nodeTitles: { i_7: "SECRET-T" } } });
      assert.ok(!html.includes("SECRET-T"), mode);
    }
  });
});

// ---------------------------------------------------------------------------
// Inline-script syntax (regression guard)
// ---------------------------------------------------------------------------

describe("buildHtml — inline scripts are valid JavaScript", () => {
  // Extract the body of every inline <script> (those WITHOUT a src=) so each can
  // be syntax-checked. The previous string-only assertions never executed the
  // emitted JS, so a `\"` inside the messaging template literal collapsed to a
  // bare `"`, produced adjacent string literals in the querySelector call, and a
  // single parse error killed the ENTIRE messaging IIFE — every webview click
  // handler (track select, focus toggle, graph zoom/pan/export) went dead. A
  // syntax check on the emitted body catches that class of bug.
  function inlineScriptBodies(html: string): string[] {
    const bodies: string[] = [];
    const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(html)) !== null) {
      const attrs = m[1];
      const body = m[2];
      if (/\bsrc=/.test(attrs)) { continue; } // external loader — no inline body
      if (body.trim() === "") { continue; }
      bodies.push(body);
    }
    return bodies;
  }

  // new Function() parses the body without running it, so undefined runtime
  // globals (mermaid, acquireVsCodeApi, document) don't matter — only syntax.
  function assertParses(body: string, label: string): void {
    assert.doesNotThrow(
      () => { new Function(body); },
      (err: unknown) =>
        `inline ${label} is not valid JS: ${(err as Error).message}\n--- body head ---\n${body.slice(0, 200)}`,
    );
  }

  it("every inline <script> parses (UMD path)", () => {
    const bodies = inlineScriptBodies(buildHtml({ ...BASE, isModule: false }));
    assert.ok(bodies.length >= 2, `expected ≥2 inline scripts, got ${bodies.length}`);
    bodies.forEach((b, i) => assertParses(b, `UMD script #${i}`));
  });

  it("the messaging IIFE (with the dep-toggle querySelector) parses", () => {
    // Specifically guards the #257 dep-disclosure selector that broke (#216 was
    // only the symptom users hit first). The body must contain the selector and
    // still parse cleanly.
    const bodies = inlineScriptBodies(buildHtml(BASE));
    const messaging = bodies.find((b) => b.includes("dep-detail-row[data-depissue="));
    assert.ok(messaging, "messaging IIFE with the dep-toggle selector not found");
    assertParses(messaging!, "messaging IIFE");
  });
});

describe("buildHtml — theme adaptivity (#207)", () => {
  it("dark editor → Mermaid initialises with the dark theme", () => {
    const html = buildHtml({ ...BASE, isDark: true });
    assert.ok(html.includes('theme: "dark"'), `expected Mermaid dark theme:\n${html.slice(0, 400)}`);
  });

  it("light editor → Mermaid initialises with the default (light) theme, never hardcoded dark", () => {
    const html = buildHtml({ ...BASE, isDark: false });
    assert.ok(html.includes('theme: "default"'), "expected Mermaid default theme on a light editor");
    assert.ok(!html.includes('theme: "dark"'), "must not hardcode the dark theme");
  });

  it("semantic pill/chip colours come from --vscode-charts-* tokens, not hardcoded hex", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("--vscode-charts-blue"), "pills/steps should use the charts-blue token");
    assert.ok(html.includes("--vscode-charts-red"), "blocker chips should use the charts-red token");
    assert.ok(!html.includes("#1e3a5f") && !html.includes("#3b1f1f"), "old hardcoded pill/chip hex should be gone");
  });
});

describe("buildHtml — detailHtml embedding", () => {
  it("detailHtml appears verbatim in the output", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes(BASE.detailHtml),
      `detailHtml missing from output:\n${html.slice(0, 1000)}`,
    );
  });
});

describe("buildHtml — trackName in heading", () => {
  it("trackName appears in the heading", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes(BASE.trackName),
      `trackName '${BASE.trackName}' missing from output`,
    );
  });

  it("trackName with special chars is HTML-escaped in heading", () => {
    const html = buildHtml({ ...BASE, trackName: "<b>bad & track</b>" });
    assert.ok(
      !html.includes("<b>bad & track</b>"),
      "Raw trackName with HTML tags must be escaped",
    );
    assert.ok(
      html.includes("&lt;b&gt;bad &amp; track&lt;/b&gt;"),
      "Expected escaped trackName in output",
    );
  });
});

// ---------------------------------------------------------------------------
// Mermaid URI loading
// ---------------------------------------------------------------------------

describe("buildHtml — mermaid bundle URI", () => {
  it("UMD path: mermaidUri appears as src of a <script> tag", () => {
    const html = buildHtml({ ...BASE, isModule: false });
    assert.ok(
      html.includes(`src="${BASE.mermaidUri}"`),
      `Expected src="${BASE.mermaidUri}" in UMD script tag:\n${html.slice(0, 800)}`,
    );
  });

  it("ESM path: mermaidUri appears in an import statement", () => {
    const html = buildHtml({ ...BASE, isModule: true });
    assert.ok(
      html.includes(`from "${BASE.mermaidUri}"`),
      `Expected import from "${BASE.mermaidUri}" in ESM script:\n${html.slice(0, 800)}`,
    );
  });

  it("UMD path: no 'import' keyword (global mermaid)", () => {
    const html = buildHtml({ ...BASE, isModule: false });
    // The loader script should NOT use ES module import syntax
    assert.ok(
      !html.includes("import mermaid"),
      "UMD path must not use 'import mermaid'",
    );
  });
});

// ---------------------------------------------------------------------------
// Mermaid initialization
// ---------------------------------------------------------------------------

describe("buildHtml — mermaid.initialize call", () => {
  it("contains mermaid.initialize call", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("mermaid.initialize("), "Expected mermaid.initialize() call");
  });

  it("uses startOnLoad: false", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("startOnLoad: false") || html.includes("startOnLoad:false"), "Expected startOnLoad: false");
  });

  it("uses securityLevel: \"strict\"", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes('securityLevel: "strict"') || html.includes("securityLevel:'strict'") || html.includes('securityLevel:"strict"'),
      "Expected securityLevel strict",
    );
  });

  it("contains mermaid.run() call", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("mermaid.run()"), "Expected mermaid.run() call");
  });
});

// ---------------------------------------------------------------------------
// Webview message protocol
// ---------------------------------------------------------------------------

describe("buildHtml — postMessage protocol", () => {
  it("contains postMessage call for selectTrack", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("selectTrack"), "Expected selectTrack in messaging script");
  });

  it("posts composite data-track-key selections without degrading to a name", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes('target.closest("[data-track-key]")'));
    assert.ok(html.includes('type: "selectTrack", key:'));
    assert.ok(html.includes('getAttribute("data-track-key")'));
  });

  it("contains postMessage call for openIssue", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("openIssue"), "Expected openIssue in messaging script");
  });

  it("acquires the VS Code API", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("acquireVsCodeApi"), "Expected acquireVsCodeApi usage");
  });

  it("acquireVsCodeApi is called exactly once", () => {
    // acquireVsCodeApi() may only be called ONCE per document; a second call
    // throws "already acquired" and aborts that script. Guard against regressions
    // (e.g. a separate toggle IIFE) by asserting a single invocation.
    const html = buildHtml({ ...BASE, mode: "focus" });
    assert.equal((html.match(/acquireVsCodeApi\(/g) || []).length, 1);
  });
});

// ---------------------------------------------------------------------------
// Graph mode buttons + critical-path controls
// ---------------------------------------------------------------------------

const CRIT = {
  trackFilter: null as string | null,
  focusIssueLabel: null as string | null,
  showClosed: false,
  banner: null as string | null,
  legend: [] as { label: string; color: string }[],
  tooLargeMessage: null as string | null,
  autoFilterNote: null as string | null,
  emptyMessage: null as string | null,
  trackOptions: [] as { key: string; label: string }[],
  nodeTitles: undefined as Record<string, string> | undefined,
  showUnlinked: false,
  unlinkedCount: 0,
};

describe("buildHtml — graph mode buttons", () => {
  const MODES = [
    { mode: "focus", id: "work-plan-mode-focus", label: "Focus on track" },
    { mode: "full", id: "work-plan-mode-full", label: "Show full map" },
    { mode: "critical", id: "work-plan-mode-critical", label: "Show critical path" },
  ] as const;

  it("renders all three mode buttons with their labels", () => {
    const html = buildHtml({ ...BASE, mode: "full" });
    for (const m of MODES) {
      assert.ok(html.includes(`id="${m.id}"`), `missing ${m.id}`);
      assert.ok(html.includes(`>${m.label}</button>`), `missing label ${m.label}`);
    }
  });

  it("the old single toggle is gone", () => {
    const html = buildHtml(BASE);
    assert.ok(!html.includes("work-plan-focus-toggle"));
    assert.ok(!html.includes("setFocus"));
  });

  for (const active of MODES) {
    it(`mode=${active.mode} marks only that button aria-pressed=true`, () => {
      const html = buildHtml({ ...BASE, mode: active.mode });
      for (const m of MODES) {
        const re = new RegExp(`<button[^>]*id="${m.id}"[^>]*>`);
        const tag = html.match(re)?.[0] ?? "";
        assert.ok(
          tag.includes(`aria-pressed="${m.mode === active.mode}"`),
          `${m.id} wrong aria-pressed in ${tag}`,
        );
      }
    });
  }

  it("each button carries its mode and one generic handler posts setGraphMode", () => {
    const html = buildHtml(BASE);
    for (const m of MODES) {
      assert.ok(
        new RegExp(`id="${m.id}"[^>]*data-mode="${m.mode}"`).test(html),
        `${m.id} lacks data-mode="${m.mode}"`,
      );
    }
    assert.equal((html.match(/type: 'setGraphMode'/g) || []).length, 1, "handler must not be copied per button");
    assert.ok(html.includes("type: 'setGraphMode', mode: "));
  });

  it("scripts carry the nonce in both module modes", () => {
    assertAllScriptsHaveNonce(buildHtml({ ...BASE, mode: "focus", isModule: false }), BASE.nonce);
    assertAllScriptsHaveNonce(buildHtml({ ...BASE, mode: "critical", isModule: true }), BASE.nonce);
  });
});

describe("buildHtml — critical-path controls", () => {
  const critical = (c: Partial<typeof CRIT> = {}): WebviewHtmlOptions => ({
    ...BASE,
    mode: "critical",
    critical: { ...CRIT, ...c },
  });

  it("absent in focus and full modes, even when critical data is passed", () => {
    for (const mode of ["focus", "full"] as const) {
      const html = buildHtml({
        ...BASE,
        mode,
        critical: { ...CRIT, banner: "BANNER-X", legend: [{ label: "LEG-X", color: "#fff" }] },
      });
      for (const needle of [
        "work-plan-critical-track", "work-plan-focus-issue", "work-plan-clear-focus",
        "work-plan-show-closed", "setCriticalTrackFilter", "pickFocusIssue",
        "clearFocusIssue", "setShowClosed", "BANNER-X", "LEG-X",
      ]) {
        assert.ok(!html.includes(needle), `${needle} leaked into mode=${mode}`);
      }
    }
  });

  it("explains the numbers in critical mode only", () => {
    const hint = "Numbers = steps from startable, not priority.";
    assert.ok(buildHtml(critical()).includes(hint));
    for (const mode of ["focus", "full"] as const) {
      assert.ok(!buildHtml({ ...BASE, mode, critical: CRIT }).includes(hint), mode);
    }
  });

  it("renders the track select, focus buttons and show-closed checkbox", () => {
    const html = buildHtml(critical({
      trackOptions: [{ key: "a/b#one", label: "One" }, { key: "a/b#two", label: "Two" }],
      trackFilter: "a/b#two",
      showClosed: true,
    }));
    assert.ok(html.includes('id="work-plan-critical-track"'));
    assert.ok(html.includes('<option value="">All tracks</option>'));
    assert.ok(html.includes('<option value="a/b#one">One</option>'));
    assert.ok(html.includes('<option value="a/b#two" selected>Two</option>'));
    assert.ok(html.includes("Focus on an issue…"));
    assert.ok(html.includes(">Clear focus</button>"));
    assert.ok(/id="work-plan-show-closed"[^>]*checked/.test(html));
  });

  it("renders the show-unlinked checkbox with its count, off by default, and posts setShowUnlinked", () => {
    const off = buildHtml(critical({ unlinkedCount: 87 }));
    const tag = off.match(/<input[^>]*id="work-plan-show-unlinked"[^>]*>/)?.[0] ?? "";
    assert.ok(tag && !tag.includes("checked"), tag);
    assert.ok(off.includes("Show unlinked issues (87)"));
    assert.ok(off.includes("type: 'setShowUnlinked', show: "));
    assert.ok(/id="work-plan-show-unlinked"[^>]*checked/.test(buildHtml(critical({ showUnlinked: true, unlinkedCount: 3 }))));
    for (const mode of ["focus", "full"] as const) {
      assert.ok(!buildHtml({ ...BASE, mode, critical: CRIT }).includes("work-plan-show-unlinked"), mode);
    }
  });

  it("show-closed checkbox is unchecked when showClosed is false", () => {
    const html = buildHtml(critical({ showClosed: false }));
    const tag = html.match(/<input[^>]*id="work-plan-show-closed"[^>]*>/)?.[0] ?? "";
    assert.ok(tag && !tag.includes("checked"), tag);
  });

  it("the controls post the four critical messages", () => {
    const html = buildHtml(critical());
    assert.ok(html.includes("type: 'setCriticalTrackFilter'"));
    assert.ok(html.includes("type: 'pickFocusIssue'"));
    assert.ok(html.includes("type: 'clearFocusIssue'"));
    assert.ok(html.includes("type: 'setShowClosed'"));
  });

  it("shows the focused issue label escaped", () => {
    const html = buildHtml(critical({ focusIssueLabel: "#5 <b>x</b>" }));
    assert.ok(html.includes("#5 &lt;b&gt;x&lt;/b&gt;"));
    assert.ok(!html.includes("<b>x</b>"));
  });

  it("banner, legend labels, notes and messages render escaped", () => {
    const html = buildHtml(critical({
      banner: "ban <i>ner</i>",
      legend: [{ label: "Blocked <u>by</u>", color: "#ff0000" }],
      tooLargeMessage: "too <s>big</s>",
      autoFilterNote: "note <em>n</em>",
      emptyMessage: "empty <o>",
      trackOptions: [{ key: "k\"1", label: "L<1>" }],
    }));
    for (const raw of ["<i>ner</i>", "<u>by</u>", "<s>big</s>", "<em>n</em>", "<o>", "L<1>", 'value="k"1"']) {
      assert.ok(!html.includes(raw), `unescaped: ${raw}`);
    }
    for (const safe of [
      "ban &lt;i&gt;ner&lt;/i&gt;", "Blocked &lt;u&gt;by&lt;/u&gt;", "too &lt;s&gt;big&lt;/s&gt;",
      "note &lt;em&gt;n&lt;/em&gt;", "empty &lt;o&gt;", "L&lt;1&gt;", 'value="k&quot;1"',
    ]) {
      assert.ok(html.includes(safe), `missing: ${safe}`);
    }
  });

  it("legend shows each label as text next to its colour swatch", () => {
    const html = buildHtml(critical({
      legend: [{ label: "On the path", color: "#e5c07b" }, { label: "Closed", color: "#888888" }],
    }));
    assert.ok(/#e5c07b[^>]*><\/span>\s*On the path/.test(html));
    assert.ok(/#888888[^>]*><\/span>\s*Closed/.test(html));
  });

  it("a colour that is not a plain hex/name is not injected into style", () => {
    const html = buildHtml(critical({ legend: [{ label: "Bad", color: 'red;"><script>x</script>' }] }));
    assert.ok(!html.includes("<script>x</script>"));
  });

  it("the inline scripts still parse with critical controls present", () => {
    const html = buildHtml(critical({ trackOptions: [{ key: "k", label: "L" }] }));
    const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(html)) !== null) {
      if (/\bsrc=/.test(m[1]) || m[2].trim() === "") continue;
      assert.doesNotThrow(() => { new Function(m![2]); });
    }
  });

  it("acquireVsCodeApi is still called exactly once", () => {
    assert.equal((buildHtml(critical()).match(/acquireVsCodeApi\(/g) || []).length, 1);
  });
});

describe("buildHtml — nothing to draw (empty graphDef)", () => {
  const empty = (graphDef: string): WebviewHtmlOptions => ({
    ...BASE, graphDef, mode: "critical",
    critical: {
      ...CRIT, tooLargeMessage: "Too large to draw (9 issues, 600 links).",
      legend: [{ label: "LEG-X", color: "#ffffff" }],
    },
  });

  for (const g of ["", "  \n "]) {
    it(`graphDef ${JSON.stringify(g)}: no mermaid element and no mermaid.run`, () => {
      const html = buildHtml(empty(g));
      assert.ok(!/<\w+[^>]*class="mermaid"/.test(html), "mermaid element emitted");
      assert.ok(!html.includes("mermaid.run()).then"), "mermaid.run still called");
      assert.ok(!html.includes("mermaid.initialize("), "mermaid still initialised");
      assert.ok(!html.includes(`src="${BASE.mermaidUri}"`), "mermaid bundle still loaded");
      assert.ok(html.includes("Too large to draw"), "message must still show");
    });
  }

  it("zoom and export controls are disabled, so nothing posts empty data", () => {
    const html = buildHtml(empty(""));
    for (const id of ["graph-zoom-out", "graph-zoom-in", "graph-fit", "graph-reset", "graph-export-svg", "graph-export-png"]) {
      const tag = html.match(new RegExp(`<button[^>]*id="${id}"[^>]*>`))?.[0] ?? "";
      assert.ok(/\sdisabled\b/.test(tag), `${id} not disabled: ${tag}`);
    }
  });

  it("the legend is hidden when nothing is drawn", () => {
    assert.ok(!buildHtml(empty("")).includes("LEG-X"));
    assert.ok(buildHtml({ ...empty("graph LR\n  a --> b") }).includes("LEG-X"));
  });

  it("a non-empty graphDef still renders the mermaid element and runs mermaid", () => {
    const html = buildHtml(empty("graph LR\n  a --> b"));
    assert.ok(html.includes('<pre class="mermaid">graph LR'));
    assert.ok(html.includes("mermaid.run()).then"));
    const tag = html.match(/<button[^>]*id="graph-export-svg"[^>]*>/)?.[0] ?? "";
    assert.ok(!/\sdisabled\b/.test(tag), tag);
  });

  it("inline scripts still parse with nothing to draw", () => {
    const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/g;
    const html = buildHtml(empty(""));
    let m: RegExpExecArray | null;
    let n = 0;
    while ((m = re.exec(html)) !== null) {
      if (/\bsrc=/.test(m[1]) || m[2].trim() === "") continue;
      n++;
      assert.doesNotThrow(() => { new Function(m![2]); });
    }
    assert.ok(n >= 1);
  });
});

describe("buildHtmlIfChanged — critical-path inputs (#423)", () => {
  const base: WebviewHtmlOptions = { ...BASE, mode: "critical", critical: { ...CRIT } };
  const first = buildHtmlIfChanged(null, base)!;
  const withCrit = (c: Partial<typeof CRIT>): WebviewHtmlOptions =>
    ({ ...base, critical: { ...CRIT, ...c } });

  it("same inputs, new nonce: no reload", () => {
    assert.equal(buildHtmlIfChanged(first.key, { ...base, nonce: "n".repeat(32) }), null);
  });

  it("mode change re-renders", () => {
    assert.ok(buildHtmlIfChanged(first.key, { ...base, mode: "full" }));
  });

  it("showUnlinked and unlinkedCount re-render", () => {
    assert.ok(buildHtmlIfChanged(first.key, withCrit({ showUnlinked: true })));
    assert.ok(buildHtmlIfChanged(first.key, withCrit({ unlinkedCount: 5 })));
  });

  it("nodeTitles change re-renders", () => {
    assert.ok(buildHtmlIfChanged(first.key, withCrit({ nodeTitles: { i_1: "#1 a" } })));
  });

  it("trackFilter, focusIssueLabel, showClosed and tooLargeMessage each re-render", () => {
    assert.ok(buildHtmlIfChanged(first.key, withCrit({ trackFilter: "a/b#t" })));
    assert.ok(buildHtmlIfChanged(first.key, withCrit({ focusIssueLabel: "#1 x" })));
    assert.ok(buildHtmlIfChanged(first.key, withCrit({ showClosed: true })));
    assert.ok(buildHtmlIfChanged(first.key, withCrit({ tooLargeMessage: "too big" })));
  });
});

// ---------------------------------------------------------------------------
// html.ts is vscode-free (this is verified by grep in CI, but add a smoke test)
// ---------------------------------------------------------------------------

describe("buildHtml — vscode-free import check", () => {
  it("buildHtml returns a string (basic smoke test for import)", () => {
    const result = buildHtml(BASE);
    assert.strictEqual(typeof result, "string");
    assert.ok(result.length > 100, "Expected non-trivial output");
  });
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Asserts every <script occurrence in html carries nonce="<nonce>".
 * Raises if any <script is found WITHOUT the expected nonce attribute.
 */
function assertAllScriptsHaveNonce(html: string, nonce: string): void {
  const nonceAttr = `nonce="${nonce}"`;
  // Find all <script occurrences
  let searchFrom = 0;
  let count = 0;
  while (true) {
    const idx = html.indexOf("<script", searchFrom);
    if (idx === -1) break;
    count++;
    // Grab the opening tag up to the first >
    const closeIdx = html.indexOf(">", idx);
    const openTag = html.slice(idx, closeIdx + 1);
    assert.ok(
      openTag.includes(nonceAttr),
      `Found <script without nonce="${nonce}":\n  tag: ${openTag}\n  (occurrence ${count})`,
    );
    searchFrom = idx + 1;
  }
  assert.ok(count > 0, "Expected at least one <script element in output");
}

// ---------------------------------------------------------------------------
// Open-file button (#211)
// ---------------------------------------------------------------------------

describe("buildHtml — open-file button (#211)", () => {
  it("renders an enabled button with the open-file id when hasTrackFile is true", () => {
    const html = buildHtml({ ...BASE, hasTrackFile: true });
    assert.ok(html.includes('id="work-plan-open-file"'), "expected the open-file button id");
    assert.ok(html.includes(">Open file<"), "expected the 'Open file' label");
    // Enabled button must not carry the disabled attribute.
    assert.ok(
      !/id="work-plan-open-file"[^>]*disabled/.test(html),
      "enabled button must not be disabled",
    );
  });

  it("clicking the button posts an openTrackFile message", () => {
    const html = buildHtml({ ...BASE, hasTrackFile: true });
    assert.ok(html.includes('type: "openTrackFile"'), "expected openTrackFile postMessage");
    assert.ok(
      html.includes('getElementById("work-plan-open-file")'),
      "expected a click handler bound to the open-file button",
    );
  });

  it("renders a disabled button (no id, aria-disabled) when hasTrackFile is false", () => {
    const html = buildHtml({ ...BASE, hasTrackFile: false });
    assert.ok(html.includes(">Open file<"), "the affordance stays visible when path-less");
    assert.ok(html.includes('aria-disabled="true"'), "path-less button must be aria-disabled");
    // No id → the click handler can't bind, so it can't post a message.
    assert.ok(
      !html.includes('id="work-plan-open-file"'),
      "disabled button must not carry the actionable id",
    );
  });
});

describe("buildHtml — milestone band filter wiring (#218)", () => {
  it("posts filterMilestone and wires the keyboard collapse toggle", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes('type: "filterMilestone"'), "missing filterMilestone postMessage");
    assert.ok(html.includes(".milestone-filter-btn"), "missing milestone-filter-btn click handler");
    assert.ok(html.includes(".milestone-toggle-btn"), "missing milestone-toggle-btn handler");
    assert.ok(html.includes('aria-expanded'), "toggle handler should sync aria-expanded");
  });
});

describe("buildHtml — in-progress toggle wiring (#271 B4)", () => {
  it("client script contains type: \"toggleInProgress\"", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes('type: "toggleInProgress"'), `expected toggleInProgress postMessage in script:\n${html.slice(0, 2000)}`);
  });

  it("client script reads data-inprogress attribute", () => {
    const html = buildHtml(BASE);
    assert.ok(html.includes("data-inprogress"), `expected data-inprogress handler in script:\n${html.slice(0, 2000)}`);
  });
});

// ---------------------------------------------------------------------------
// Dep toggle DOM wiring (#257 B3)
// ---------------------------------------------------------------------------

describe("buildHtml — dep-detail-row toggle DOM wiring (#257 B3)", () => {
  it("client script handles [data-depissue] click targets", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes("data-depissue"),
      `expected data-depissue handler in client script:\n${html.slice(0, 3000)}`,
    );
  });

  it("dep toggle is pure DOM (no postMessage) — no new message type emitted", () => {
    const html = buildHtml(BASE);
    // The toggle must NOT post any new message type for dep expand/collapse.
    // It toggles hidden + aria-expanded client-side only.
    assert.ok(
      !html.includes('"openDep"') && !html.includes('"toggleDep"'),
      `dep toggle must not postMessage a new type:\n${html.slice(0, 3000)}`,
    );
  });

  it("dep toggle handler flips aria-expanded on the button", () => {
    const html = buildHtml(BASE);
    // The handler must set aria-expanded — mirror the cap-toggle pattern
    assert.ok(
      html.includes("aria-expanded"),
      `dep toggle handler must sync aria-expanded:\n${html.slice(0, 3000)}`,
    );
  });

  it("dep toggle handler toggles the hidden attribute on the dep-detail-row", () => {
    const html = buildHtml(BASE);
    // The handler locates the dep-detail-row and toggles its `hidden` attribute
    assert.ok(
      html.includes("dep-detail-row") || html.includes("[data-depissue]"),
      `dep toggle handler must reference the dep-detail-row:\n${html.slice(0, 3000)}`,
    );
  });

  it("dep toggle CSS defines .dep-toggle-btn", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes(".dep-toggle-btn"),
      `expected .dep-toggle-btn CSS rule:\n${html.slice(0, 3000)}`,
    );
  });

  it("dep chip CSS defines .dep-chip", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes(".dep-chip"),
      `expected .dep-chip CSS rule:\n${html.slice(0, 3000)}`,
    );
  });

  it(".dep-chip is included in the forced-colors reset selector", () => {
    const html = buildHtml(BASE);
    // The forced-colors block containing the chip/pill reset must include .dep-chip.
    // There can be multiple forced-colors blocks (e.g. one for progress bar); find
    // the one that already contains .chip or .pill to locate the chip-reset block.
    const allForcedBlocks = [...html.matchAll(/@media \(forced-colors: active\)[^{]*\{[^}]*\}/g)];
    assert.ok(allForcedBlocks.length > 0, "expected at least one forced-colors block");
    const chipResetBlock = allForcedBlocks.find(m => m[0].includes(".chip") || m[0].includes(".pill"));
    assert.ok(
      chipResetBlock !== undefined,
      `no forced-colors block containing .chip/.pill found`,
    );
    assert.ok(
      chipResetBlock![0].includes(".dep-chip"),
      `forced-colors chip-reset block must include .dep-chip:\n${chipResetBlock![0]}`,
    );
  });
});

// ---------------------------------------------------------------------------
// Set Next-Up client-side handler
// ---------------------------------------------------------------------------

describe("buildHtml — Set Next-Up button client script", () => {
  it("client script looks up the work-plan-set-next element", () => {
    const html = buildHtml(BASE);
    assert.ok(
      html.includes("work-plan-set-next"),
      `Expected client script to reference 'work-plan-set-next':\n${html.slice(0, 3000)}`,
    );
  });

  it("client script wires a click on work-plan-set-next to post({ type: 'setNextUp' })", () => {
    const html = buildHtml(BASE);
    // The handler must post the setNextUp message type.
    assert.ok(
      html.includes('"setNextUp"') || html.includes("'setNextUp'"),
      `Expected post({ type: "setNextUp" }) in client script:\n${html.slice(0, 3000)}`,
    );
  });

  it("setNextUp post is inside a null-guard (if setNextBtn)", () => {
    const html = buildHtml(BASE);
    // The script should have a null guard before adding the event listener.
    // Find the section around "work-plan-set-next" and verify a conditional guard.
    const idx = html.indexOf("work-plan-set-next");
    assert.ok(idx !== -1, "work-plan-set-next not found in html");
    const snippet = html.slice(idx - 50, idx + 300);
    // There must be an 'if' check nearby (null guard pattern)
    assert.ok(
      snippet.includes("if (") || snippet.includes("if("),
      `Expected a null-guard 'if' near the setNextBtn handler:\n${snippet}`,
    );
  });
});

// ---------------------------------------------------------------------------
// buildHtmlIfChanged — skip unchanged re-renders (#423)
// ---------------------------------------------------------------------------

describe("buildHtmlIfChanged — change-aware panel render (#423)", () => {
  const NOW = Date.parse("2026-06-07T12:00:00Z");

  function track(name: string, title = "auth rate limit"): Track {
    return makeTrack({
      name,
      repo: "your-org/myproject",
      tier: "private",
      status: "active",
      launch_priority: "P1",
      milestone_alignment: null,
      visibility: "PRIVATE",
      blockers: [],
      next_up: [487],
      depends_on: [],
      rollup: { open: 1, closed: 0 },
      issues: [makeIssue({ number: 487, title, state: "open", assignee: "@alice", milestone: null })],
    });
  }

  function exportAt(generatedAt: string, tracks: Track[]): Export {
    return { schema: 1, generated_at: generatedAt, tracks };
  }

  // Builds options exactly as WorkPlanPanel.render does, with a fresh nonce
  // per call (panel.ts mints one every render).
  let nonceSeq = 0;
  function optionsFor(
    exp: Export,
    selection: string,
    view: { focused?: boolean; mode?: GraphMode; isDark?: boolean } = {},
  ): WebviewHtmlOptions {
    const sel = exp.tracks.find(t => t.name === selection)!;
    const focused = view.focused ?? true;
    const isDark = view.isDark ?? true;
    const graphExp = focused ? exp : { ...exp, tracks: exp.tracks.filter(t => t.repo === sel.repo) };
    return {
      ...BASE,
      nonce: `nonce${String(++nonceSeq).padStart(27, "0")}`,
      graphDef: toMermaid(graphExp, trackKey(sel), { focus: focused, dark: isDark }),
      detailHtml: renderDetail(sel, { now: NOW }),
      trackName: sel.name,
      mode: view.mode ?? (focused ? "focus" : "full"),
      isDark,
      hasTrackFile: !!sel.path,
    };
  }

  const first = exportAt("2026-06-07T00:00:00Z", [track("alpha"), track("beta")]);
  const shown = buildHtmlIfChanged(null, optionsFor(first, "alpha"))!;

  it("first render always builds the document", () => {
    assert.ok(shown, "a null previous key must render");
    assert.ok(shown.html.includes("<!DOCTYPE html>") || shown.html.includes("<html"));
  });

  it("an unchanged semantic export (only generated_at + nonce differ) does not reload", () => {
    const polled = exportAt("2026-06-07T00:00:30Z", [track("alpha"), track("beta")]);
    assert.equal(buildHtmlIfChanged(shown.key, optionsFor(polled, "alpha")), null);
  });

  it("changed issue data re-renders", () => {
    const changed = exportAt("2026-06-07T00:00:30Z", [track("alpha", "renamed"), track("beta")]);
    assert.ok(buildHtmlIfChanged(shown.key, optionsFor(changed, "alpha")));
  });

  it("a lens that changes the visible tracks re-renders", () => {
    const lensed = exportAt("2026-06-07T00:00:00Z", [track("alpha")]);
    const fullMap = buildHtmlIfChanged(null, optionsFor(first, "alpha", { focused: false }))!;
    assert.ok(buildHtmlIfChanged(fullMap.key, optionsFor(lensed, "alpha", { focused: false })));
  });

  it("a theme change re-renders", () => {
    assert.ok(buildHtmlIfChanged(shown.key, optionsFor(first, "alpha", { isDark: false })));
  });

  it("a different selected track re-renders", () => {
    assert.ok(buildHtmlIfChanged(shown.key, optionsFor(first, "beta")));
  });

  it("a focus-mode toggle re-renders", () => {
    assert.ok(buildHtmlIfChanged(shown.key, optionsFor(first, "alpha", { focused: false })));
  });

  it("the returned html is exactly buildHtml's output for the same options", () => {
    const o = optionsFor(first, "beta");
    assert.equal(buildHtmlIfChanged(null, o)!.html, buildHtml(o));
  });
});
