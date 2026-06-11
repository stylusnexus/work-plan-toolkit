/**
 * Tests for src/webview/graph.ts — pure Mermaid graph derivation.
 *
 * Fixture mirrors the mockup:
 *   myproject (PRIVATE):
 *     • platform-health — blocked, blockers:[4821], next_up:[487,1556]
 *     • idea-mode       — active,  blockers:[],    next_up:[4821]
 *   work-plan-toolkit (PUBLIC):
 *     • org-sharing     — active,  blockers:[],    next_up:[87]
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Export } from "../model.ts";
import { toMermaid, __mermaidLabelForTest as mermaidLabel } from "./graph.ts";

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

const exp: Export = {
  schema: 1,
  generated_at: "2026-06-07T00:00:00Z",
  tracks: [
    {
      name: "platform-health",
      repo: "your-org/myproject",
      tier: "private",
      status: "blocked",
      launch_priority: "P0",
      milestone_alignment: "M1",
      visibility: "PRIVATE",
      blockers: [4821],
      next_up: [487, 1556],
      rollup: { open: 12, closed: 8 },
      issues: [
        { number: 487,  title: "auth rate limit",  state: "open",   assignee: "@alice", milestone: "M1" },
        { number: 1556, title: "session cache",    state: "open",   assignee: "@bob",   milestone: "M1" },
        { number: 2196, title: "RLS audit",        state: "closed", assignee: "—",      milestone: null },
        { number: 2528, title: "poll schema",      state: "open",   assignee: "@alice", milestone: null },
      ],
    },
    {
      name: "idea-mode",
      repo: "your-org/myproject",
      tier: "private",
      status: "active",
      launch_priority: "P1",
      milestone_alignment: null,
      visibility: "PRIVATE",
      blockers: [],
      next_up: [4821],
      rollup: { open: 5, closed: 3 },
      issues: [
        { number: 4821, title: "OAuth scopes", state: "open",   assignee: "@carol", milestone: null },
        { number: 4830, title: "scope UI",     state: "open",   assignee: "@carol", milestone: null },
      ],
    },
    {
      name: "org-sharing",
      repo: "stylusnexus/work-plan-toolkit",
      tier: "private",
      status: "active",
      launch_priority: "P2",
      milestone_alignment: null,
      visibility: "PUBLIC",
      blockers: [],
      next_up: [87],
      rollup: { open: 3, closed: 2 },
      issues: [
        { number: 87, title: "VS Code viewer", state: "open",   assignee: "@dave", milestone: null },
        { number: 74, title: "plan-status",    state: "closed", assignee: "—",     milestone: null },
      ],
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mermaid(selectedTrack?: string): string {
  return toMermaid(exp, selectedTrack);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("toMermaid — track nodes", () => {
  it("contains a node id for platform-health", () => {
    const out = mermaid();
    assert.ok(
      out.includes("t_platform_health"),
      `Expected t_platform_health in output:\n${out}`,
    );
  });

  it("contains a node id for idea-mode", () => {
    const out = mermaid();
    assert.ok(out.includes("t_idea_mode"), `Expected t_idea_mode:\n${out}`);
  });

  it("contains a node id for org-sharing", () => {
    const out = mermaid();
    assert.ok(out.includes("t_org_sharing"), `Expected t_org_sharing:\n${out}`);
  });

  it("includes track label 'platform-health' in output", () => {
    assert.ok(mermaid().includes("platform-health"));
  });

  it("includes track label 'idea-mode' in output", () => {
    assert.ok(mermaid().includes("idea-mode"));
  });

  it("includes track label 'org-sharing' in output", () => {
    assert.ok(mermaid().includes("org-sharing"));
  });
});

describe("toMermaid — issue nodes (blocker/next_up only)", () => {
  it("issue node i_4821 exists (blocker of platform-health AND next_up of idea-mode)", () => {
    assert.ok(mermaid().includes("i_4821"));
  });

  it("issue node i_487 exists (next_up of platform-health)", () => {
    assert.ok(mermaid().includes("i_487"));
  });

  it("issue node i_1556 exists (next_up of platform-health)", () => {
    assert.ok(mermaid().includes("i_1556"));
  });

  it("issue node i_87 exists (next_up of org-sharing)", () => {
    assert.ok(mermaid().includes("i_87"));
  });

  it("issue node i_2196 does NOT exist (only in issues[], never blocker/next_up)", () => {
    assert.ok(
      !mermaid().includes("i_2196"),
      "i_2196 should not appear — it is only in issues[], not blockers/next_up",
    );
  });

  it("issue node i_2528 does NOT exist (only in issues[], never blocker/next_up)", () => {
    assert.ok(!mermaid().includes("i_2528"));
  });

  it("issue node i_4830 does NOT exist (only in issues[], never blocker/next_up)", () => {
    assert.ok(!mermaid().includes("i_4830"));
  });

  it("issue node i_74 does NOT exist (only in issues[], never blocker/next_up)", () => {
    assert.ok(!mermaid().includes("i_74"));
  });
});

describe("toMermaid — blocks edges", () => {
  it("blocks edge from i_4821 to t_platform_health with label 'blocks'", () => {
    const out = mermaid();
    // The edge must mention i_4821, 'blocks', and t_platform_health on the same or adjacent line.
    // We check by asserting all three substrings exist and that i_4821 appears before t_platform_health
    // in a 'blocks' edge context.
    assert.ok(out.includes("i_4821"), "i_4821 missing");
    assert.ok(out.includes("t_platform_health"), "t_platform_health missing");
    // At least one line contains i_4821, |blocks|, t_platform_health
    const lines = out.split("\n");
    const blocksLine = lines.find(
      l => l.includes("i_4821") && l.includes("blocks") && l.includes("t_platform_health"),
    );
    assert.ok(
      blocksLine !== undefined,
      `Expected a line with i_4821 + blocks + t_platform_health:\n${out}`,
    );
  });
});

describe("toMermaid — cross-track owns edges", () => {
  it("owns edge from t_idea_mode to t_platform_health labeled 'owns #4821'", () => {
    const out = mermaid();
    const lines = out.split("\n");
    // Look for a line that contains t_idea_mode, owns, #4821, t_platform_health
    const ownsLine = lines.find(
      l =>
        l.includes("t_idea_mode") &&
        l.includes("owns") &&
        l.includes("4821") &&
        l.includes("t_platform_health"),
    );
    assert.ok(
      ownsLine !== undefined,
      `Expected an owns edge from t_idea_mode to t_platform_health about #4821:\n${out}`,
    );
  });
});

describe("toMermaid — next_up flow edges", () => {
  it("next_up solid edge from t_platform_health to i_487", () => {
    const out = mermaid();
    const lines = out.split("\n");
    const nextUpLine = lines.find(
      l => l.includes("t_platform_health") && l.includes("next_up") && l.includes("i_487"),
    );
    assert.ok(
      nextUpLine !== undefined,
      `Expected next_up edge from t_platform_health to i_487:\n${out}`,
    );
  });

  it("dashed 'then' edge from i_487 to i_1556", () => {
    const out = mermaid();
    const lines = out.split("\n");
    const thenLine = lines.find(
      l => l.includes("i_487") && l.includes("then") && l.includes("i_1556"),
    );
    assert.ok(
      thenLine !== undefined,
      `Expected dashed then edge from i_487 to i_1556:\n${out}`,
    );
  });

  it("next_up edge from t_idea_mode to i_4821", () => {
    const out = mermaid();
    const lines = out.split("\n");
    const nextUpLine = lines.find(
      l => l.includes("t_idea_mode") && l.includes("next_up") && l.includes("i_4821"),
    );
    assert.ok(
      nextUpLine !== undefined,
      `Expected next_up edge from t_idea_mode to i_4821:\n${out}`,
    );
  });

  it("next_up edge from t_org_sharing to i_87", () => {
    const out = mermaid();
    const lines = out.split("\n");
    const nextUpLine = lines.find(
      l => l.includes("t_org_sharing") && l.includes("next_up") && l.includes("i_87"),
    );
    assert.ok(
      nextUpLine !== undefined,
      `Expected next_up edge from t_org_sharing to i_87:\n${out}`,
    );
  });
});

describe("toMermaid — determinism", () => {
  it("identical input produces byte-identical output (no randomness)", () => {
    assert.strictEqual(toMermaid(exp), toMermaid(exp));
  });

  it("deterministic even with selectedTrack", () => {
    assert.strictEqual(toMermaid(exp, "idea-mode"), toMermaid(exp, "idea-mode"));
  });
});

describe("toMermaid — selected highlight", () => {
  it("selected track assigns 'selected' class to t_platform_health", () => {
    const out = toMermaid(exp, "platform-health");
    // Must contain: class t_platform_health selected  (or classDef selected ... + class t_platform_health selected)
    assert.ok(
      out.includes("t_platform_health") && out.includes("selected"),
      `Expected 'selected' class applied to t_platform_health:\n${out}`,
    );
    // Specifically a class assignment line
    const lines = out.split("\n");
    const classLine = lines.find(
      l => l.includes("class") && l.includes("t_platform_health") && l.includes("selected"),
    );
    assert.ok(
      classLine !== undefined,
      `Expected a class assignment line for t_platform_health + selected:\n${out}`,
    );
  });

  it("without selectedTrack arg, 'selected' class is NOT assigned to t_platform_health", () => {
    const out = toMermaid(exp);
    // It's ok if 'classDef selected' is always emitted, but the class assignment should not target t_platform_health
    const lines = out.split("\n");
    const classAssignLine = lines.find(
      l =>
        l.trim().startsWith("class ") &&
        l.includes("t_platform_health") &&
        l.includes("selected"),
    );
    assert.ok(
      classAssignLine === undefined,
      `Should NOT assign 'selected' to t_platform_health without selectedTrack:\n${out}`,
    );
  });
});

describe("toMermaid — blocked styling", () => {
  it("t_platform_health gets the 'blocked' class (status=blocked + blockers present)", () => {
    const out = mermaid();
    const lines = out.split("\n");
    // Either a classDef blocked + class assignment, or inline class styling
    const blockedAssign = lines.find(
      l => l.includes("t_platform_health") && l.includes("blocked"),
    );
    assert.ok(
      blockedAssign !== undefined,
      `Expected blocked class assigned to t_platform_health:\n${out}`,
    );
  });
});

describe("toMermaid — label escaping", () => {
  const quotedExp: Export = {
    schema: 1,
    generated_at: "2026-06-07T00:00:00Z",
    tracks: [
      {
        name: "quoted",
        repo: "stylusnexus/test",
        tier: "private",
        status: "active",
        launch_priority: null,
        milestone_alignment: null,
        visibility: null,
        blockers: [],
        next_up: [555],
        rollup: { open: 1, closed: 0 },
        issues: [
          {
            number: 555,
            title: 'auth "rate" limit',
            state: "open",
            assignee: "@x",
            milestone: null,
          },
        ],
      },
    ],
  };

  it("replaces \" with ' in issue titles (prevents \"] delimiter)", () => {
    const out = toMermaid(quotedExp);
    assert.ok(
      out.includes("'rate'"),
      `Expected 'rate' (double-quotes replaced with single-quotes):\n${out}`,
    );
  });

  it("does NOT leak the raw '\"rate\"' sequence into the label (would break Mermaid)", () => {
    const out = toMermaid(quotedExp);
    assert.ok(
      !out.includes('"rate"'),
      `Raw "rate" found unescaped — would break the Mermaid node label:\n${out}`,
    );
  });
});

// ---------------------------------------------------------------------------
// Focus mode tests
// ---------------------------------------------------------------------------

describe("toMermaid — focus mode: org-sharing", () => {
  it("INCLUDES t_org_sharing and i_87 in focused output", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    assert.ok(out.includes("t_org_sharing"), `Expected t_org_sharing:\n${out}`);
    assert.ok(out.includes("i_87"), `Expected i_87:\n${out}`);
  });

  it("INCLUDES the next_up edge t_org_sharing → i_87", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    const lines = out.split("\n");
    const nextUpLine = lines.find(
      l => l.includes("t_org_sharing") && l.includes("next_up") && l.includes("i_87"),
    );
    assert.ok(nextUpLine !== undefined, `Expected next_up edge for org-sharing:\n${out}`);
  });

  it("EXCLUDES t_platform_health from org-sharing focused output", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    assert.ok(!out.includes("t_platform_health"), `t_platform_health should be absent:\n${out}`);
  });

  it("EXCLUDES t_idea_mode from org-sharing focused output", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    assert.ok(!out.includes("t_idea_mode"), `t_idea_mode should be absent:\n${out}`);
  });

  it("EXCLUDES i_4821 from org-sharing focused output", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    assert.ok(!out.includes("i_4821"), `i_4821 should be absent:\n${out}`);
  });

  it("EXCLUDES i_487 from org-sharing focused output", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    assert.ok(!out.includes("i_487"), `i_487 should be absent:\n${out}`);
  });

  it("EXCLUDES i_1556 from org-sharing focused output", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    assert.ok(!out.includes("i_1556"), `i_1556 should be absent:\n${out}`);
  });

  it("assigns 'selected' class to t_org_sharing in focused output", () => {
    const out = toMermaid(exp, "org-sharing", { focus: true });
    const lines = out.split("\n");
    const classLine = lines.find(
      l => l.includes("class") && l.includes("t_org_sharing") && l.includes("selected"),
    );
    assert.ok(classLine !== undefined, `Expected selected class for t_org_sharing:\n${out}`);
  });
});

describe("toMermaid — focus mode: platform-health", () => {
  it("INCLUDES t_platform_health in focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    assert.ok(out.includes("t_platform_health"), `Expected t_platform_health:\n${out}`);
  });

  it("INCLUDES i_4821 (blocker) in focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    assert.ok(out.includes("i_4821"), `Expected i_4821:\n${out}`);
  });

  it("INCLUDES t_idea_mode (owns #4821) in focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    assert.ok(out.includes("t_idea_mode"), `Expected t_idea_mode (owns #4821):\n${out}`);
  });

  it("INCLUDES i_487 (next_up) in focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    assert.ok(out.includes("i_487"), `Expected i_487:\n${out}`);
  });

  it("INCLUDES i_1556 (next_up) in focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    assert.ok(out.includes("i_1556"), `Expected i_1556:\n${out}`);
  });

  it("INCLUDES the blocks edge i_4821 →|blocks| t_platform_health", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    const lines = out.split("\n");
    const blocksLine = lines.find(
      l => l.includes("i_4821") && l.includes("blocks") && l.includes("t_platform_health"),
    );
    assert.ok(blocksLine !== undefined, `Expected blocks edge:\n${out}`);
  });

  it("INCLUDES the owns edge t_idea_mode →|owns #4821| t_platform_health", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    const lines = out.split("\n");
    const ownsLine = lines.find(
      l => l.includes("t_idea_mode") && l.includes("owns") && l.includes("4821") && l.includes("t_platform_health"),
    );
    assert.ok(ownsLine !== undefined, `Expected owns edge:\n${out}`);
  });

  it("INCLUDES the next_up edge t_platform_health → i_487", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    const lines = out.split("\n");
    const nextUpLine = lines.find(
      l => l.includes("t_platform_health") && l.includes("next_up") && l.includes("i_487"),
    );
    assert.ok(nextUpLine !== undefined, `Expected next_up edge:\n${out}`);
  });

  it("INCLUDES the dashed 'then' edge i_487 → i_1556", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    const lines = out.split("\n");
    const thenLine = lines.find(
      l => l.includes("i_487") && l.includes("then") && l.includes("i_1556"),
    );
    assert.ok(thenLine !== undefined, `Expected then edge:\n${out}`);
  });

  it("EXCLUDES t_org_sharing from platform-health focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    assert.ok(!out.includes("t_org_sharing"), `t_org_sharing should be absent:\n${out}`);
  });

  it("EXCLUDES i_87 from platform-health focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    assert.ok(!out.includes("i_87"), `i_87 should be absent:\n${out}`);
  });

  it("assigns 'selected' class to t_platform_health in focused output", () => {
    const out = toMermaid(exp, "platform-health", { focus: true });
    const lines = out.split("\n");
    const classLine = lines.find(
      l => l.includes("class") && l.includes("t_platform_health") && l.includes("selected"),
    );
    assert.ok(classLine !== undefined, `Expected selected class for t_platform_health:\n${out}`);
  });
});

describe("toMermaid — focus:false == full graph", () => {
  it("focus:false still contains org-sharing (full graph unchanged)", () => {
    const out = toMermaid(exp, "platform-health", { focus: false });
    assert.ok(out.includes("t_org_sharing"), `Expected t_org_sharing in full graph:\n${out}`);
  });

  it("no opts still contains org-sharing (full graph unchanged)", () => {
    const out = toMermaid(exp, "platform-health");
    assert.ok(out.includes("t_org_sharing"), `Expected t_org_sharing in full graph:\n${out}`);
  });

  it("focus:false output is identical to no-opts output", () => {
    assert.strictEqual(
      toMermaid(exp, "platform-health", { focus: false }),
      toMermaid(exp, "platform-health"),
    );
  });
});

describe("toMermaid — focus fallback on unknown track", () => {
  it("does not throw for unknown track name with focus:true", () => {
    assert.doesNotThrow(() => toMermaid(exp, "does-not-exist", { focus: true }));
  });

  it("falls back to full graph when selectedTrack is not found", () => {
    const out = toMermaid(exp, "does-not-exist", { focus: true });
    assert.ok(out.includes("t_org_sharing"), `Expected full graph fallback:\n${out}`);
    assert.ok(out.includes("t_platform_health"), `Expected full graph fallback:\n${out}`);
    assert.ok(out.includes("t_idea_mode"), `Expected full graph fallback:\n${out}`);
  });
});

describe("toMermaid — next_up self-loop dedup", () => {
  const dupExp: Export = {
    schema: 1,
    generated_at: "2026-06-07T00:00:00Z",
    tracks: [
      {
        name: "dup",
        repo: "stylusnexus/test",
        tier: "private",
        status: "active",
        launch_priority: null,
        milestone_alignment: null,
        visibility: null,
        blockers: [],
        next_up: [10, 10, 20],
        rollup: { open: 0, closed: 0 },
        issues: [],
      },
    ],
  };

  it("repeated consecutive next_up does NOT emit a i_10 -.->|then| i_10 self-loop", () => {
    const out = toMermaid(dupExp);
    assert.ok(
      !out.includes("i_10 -.->|then| i_10"),
      `Self-loop then-edge emitted for repeated next_up entry:\n${out}`,
    );
  });

  it("still emits the i_10 -.->|then| i_20 transition after the dedup", () => {
    const out = toMermaid(dupExp);
    assert.ok(
      out.includes("i_10 -.->|then| i_20"),
      `Expected the 10→20 then-edge to survive dedup:\n${out}`,
    );
  });
});

describe("toMermaid — track id collision disambiguation", () => {
  const collisionExp: Export = {
    schema: 1,
    generated_at: "2026-06-09T00:00:00Z",
    tracks: [
      {
        name: "my-track",
        repo: "org/repo",
        tier: "private",
        status: "active",
        launch_priority: null,
        milestone_alignment: null,
        visibility: null,
        blockers: [],
        next_up: [1],
        rollup: { open: 0, closed: 0 },
        issues: [
          { number: 1, title: "test issue", state: "open", assignee: "@x", milestone: null },
        ],
      },
      {
        name: "my_track",
        repo: "org/repo",
        tier: "private",
        status: "active",
        launch_priority: null,
        milestone_alignment: null,
        visibility: null,
        blockers: [1],
        next_up: [],
        rollup: { open: 0, closed: 0 },
        issues: [],
      },
    ],
  };

  it("produces distinct node ids for my-track and my_track", () => {
    const out = toMermaid(collisionExp);
    // Both track names should appear in the output as distinct node declarations.
    const lines = out.split("\n");
    const trackLines = lines.filter(
      l => l.match(/^\s+t_my_track/) && l.includes('["'),
    );
    assert.strictEqual(
      trackLines.length,
      2,
      `Expected 2 distinct track node declarations, got ${trackLines.length}:\n${out}`,
    );
    const ids = trackLines.map(l => l.trim().split(/[\s\[]/)[0]);
    assert.notStrictEqual(
      ids[0],
      ids[1],
      `Expected different node ids for the two tracks, got ${ids[0]} and ${ids[1]}:\n${out}`,
    );
  });

  it("first-seen track keeps the bare sanitised id", () => {
    const out = toMermaid(collisionExp);
    // "my-track" appears first in the tracks array → id should be t_my_track.
    assert.ok(
      out.includes('t_my_track["my-track"]'),
      `Expected first track to get the unsuffixed id t_my_track:\n${out}`,
    );
  });

  it("second colliding track gets a suffixed id", () => {
    const out = toMermaid(collisionExp);
    // "my_track" is second → id should be t_my_track_1. Tolerate the blocked
    // marker (#244) — this track has a blocker, so its label is prefixed.
    assert.ok(
      /t_my_track_1\["(?:⛔ )?my_track"\]/.test(out),
      `Expected second track to get suffixed id t_my_track_1:\n${out}`,
    );
  });

  it("edges use the correct disambiguated track id", () => {
    const out = toMermaid(collisionExp);
    // my-track (t_my_track) has next_up → i_1
    assert.ok(
      out.includes("t_my_track -->|next_up| i_1"),
      `Expected next_up edge from first track:\n${out}`,
    );
    // my_track (t_my_track_1) has i_1 blocks → my_track
    assert.ok(
      out.includes("i_1 -->|blocks| t_my_track_1"),
      `Expected blocks edge to second track:\n${out}`,
    );
    // owns edge: t_my_track (owns issue 1) → t_my_track_1
    assert.ok(
      out.includes("t_my_track -->|owns #1| t_my_track_1"),
      `Expected owns edge from first track to second:\n${out}`,
    );
  });

  it("single-track exports still use bare ids (no regression)", () => {
    const singleTrackExp: Export = {
      schema: 1,
      generated_at: "2026-06-09T00:00:00Z",
      tracks: [
        {
          name: "platform-health",
          repo: "org/repo",
          tier: "private",
          status: "active",
          launch_priority: null,
          milestone_alignment: null,
          visibility: null,
          blockers: [],
          next_up: [1],
          rollup: { open: 0, closed: 0 },
          issues: [
            { number: 1, title: "test", state: "open", assignee: "@x", milestone: null },
          ],
        },
      ],
    };
    const out = toMermaid(singleTrackExp);
    assert.ok(out.includes("t_platform_health"), `Expected bare id:\n${out}`);
    // No suffix should appear for a single track.
    assert.ok(
      !out.includes("t_platform_health_"),
      `Unexpected suffixed id for single track:\n${out}`,
    );
  });

  it("deterministic: identical collision input produces identical output", () => {
    assert.strictEqual(toMermaid(collisionExp), toMermaid(collisionExp));
  });
});

describe("toMermaid — label escaping (brackets/parens/braces/backticks)", () => {
  const specialTitleExp: Export = {
    schema: 1,
    generated_at: "2026-06-09T00:00:00Z",
    tracks: [
      {
        name: "special",
        repo: "org/repo",
        tier: "private",
        status: "active",
        launch_priority: null,
        milestone_alignment: null,
        visibility: null,
        blockers: [10, 20, 30, 40, 50],
        next_up: [],
        rollup: { open: 0, closed: 0 },
        issues: [
          { number: 10, title: "Fix [API] rate limit", state: "open", assignee: "@x", milestone: null },
          { number: 20, title: "Update (urgent) dependencies", state: "open", assignee: "@x", milestone: null },
          { number: 30, title: "Handle {JSON} parsing", state: "open", assignee: "@x", milestone: null },
          { number: 40, title: 'Auth "token" refresh', state: "open", assignee: "@x", milestone: null },
          { number: 50, title: "Run `migrate` script", state: "open", assignee: "@x", milestone: null },
        ],
      },
    ],
  };

  it("replaces [ and ] in issue titles with ( and )", () => {
    const out = toMermaid(specialTitleExp);
    // [API] → (API) — the characters are replaced with safe literal chars
    assert.ok(out.includes("(API)"), `Expected (API) for '[API]' in title:\n${out}`);
    assert.ok(!out.includes("[API]"), `Raw '[API]' should not appear:\n${out}`);
  });

  it("leaves ( and ) in issue titles unchanged (safe inside labels)", () => {
    const out = toMermaid(specialTitleExp);
    // (urgent) stays as (urgent) — parens are safe inside Mermaid labels
    assert.ok(out.includes("(urgent)"), `Expected (urgent) unchanged in title:\n${out}`);
  });

  it("replaces { and } in issue titles with ( and )", () => {
    const out = toMermaid(specialTitleExp);
    // {JSON} → (JSON)
    assert.ok(out.includes("(JSON)"), `Expected (JSON) for '{JSON}' in title:\n${out}`);
    assert.ok(!out.includes("{JSON}"), `Raw '{JSON}' should not appear:\n${out}`);
  });

  it("replaces backticks in issue titles with '", () => {
    const out = toMermaid(specialTitleExp);
    // `migrate` → 'migrate'
    assert.ok(out.includes("'migrate'"), `Expected 'migrate' for backtick in title:\n${out}`);
    assert.ok(!out.includes("`migrate`"), `Raw backtick should not appear:\n${out}`);
  });

  it("replaces \" with ' in issue titles (prevents \"] delimiter)", () => {
    const out = toMermaid(specialTitleExp);
    assert.ok(out.includes("'token'"), `Expected 'token' for embedded quote:\n${out}`);
    assert.ok(!out.includes('"token"'), `Raw double-quote should not appear:\n${out}`);
  });

  it("no raw [, ], {, }, \", or backtick leak into node labels", () => {
    const out = toMermaid(specialTitleExp);
    // The raw characters that would form Mermaid delimiters must NOT appear.
    // Parens are safe — they may appear as replacements or pass through unchanged.
    const nodeRegex = /\bi_\d+\(\["(.*?)"\]\)/g;
    let match: RegExpExecArray | null;
    while ((match = nodeRegex.exec(out)) !== null) {
      const label = match[1];
      assert.ok(!label.includes("["), `Raw '[' leaked into label: "${label}"`);
      assert.ok(!label.includes("]"), `Raw ']' leaked into label: "${label}"`);
      assert.ok(!label.includes("{"), `Raw '{' leaked into label: "${label}"`);
      assert.ok(!label.includes("}"), `Raw '}' leaked into label: "${label}"`);
      assert.ok(!label.includes('"'), `Raw '\"' leaked into label: "${label}"`);
      assert.ok(!label.includes("`"), `Raw backtick leaked into label: "${label}"`);
    }
  });

  it("track name label with special chars replaced", () => {
    const bracketTrackExp: Export = {
      schema: 1,
      generated_at: "2026-06-09T00:00:00Z",
      tracks: [
        {
          name: "fix [API] (v2) {urgent}",
          repo: "org/repo",
          tier: "private",
          status: "active",
          launch_priority: null,
          milestone_alignment: null,
          visibility: null,
          blockers: [],
          next_up: [],
          rollup: { open: 0, closed: 0 },
          issues: [],
        },
      ],
    };
    const out = toMermaid(bracketTrackExp);
    // Track labels are ["..."] (rectangle).  The replaced label should be
    // "fix (API) (v2) (urgent)" — brackets/braces → parens.
    const trackLabelMatch = out.match(/t_fix__API___v2___urgent_\["(.*?)"\]/);
    assert.ok(trackLabelMatch !== null, `Expected track node definition:\n${out}`);
    const label = trackLabelMatch![1];
    assert.ok(!label.includes("["), "Raw '[' should not appear in track name label");
    assert.ok(!label.includes("]"), "Raw ']' should not appear in track name label");
    assert.ok(!label.includes("{"), "Raw '{' should not appear in track name label");
    assert.ok(!label.includes("}"), "Raw '}' should not appear in track name label");
    assert.ok(!label.includes('"'), "Raw '\"' should not appear in track name label");
    assert.ok(!label.includes("`"), "Raw backtick should not appear in track name label");
    // Parens ARE present (as replacements or pass-through).
    assert.ok(label.includes("(API)"), `Expected (API) in label, got: "${label}"`);
    assert.ok(label.includes("(v2)"), `Expected (v2) in label, got: "${label}"`);
    assert.ok(label.includes("(urgent)"), `Expected (urgent) in label, got: "${label}"`);
  });
});

describe("toMermaid — depends_on edges (#102)", () => {
  const depExp: Export = {
    schema: 1,
    generated_at: "2026-06-09T00:00:00Z",
    tracks: [
      {
        name: "alpha",
        repo: "org/repo",
        tier: "private",
        status: "active",
        launch_priority: null,
        milestone_alignment: null,
        visibility: null,
        blockers: [],
        next_up: [],
        depends_on: ["beta"],
        rollup: { open: 0, closed: 0 },
        issues: [],
      },
      {
        name: "beta",
        repo: "org/repo",
        tier: "private",
        status: "active",
        launch_priority: null,
        milestone_alignment: null,
        visibility: null,
        blockers: [],
        next_up: [],
        depends_on: [],
        rollup: { open: 0, closed: 0 },
        issues: [],
      },
    ],
  };

  it("emits a thick 'depends on' edge from alpha to beta", () => {
    const out = toMermaid(depExp);
    const lines = out.split("\n");
    const depLine = lines.find(
      l => l.includes("t_alpha") && l.includes("depends on") && l.includes("t_beta"),
    );
    assert.ok(depLine !== undefined, `Expected depends on edge:\n${out}`);
  });

  it("uses thick arrow (==>) for depends_on edges", () => {
    const out = toMermaid(depExp);
    assert.ok(
      out.includes("==>|depends on|"),
      `Expected ==>|depends on| thick arrow:\n${out}`,
    );
  });

  it("track without depends_on has no dependency edges", () => {
    // beta has empty depends_on — no outgoing dependency edges
    const out = toMermaid(depExp);
    const lines = out.split("\n");
    const betaDepEdge = lines.find(
      l => l.startsWith("  t_beta") && l.includes("depends on"),
    );
    assert.strictEqual(
      betaDepEdge,
      undefined,
      `Beta should not emit depends_on edges:\n${out}`,
    );
  });

  it("focused graph includes tracks in dependency neighbourhood", () => {
    const out = toMermaid(depExp, "alpha", { focus: true });
    // alpha depends_on beta → beta should be included in focused view
    assert.ok(
      out.includes("t_beta"),
      `Focused alpha should include beta (dependency):\n${out}`,
    );
    assert.ok(
      out.includes("depends on"),
      `Focused alpha should show depends on edge:\n${out}`,
    );
  });

  it("focused graph includes tracks that depend on the selected track", () => {
    const out = toMermaid(depExp, "beta", { focus: true });
    // alpha depends_on beta → alpha should be included when focused on beta
    assert.ok(
      out.includes("t_alpha"),
      `Focused beta should include alpha (reverse dependency):\n${out}`,
    );
  });
});

// ---------------------------------------------------------------------------
// Hostile issue-title corpus → label escaper grammar contract (#197)
// ---------------------------------------------------------------------------
//
// mermaid.parse() needs a DOM (jsdom), which this stdlib `node --test` setup
// does not provide. So instead of round-tripping through the real parser we
// lock the grammar contract directly: the escaper output must contain none of
// the characters that can terminate or break a Mermaid `["..."]` /
// `(["..."])` node label, and embedding a hostile title in a full toMermaid()
// graph must keep every node statement on its own single line.

describe("mermaidLabel — hostile-title corpus (#197)", () => {
  const hostileTitles = [
    'foo")',                       // closes the SQE token then the bracket
    'bar"]',                       // raw "] terminates the label
    "line one\nline two",          // newline aborts the node statement
    "carriage\rreturn",            // lone CR
    "windows\r\nnewline",          // CRLF
    "</script><img src=x>",        // HTML/script injection attempt
    '"[]{}`',                      // every bracket/quote/backtick at once
    ";|()&<>",                     // pipe/semicolon/paren/entity chars
    "100% done (maybe?)",          // benign-looking but paren-heavy
    "a".repeat(500) + '"]',        // long title ending in the SQE token
  ];

  // Characters that, if present RAW in the escaper output, can break the
  // `["..."]` label grammar: the double-quote (closes the string), square
  // brackets and braces (bracket grammar), the backtick, and any newline.
  const forbiddenRaw = ['"', "[", "]", "{", "}", "`", "\n", "\r"];

  for (const title of hostileTitles) {
    it(`neutralises grammar-breakers in: ${JSON.stringify(title.slice(0, 40))}`, () => {
      const out = mermaidLabel(title);
      for (const ch of forbiddenRaw) {
        assert.ok(
          !out.includes(ch),
          `escaped label must not contain raw ${JSON.stringify(ch)}: ${JSON.stringify(out)}`,
        );
      }
    });
  }

  it("escaper is idempotent on already-safe output", () => {
    for (const title of hostileTitles) {
      const once = mermaidLabel(title);
      // A second pass may re-escape '&' inside entities, but must still produce
      // no forbidden raw grammar chars.
      const twice = mermaidLabel(once);
      for (const ch of forbiddenRaw) {
        assert.ok(!twice.includes(ch), `double-escape leaked ${JSON.stringify(ch)}`);
      }
    }
  });

  it("hostile titles in a full graph keep node statements on a single line", () => {
    const exp: Export = {
      schema: 1,
      generated_at: "2026-06-10T00:00:00Z",
      tracks: [
        {
          name: 'evil")\nx["pwned',
          repo: "stylusnexus/work-plan-toolkit",
          tier: "shared",
          status: "active",
          launch_priority: "P1",
          milestone_alignment: null,
          visibility: "PUBLIC",
          blockers: [],
          next_up: [42],
          rollup: { open: 1, closed: 0 },
          issues: [
            { number: 42, title: 'boom"]\nclass x evil', state: "open", assignee: "@x", milestone: null },
          ],
        },
      ],
    };

    const out = toMermaid(exp);

    // Every node-definition line must be balanced: opening `["` is matched by a
    // closing `"]` on the SAME line, and no label content introduced a newline.
    for (const line of out.split("\n")) {
      const opens = (line.match(/\["/g) ?? []).length;
      const closes = (line.match(/"\]/g) ?? []).length;
      assert.equal(
        opens,
        closes,
        `unbalanced label quoting on line: ${JSON.stringify(line)}`,
      );
    }

    // The injected `x["` must NOT have survived as raw Mermaid node syntax:
    // the newline collapsed to a space and the `[` became `(`, so "pwned" is
    // now inert escaped text inside the single track label, not a second node.
    // There must be exactly one track-node definition (the `["..."]` form) and
    // one issue-node definition (the `(["..."])` form) — no extras spawned by
    // the injected bracket.
    const trackNodeLines = out
      .split("\n")
      .filter(l => /^\s+t_\S+\["/.test(l));
    assert.equal(
      trackNodeLines.length,
      1,
      `newline/bracket injection spawned extra track nodes:\n${out}`,
    );
    assert.ok(
      !out.includes('x["pwned'),
      `raw 'x["pwned' node syntax leaked into the graph:\n${out}`,
    );
  });
});

describe("toMermaid — theme-aware classDef fills (#207)", () => {
  it("dark option emits the dark-theme classDef palette", () => {
    const out = toMermaid(exp, "platform-health", { dark: true });
    assert.ok(out.includes("classDef blocked fill:#5b1d1d"), `expected dark blocked fill:\n${out}`);
    assert.ok(out.includes("classDef selected fill:#1e3a5f"), `expected dark selected fill:\n${out}`);
  });

  it("light option emits the light-theme classDef palette", () => {
    const out = toMermaid(exp, "platform-health", { dark: false });
    assert.ok(out.includes("classDef blocked fill:#fee2e2"), `expected light blocked fill:\n${out}`);
    assert.ok(out.includes("classDef selected fill:#dbeafe"), `expected light selected fill:\n${out}`);
  });
});

describe("toMermaid — blocked nodes carry a non-colour marker (#244)", () => {
  it("prefixes a blocked track node label with the ⛔ glyph", () => {
    // platform-health is blocked in the fixture.
    const out = toMermaid(exp);
    assert.ok(out.includes('⛔ '), `expected a ⛔ marker on a blocked node:\n${out}`);
  });
});
