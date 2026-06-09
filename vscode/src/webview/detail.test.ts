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
  depends_on: ["idea-mode", "org-sharing"],
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
  depends_on: [],
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
  depends_on: [],
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

describe("renderDetail — depends_on (#102)", () => {
  it("renders depends_on chips with data-track attributes", () => {
    const html = renderDetail(platformHealth);
    // platformHealth depends_on: ["idea-mode", "org-sharing"]
    assert.ok(
      html.includes("idea-mode"),
      `Expected 'idea-mode' depends_on chip:\n${html}`,
    );
    assert.ok(
      html.includes("org-sharing"),
      `Expected 'org-sharing' depends_on chip:\n${html}`,
    );
    // Chips should be clickable (data-track attribute for navigation)
    assert.ok(
      html.includes('data-track="idea-mode"'),
      `Expected data-track attribute on idea-mode chip:\n${html}`,
    );
    assert.ok(
      html.includes('data-track="org-sharing"'),
      `Expected data-track attribute on org-sharing chip:\n${html}`,
    );
    // Uses the depends-chip CSS class
    assert.ok(
      html.includes("depends-chip"),
      `Expected depends-chip class:\n${html}`,
    );
  });

  it("empty depends_on → renders 'None.'", () => {
    const html = renderDetail(emptyTrack);
    assert.ok(
      html.includes("Depends on:"),
      `Expected 'Depends on:' heading even when empty:\n${html}`,
    );
    // The "None." text should appear in the depends-on section.
    // We check that "None." appears after "Depends on:".
    const dependsIdx = html.indexOf("Depends on:");
    const noneIdx = html.indexOf("None.", dependsIdx);
    assert.ok(
      noneIdx > dependsIdx,
      `Expected 'None.' after 'Depends on:' for empty depends_on:\n${html}`,
    );
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

describe("renderDetail — milestone bands", () => {
  it("renders milestone band headers when multiple milestone groups exist", () => {
    const html = renderDetail(platformHealth);
    // platformHealth has issues in M1 and null milestones → 2 groups → bands
    assert.ok(
      html.includes("milestone-band-header"),
      `Expected milestone-band-header for multi-milestone track:\n${html}`,
    );
  });

  it("active milestone band (M1) is expanded (no 'collapsed' class)", () => {
    const html = renderDetail(platformHealth);
    // The FIRST tbody.milestone-band should not have 'collapsed'
    const firstBand = html.match(/<tbody class="milestone-band[^"]*"[^>]*>/);
    assert.ok(firstBand !== null, "Expected at least one milestone-band tbody");
    assert.ok(
      !firstBand![0].includes("collapsed"),
      `First band should not be collapsed:\n${firstBand![0]}`,
    );
  });

  it("non-active milestone band is collapsed", () => {
    const html = renderDetail(platformHealth);
    assert.ok(
      html.includes("collapsed"),
      `Expected a 'collapsed' class on at least one band:\n${html}`,
    );
  });

  it("renders the milestone label (M1) in the band header", () => {
    const html = renderDetail(platformHealth);
    assert.ok(
      html.includes("<b>M1</b>"),
      `Expected M1 label in band header:\n${html}`,
    );
  });

  it("renders 'No milestone' for the null-milestone band", () => {
    const html = renderDetail(platformHealth);
    assert.ok(
      html.includes("<b>No milestone</b>"),
      `Expected No milestone label:\n${html}`,
    );
  });

  it("renders the issue count in the band header", () => {
    const html = renderDetail(platformHealth);
    // M1 has 2 issues (#487, #1556) → (2)
    assert.ok(
      html.includes("(2)"),
      `Expected issue count (2) for M1 band:\n${html}`,
    );
  });

  it("single milestone group renders flat (no bands)", () => {
    const singleMsTrack: Track = {
      ...emptyTrack,
      issues: [
        { number: 1, title: "one", state: "open", assignee: "@x", milestone: "v1" },
        { number: 2, title: "two", state: "open", assignee: "@y", milestone: "v1" },
      ],
      rollup: { open: 2, closed: 0 },
    };
    const html = renderDetail(singleMsTrack);
    assert.ok(
      !html.includes("milestone-band-header"),
      `Single-milestone track should render flat (no bands):\n${html}`,
    );
  });

  it("all-null milestone track renders flat (no bands)", () => {
    const allNullTrack: Track = {
      ...emptyTrack,
      issues: [
        { number: 1, title: "one", state: "open", assignee: "@x", milestone: null },
        { number: 2, title: "two", state: "open", assignee: "@y", milestone: null },
      ],
      rollup: { open: 2, closed: 0 },
    };
    const html = renderDetail(allNullTrack);
    assert.ok(
      !html.includes("milestone-band-header"),
      `All-null-milestone track should render flat:\n${html}`,
    );
  });

  it("issues within each band are in number order", () => {
    // Create a track with multiple milestones to verify number-sort within groups
    const multiTrack: Track = {
      ...emptyTrack,
      milestone_alignment: "v1",
      issues: [
        { number: 30, title: "c", state: "open", assignee: "@x", milestone: "v2" },
        { number: 10, title: "a", state: "open", assignee: "@x", milestone: "v1" },
        { number: 20, title: "b", state: "open", assignee: "@x", milestone: "v1" },
        { number: 40, title: "d", state: "open", assignee: "@x", milestone: null },
      ],
      rollup: { open: 4, closed: 0 },
    };
    const html = renderDetail(multiTrack);
    // v1 band (#10, #20) should appear before v2 #30 before null #40
    const idx10 = html.indexOf("#10");
    const idx20 = html.indexOf("#20");
    const idx30 = html.indexOf("#30");
    const idx40 = html.indexOf("#40");
    assert.ok(idx10 < idx20, "#10 should appear before #20 within v1 band");
    assert.ok(idx20 < idx30, "v1 band should appear before v2 band");
    assert.ok(idx30 < idx40, "v2 band should appear before null-milestone band");
  });
});

// ---------------------------------------------------------------------------
// Issue cap tests (#169)
// ---------------------------------------------------------------------------

describe("renderDetail — issue cap", () => {
  /** Build a track with `n` issues numbered 1..n, all open, no milestone. */
  function makeBigTrack(n: number): Track {
    const issues: Issue[] = [];
    for (let i = 1; i <= n; i++) {
      issues.push({
        number: i,
        title: `Issue ${i}`,
        state: "open",
        assignee: "@dev",
        milestone: null,
      });
    }
    return {
      name: "big-track",
      repo: "org/repo",
      tier: "private",
      status: "active",
      launch_priority: null,
      milestone_alignment: null,
      visibility: null,
      blockers: [],
      next_up: [],
      depends_on: [],
      rollup: { open: n, closed: 0 },
      issues,
    };
  }

  it("renders all issues when count is below the cap", () => {
    const track = makeBigTrack(30);
    const html = renderDetail(track);
    // All 30 issues should be in the visible table
    assert.ok(html.includes("#1"), "missing #1");
    assert.ok(html.includes("#30"), "missing #30");
    // No collapsible overflow
    assert.ok(!html.includes("issue-cap-toggle"), "unexpected cap toggle");
  });

  it("caps at 50 with collapsible overflow for flat table", () => {
    const track = makeBigTrack(75);
    const html = renderDetail(track);
    // First 50 visible
    assert.ok(html.includes("#1"), "missing #1");
    assert.ok(html.includes("#50"), "missing #50");
    // #51 should NOT be in the visible table — only inside <details>
    const idx50 = html.indexOf("#50");
    const idx51 = html.indexOf("#51");
    assert.ok(idx51 > idx50, "#51 should appear after #50");
    // Collapsible toggle present
    assert.ok(html.includes("issue-cap-toggle"), "missing cap toggle");
    assert.ok(html.includes("<details>"), "missing <details> element");
    assert.ok(html.includes("Show all 75 issues"), "missing 'Show all 75 issues'");
    assert.ok(html.includes("25 more"), "missing '25 more' count");
  });

  it("caps within milestone bands — overflow goes to collapsible band", () => {
    // 3 milestones × 20 issues = 60 total, cap at 50 → 10 in overflow
    const issues: Issue[] = [];
    for (let i = 1; i <= 60; i++) {
      const ms = i <= 20 ? "v1" : i <= 40 ? "v2" : null;
      issues.push({
        number: i,
        title: `Issue ${i}`,
        state: "open",
        assignee: "@dev",
        milestone: ms,
      });
    }
    const track: Track = {
      name: "multi-ms-big",
      repo: "org/repo",
      tier: "private",
      status: "active",
      launch_priority: null,
      milestone_alignment: "v1",
      visibility: null,
      blockers: [],
      next_up: [],
      depends_on: [],
      rollup: { open: 60, closed: 0 },
      issues,
    };

    const html = renderDetail(track);
    // Milestone bands should be present
    assert.ok(html.includes("milestone-band-header"), "missing milestone bands");
    // First 50 visible — v1 (20) + v2 (20) + null (10 of 20) = 50
    assert.ok(html.includes("#1"), "missing #1");
    assert.ok(html.includes("#50"), "missing #50");
    // Overflow toggle present
    assert.ok(html.includes("issue-cap-toggle"), "missing cap toggle in milestone bands");
    assert.ok(html.includes("Show all 60 issues"), "missing total count");
    assert.ok(html.includes("10 more"), "missing '10 more' count");
  });
});
