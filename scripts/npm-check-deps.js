#!/usr/bin/env node
// Postinstall check for the @stylusnexus/work-plan npm package.
//
// The work-plan CLI is pure Python and shells out to three external tools at
// runtime. npm can't install them (they're not npm packages), so we just check
// they're on PATH and print a friendly heads-up if any are missing. This NEVER
// fails the install — a missing tool is the user's to fix, and the CLI prints
// its own clear error if one is absent when actually run.

const { execSync } = require("node:child_process");

const TOOLS = [
  { cmd: "python3", why: "runs the CLI", hint: "https://www.python.org/downloads/ (or `brew install python`)" },
  { cmd: "yq", why: "parses config + frontmatter (mikefarah/yq, the Go one — NOT the python yq)", hint: "brew install yq  ·  https://github.com/mikefarah/yq" },
  { cmd: "gh", why: "reads GitHub issue state", hint: "brew install gh  ·  https://cli.github.com" },
];

function have(cmd) {
  try {
    const probe = process.platform === "win32" ? `where ${cmd}` : `command -v ${cmd}`;
    execSync(probe, { stdio: "ignore", shell: true });
    return true;
  } catch {
    return false;
  }
}

try {
  const missing = TOOLS.filter((t) => !have(t.cmd));
  if (missing.length) {
    const lines = [
      "",
      "  work-plan installed. It needs a few tools on your PATH that npm can't install:",
      ...missing.map((t) => `    • ${t.cmd} — ${t.why}\n        ${t.hint}`),
      "",
      "  (The CLI will tell you specifically if one is missing when you run it.)",
      "",
    ];
    console.warn(lines.join("\n"));
  }
} catch {
  // Never let the check itself break the install.
}
process.exit(0);
