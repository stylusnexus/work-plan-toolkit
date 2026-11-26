import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildHtml } from "./html.ts";

describe("graph header in a narrow panel (#598)", () => {
  const html = buildHtml({
    cspSource: "x:", nonce: "n".repeat(32), mermaidUri: "x:/m.js", graphDef: "", detailHtml: "", trackName: "t",
    isModule: false, mode: "focus", isDark: true, hasTrackFile: false,
    issueStates: { open: true, closed: false }, graphNote: null, trackKey: "k",
  });
  it("wraps the header onto more lines instead of squeezing its groups", () => {
    assert.match(html, /\.graph-header \{[^}]*flex-wrap: wrap;/);
  });
  it("never shrinks or breaks the Issue state group", () => {
    assert.match(html, /\.state-group \{[^}]*flex-shrink: 0;[^}]*white-space: nowrap;/);
  });
});
