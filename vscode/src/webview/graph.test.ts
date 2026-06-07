/**
 * Tests for src/webview/graph.ts — pure Mermaid graph derivation.
 *
 * Fixture mirrors the mockup:
 *   CritForge (PRIVATE):
 *     • platform-health — blocked, blockers:[4821], next_up:[487,1556]
 *     • idea-mode       — active,  blockers:[],    next_up:[4821]
 *   work-plan-toolkit (PUBLIC):
 *     • org-sharing     — active,  blockers:[],    next_up:[87]
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import type { Export } from "../model.ts";
import { toMermaid } from "./graph.ts";

// ---------------------------------------------------------------------------
// Fixture
// ---------------------------------------------------------------------------

const exp: Export = {
  schema: 1,
  generated_at: "2026-06-07T00:00:00Z",
  tracks: [
    {
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
        { number: 487,  title: "auth rate limit",  state: "open",   assignee: "@alice", milestone: "M1" },
        { number: 1556, title: "session cache",    state: "open",   assignee: "@bob",   milestone: "M1" },
        { number: 2196, title: "RLS audit",        state: "closed", assignee: "—",      milestone: null },
        { number: 2528, title: "poll schema",      state: "open",   assignee: "@alice", milestone: null },
      ],
    },
    {
      name: "idea-mode",
      repo: "stylusnexus/CritForge",
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

  it("escapes a double-quote in an issue title to &quot;", () => {
    const out = toMermaid(quotedExp);
    assert.ok(
      out.includes("&quot;"),
      `Expected &quot; for the quoted title:\n${out}`,
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
