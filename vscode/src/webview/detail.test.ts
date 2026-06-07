/**
 * Tests for src/webview/detail.ts — pure HTML detail-panel renderer.
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Track } from "../model.ts";
import { renderDetail } from "./detail.ts";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const platformHealth: Track = {
  name: "platform-health",
  repo: "stylusnexus/CritForge",
  tier: "private",
  status: "blocked",
  launch_priority: "P0",
  milestone_alignment: "M1",
  visibility: "PRIVATE",
  blockers: [4821],
  next_up: [487, 1556],
  rollup: { open: 12, closed: 8 },
  issues: [
    { number: 4821, title: "OAuth scopes",   state: "open",   assignee: "@carol", milestone: null },
    { number: 487,  title: "auth rate limit", state: "open",  assignee: "@alice", milestone: "M1" },
    { number: 1556, title: "session cache",  state: "open",   assignee: "@bob",   milestone: "M1" },
    { number: 2196, title: "RLS audit",      state: "closed", assignee: "—",      milestone: null },
  ],
};

const emptyTrack: Track = {
  name: "empty-track",
  repo: "stylusnexus/test",
  tier: "private",
  status: "parked",
  launch_priority: null,
  milestone_alignment: null,
  visibility: null,
  blockers: [],
  next_up: [],
  rollup: { open: 0, closed: 0 },
  issues: [],
};

const xssTrack: Track = {
  name: "xss-track",
  repo: "stylusnexus/test",
  tier: "private",
  status: "active",
  launch_priority: null,
  milestone_alignment: null,
  visibility: null,
  blockers: [],
  next_up: [999],
  rollup: { open: 1, closed: 0 },
  issues: [
    {
      number: 999,
      title: "<script>alert('xss')</script>",
      state: "open",
      assignee: "<b>evil</b>",
      milestone: null,
    },
  ],
};

// ---------------------------------------------------------------------------
// Tests: platform-health track
// ---------------------------------------------------------------------------

describe("renderDetail — rollup", () => {
  it("contains rollup open count 12", () => {
    const html = renderDetail(platformHealth);
    // Must render "12" as the open count — wrapped in <b>
    assert.ok(
      html.includes("<b>12</b>") || (html.includes(">12<") && html.includes("open")),
      `Expected bold 12 open in:\n${html}`,
    );
  });

  it("contains rollup closed count 8", () => {
    const html = renderDetail(platformHealth);
    assert.ok(
      html.includes("<b>8</b>") || (html.includes(">8<") && html.includes("closed")),
      `Expected bold 8 closed in:\n${html}`,
    );
  });

  it("rollup line has both 'open' and 'closed' text", () => {
    const html = renderDetail(platformHealth);
    assert.ok(html.includes("open"), "missing 'open'");
    assert.ok(html.includes("closed"), "missing 'closed'");
  });
});

describe("renderDetail — issues table", () => {
  it("contains a row for issue #487", () => {
    const html = renderDetail(platformHealth);
    assert.ok(html.includes("487"), `Missing issue #487:\n${html}`);
  });

  it("contains the title 'auth rate limit' for #487", () => {
    const html = renderDetail(platformHealth);
    assert.ok(html.includes("auth rate limit"), `Missing title:\n${html}`);
  });

  it("contains an 'open' pill for open issues", () => {
    const html = renderDetail(platformHealth);
    assert.ok(
      html.includes('class="pill open"') || html.includes("class='pill open'"),
      `Expected open pill:\n${html}`,
    );
  });

  it("contains a 'closed' pill for closed issues", () => {
    const html = renderDetail(platformHealth);
    // #2196 RLS audit is closed
    assert.ok(
      html.includes('class="pill closed"') || html.includes("class='pill closed'"),
      `Expected closed pill:\n${html}`,
    );
  });

  it("contains the assignee '@alice'", () => {
    assert.ok(renderDetail(platformHealth).includes("@alice"));
  });
});

describe("renderDetail — clickable issue links", () => {
  it("emits data-repo / data-issue anchors when the track has a repo", () => {
    const html = renderDetail(platformHealth);
    assert.ok(
      html.includes('data-repo="stylusnexus/CritForge"'),
      `Expected data-repo attribute:\n${html}`,
    );
    assert.ok(
      html.includes('data-issue="487"'),
      `Expected data-issue="487" for the #487 row:\n${html}`,
    );
  });

  it("renders plain-text numbers (no anchor) when repo is null", () => {
    const noRepoTrack: Track = {
      ...platformHealth,
      repo: null as unknown as string,
    };
    const html = renderDetail(noRepoTrack);
    assert.ok(
      !html.includes("data-issue="),
      `Expected no data-issue anchors for a null-repo track:\n${html}`,
    );
    // The number itself should still render as plain text.
    assert.ok(html.includes("#487"), `Expected #487 to still render:\n${html}`);
  });
});

describe("renderDetail — blocker chips", () => {
  it("contains ⛔ blocker chip for #4821", () => {
    const html = renderDetail(platformHealth);
    assert.ok(html.includes("⛔"), `Expected ⛔ symbol:\n${html}`);
    assert.ok(html.includes("4821"), `Expected 4821 in blockers:\n${html}`);
  });

  it("includes title 'OAuth scopes' next to blocker #4821", () => {
    const html = renderDetail(platformHealth);
    assert.ok(html.includes("OAuth scopes"), `Expected OAuth scopes title:\n${html}`);
  });
});

describe("renderDetail — next_up steps", () => {
  it("contains #487 in next-up", () => {
    const html = renderDetail(platformHealth);
    // next_up = [487, 1556] — both must appear in the steps section
    assert.ok(html.includes("487"), `Expected 487 in next_up:\n${html}`);
  });

  it("contains #1556 in next-up", () => {
    const html = renderDetail(platformHealth);
    assert.ok(html.includes("1556"), `Expected 1556 in next_up:\n${html}`);
  });

  it("steps are separated by →", () => {
    const html = renderDetail(platformHealth);
    assert.ok(html.includes("→"), `Expected → separator in steps:\n${html}`);
  });
});

describe("renderDetail — empty blockers / next_up branches", () => {
  it("empty blockers → renders 'None.'", () => {
    const html = renderDetail(emptyTrack);
    assert.ok(html.includes("None."), `Expected 'None.' for empty blockers:\n${html}`);
  });

  it("empty next_up → renders 'empty'", () => {
    const html = renderDetail(emptyTrack);
    assert.ok(html.includes("empty"), `Expected 'empty' for empty next_up:\n${html}`);
  });
});

describe("renderDetail — HTML escaping", () => {
  it("raw '<script>' does NOT appear unescaped in output", () => {
    const html = renderDetail(xssTrack);
    assert.ok(
      !html.includes("<script>"),
      `Raw <script> found unescaped in:\n${html}`,
    );
  });

  it("'<script>' is escaped as '&lt;script&gt;'", () => {
    const html = renderDetail(xssTrack);
    assert.ok(
      html.includes("&lt;script&gt;"),
      `Expected &lt;script&gt; escaped form:\n${html}`,
    );
  });

  it("assignee '<b>evil</b>' is escaped", () => {
    const html = renderDetail(xssTrack);
    // Raw <b>evil</b> should not appear as-is (it would be rendered as bold)
    // The escaped form &lt;b&gt;evil&lt;/b&gt; should appear instead
    assert.ok(
      !html.includes("<b>evil</b>"),
      `Raw <b>evil</b> should be escaped:\n${html}`,
    );
    assert.ok(
      html.includes("&lt;b&gt;"),
      `Expected escaped &lt;b&gt; for evil assignee:\n${html}`,
    );
  });

  it("escapes a crafted issue.state in the attribute position", () => {
    // The `state` type is "open"|"closed", but adversarial export JSON can supply
    // anything at runtime. Cast to bypass the compile-time guard.
    const attackTrack: Track = {
      ...emptyTrack,
      issues: [
        {
          number: 1,
          title: "ok",
          state: 'open" onmouseover="x' as unknown as "open",
          assignee: "@x",
          milestone: null,
        },
      ],
    };
    const html = renderDetail(attackTrack);
    assert.ok(
      !html.includes('onmouseover="x"'),
      `Crafted state broke out of the attribute (live onmouseover):\n${html}`,
    );
    assert.ok(
      html.includes("&quot;"),
      `Expected the crafted double-quote escaped to &quot;:\n${html}`,
    );
  });
});
