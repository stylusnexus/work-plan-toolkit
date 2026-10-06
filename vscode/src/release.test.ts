/**
 * Release-metadata guard: the extension version in package.json must have a
 * matching entry in vscode/CHANGELOG.md (the Marketplace Changelog tab) and in
 * the `## Status` list of vscode/README.md.
 *
 * Why this exists: the changelog silently stopped being updated after 0.19.4 and
 * missed six releases, because the release steps only mentioned the README Status
 * line and nothing checked the file. A version bump without its entries now fails
 * CI instead of shipping a stale Changelog tab.
 */
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (f: string): string => readFileSync(join(root, f), "utf8").replace(/\r\n/g, "\n");

const version: string = JSON.parse(read("package.json")).version;
const changelog = read("CHANGELOG.md");
const readme = read("README.md");

const versionHeadings = [...changelog.matchAll(/^## \[(\d+\.\d+\.\d+)\] - (\S+)$/gm)].map(m => ({
  version: m[1],
  date: m[2],
  index: m.index ?? 0,
}));

const cmp = (a: string, b: string): number => {
  const [x, y] = [a, b].map(v => v.split(".").map(Number));
  return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
};

describe("release metadata (package.json ↔ CHANGELOG.md ↔ README Status)", () => {
  test("package.json has a plain semver version", () => {
    assert.match(version, /^\d+\.\d+\.\d+$/);
  });

  test("CHANGELOG.md has an entry for the current version", () => {
    assert.ok(
      versionHeadings.some(h => h.version === version),
      `vscode/CHANGELOG.md has no "## [${version}] - YYYY-MM-DD" entry. ` +
        `Add one when you bump package.json (see CLAUDE.md → Releasing (maintainers)).`,
    );
  });

  test("the current version is the newest entry in CHANGELOG.md", () => {
    assert.equal(
      versionHeadings[0]?.version,
      version,
      `The newest vscode/CHANGELOG.md entry is ${versionHeadings[0]?.version}, ` +
        `but package.json is ${version}. Bump both together.`,
    );
  });

  test("the current entry has a real date and at least one bullet", () => {
    const i = versionHeadings.findIndex(h => h.version === version);
    assert.ok(i >= 0, "no entry for the current version");
    assert.match(versionHeadings[i].date, /^\d{4}-\d{2}-\d{2}$/);
    const end = versionHeadings[i + 1]?.index ?? changelog.length;
    const body = changelog.slice(versionHeadings[i].index, end);
    assert.match(body, /^- \S/m, `the [${version}] entry has no bullet points`);
  });

  test("changelog versions are unique and newest-first", () => {
    const seen = versionHeadings.map(h => h.version);
    assert.equal(new Set(seen).size, seen.length, "duplicate version headings in vscode/CHANGELOG.md");
    for (let i = 1; i < seen.length; i++) {
      assert.ok(cmp(seen[i - 1], seen[i]) > 0, `${seen[i - 1]} must come before ${seen[i]} (newest first)`);
    }
  });

  test("README Status names the current version as published and lists it", () => {
    const status = readme.split(/^## Status$/m)[1] ?? "";
    assert.ok(status !== "", "vscode/README.md has no '## Status' section");
    assert.match(
      status,
      new RegExp(`\\*\\*Published — v${version.replace(/\./g, "\\.")} on the`),
      `The README Status line must read "Published — v${version}".`,
    );
    assert.match(
      status,
      new RegExp(`^- \\*\\*v${version.replace(/\./g, "\\.")}\\*\\* — `, "m"),
      `The README Status list has no "- **v${version}** — …" bullet.`,
    );
  });
});
