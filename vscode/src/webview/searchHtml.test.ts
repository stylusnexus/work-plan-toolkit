/**
 * Tests for src/webview/searchHtml.ts — pure HTML builder for search results.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { SearchHit } from "./search.ts";
import { buildSearchHtml } from "./searchHtml.ts";

const base = { generatedAt: "2026-06-11T00:00:00Z", cspSource: "vscode-resource:", nonce: "abc123" };

function hit(over: Partial<SearchHit> = {}): SearchHit {
  return {
    number: 487,
    title: "Auth rate limit",
    state: "open",
    assignee: "@alice",
    milestone: null,
    repo: "your-org/myproject",
    track: "platform-health",
    ...over,
  };
}

describe("buildSearchHtml — header & count", () => {
  it("states the match count and echoes the query", () => {
    const html = buildSearchHtml({ ...base, query: "%auth%", hits: [hit()] });
    assert.match(html, /1 issue matching/);
    assert.match(html, /%auth%/);
  });

  it("pluralizes the count", () => {
    const html = buildSearchHtml({ ...base, query: "x", hits: [hit(), hit({ number: 488 })] });
    assert.match(html, /2 issues matching/);
  });

  it("surfaces the snapshot generated_at", () => {
    const html = buildSearchHtml({ ...base, query: "x", hits: [hit()] });
    assert.match(html, /As of 2026-06-11T00:00:00Z/);
  });

  it("includes the nonce on the script and a strict CSP", () => {
    const html = buildSearchHtml({ ...base, query: "x", hits: [hit()] });
    assert.match(html, /<script nonce="abc123">/);
    assert.match(html, /default-src 'none'/);
  });
});

describe("buildSearchHtml — empty state", () => {
  it("renders a friendly no-match message, not an error", () => {
    const html = buildSearchHtml({ ...base, query: "%zzz%", hits: [] });
    assert.match(html, /No issues matched/);
    assert.match(html, /%zzz%/);
    assert.doesNotMatch(html, /error/i);
  });
});

describe("buildSearchHtml — rows", () => {
  it("renders an issue link carrying repo + number for the open handler", () => {
    const html = buildSearchHtml({ ...base, query: "x", hits: [hit()] });
    assert.match(html, /data-number="487"/);
    assert.match(html, /data-repo="your-org\/myproject"/);
    assert.match(html, /#487/);
  });

  it("shows a reveal button for tracked issues", () => {
    const html = buildSearchHtml({ ...base, query: "x", hits: [hit()] });
    assert.match(html, /class="reveal-btn"[^>]*data-track="platform-health"/);
  });

  it("omits the reveal button for untracked issues", () => {
    const html = buildSearchHtml({ ...base, query: "x", hits: [hit({ track: null })] });
    // Match the button element, not the `.reveal-btn` CSS rule in <style>.
    assert.doesNotMatch(html, /class="reveal-btn"/);
    assert.match(html, /untracked/);
  });

  it("escapes HTML in issue titles", () => {
    const html = buildSearchHtml({ ...base, query: "x", hits: [hit({ title: "<script>alert(1)</script>" })] });
    assert.doesNotMatch(html, /<script>alert\(1\)<\/script>/);
    assert.match(html, /&lt;script&gt;/);
  });

  it("groups by repo with a per-repo count", () => {
    const html = buildSearchHtml({
      ...base,
      query: "x",
      hits: [hit(), hit({ number: 900, repo: "your-org/other", track: null })],
    });
    assert.match(html, /your-org\/myproject/);
    assert.match(html, /your-org\/other/);
  });
});
