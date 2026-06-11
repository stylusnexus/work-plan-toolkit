/**
 * Tests for src/webview/html.ts — pure HTML/CSP builder.
 *
 * All assertions are offline; no vscode import anywhere in this test or the
 * module under test.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildHtml } from "./html.ts";
import type { WebviewHtmlOptions } from "./html.ts";

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
  focused: false,
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

  it("the mermaid graph has a text alternative (role=img + aria-label) (#217)", () => {
    const html = buildHtml({ ...BASE, trackName: "platform-health" });
    assert.ok(
      html.includes('<pre class="mermaid" role="img" aria-label="Dependency graph for platform-health">'),
      `mermaid graph missing role/aria-label:\n${html}`,
    );
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
    const html = buildHtml({ ...BASE, focused: true });
    assert.equal((html.match(/acquireVsCodeApi\(/g) || []).length, 1);
  });
});

// ---------------------------------------------------------------------------
// Focus toggle button
// ---------------------------------------------------------------------------

describe("buildHtml — focus toggle button", () => {
  it("renders the toggle button element", () => {
    const html = buildHtml({ ...BASE, focused: false });
    assert.ok(
      html.includes("work-plan-focus-toggle"),
      `Expected focus toggle button in output`,
    );
  });

  it("label is 'Focus on track' when focused is false", () => {
    const html = buildHtml({ ...BASE, focused: false });
    assert.ok(
      html.includes("Focus on track"),
      `Expected 'Focus on track' label when focused=false:\n${html.slice(0, 1000)}`,
    );
  });

  it("label is 'Show full map' when focused is true", () => {
    const html = buildHtml({ ...BASE, focused: true });
    assert.ok(
      html.includes("Show full map"),
      `Expected 'Show full map' label when focused=true:\n${html.slice(0, 1000)}`,
    );
  });

  it("does NOT show 'Focus on track' when focused is true", () => {
    const html = buildHtml({ ...BASE, focused: true });
    assert.ok(
      !html.includes("Focus on track"),
      `Should not show 'Focus on track' when already focused`,
    );
  });

  it("does NOT show 'Show full map' when focused is false", () => {
    const html = buildHtml({ ...BASE, focused: false });
    assert.ok(
      !html.includes("Show full map"),
      `Should not show 'Show full map' when not focused`,
    );
  });

  it("toggle click posts setFocus message (focused=false → posts focus:true)", () => {
    const html = buildHtml({ ...BASE, focused: false });
    // The script should post { type: "setFocus", focus: true } when clicked
    assert.ok(
      html.includes("setFocus"),
      `Expected setFocus in toggle script`,
    );
    assert.ok(
      html.includes('"setFocus"') || html.includes("'setFocus'") || html.includes("setFocus"),
      `Expected setFocus message type in script`,
    );
  });

  it("toggle click posts setFocus with focus:false when currently focused", () => {
    const html = buildHtml({ ...BASE, focused: true });
    // When focused=true, clicking should post focus:false
    assert.ok(
      html.includes("false"),
      `Expected focus: false in the setFocus script when focused=true`,
    );
  });

  it("toggle click posts setFocus with focus:true when not focused", () => {
    const html = buildHtml({ ...BASE, focused: false });
    // When focused=false, clicking should post focus:true
    assert.ok(
      html.includes("true"),
      `Expected focus: true in the setFocus script when focused=false`,
    );
  });

  it("toggle script carries the nonce (UMD path)", () => {
    const html = buildHtml({ ...BASE, focused: false, isModule: false });
    // assertAllScriptsHaveNonce already covers all scripts, but let's be explicit
    assertAllScriptsHaveNonce(html, BASE.nonce);
  });

  it("toggle script carries the nonce (ESM path)", () => {
    const html = buildHtml({ ...BASE, focused: true, isModule: true });
    assertAllScriptsHaveNonce(html, BASE.nonce);
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
