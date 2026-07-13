import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, realpath, symlink, writeFile } from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

import { resolveContainedFile } from "./pathSafety.ts";

async function fixture(): Promise<{ root: string; outside: string }> {
  const base = await mkdtemp(path.join(os.tmpdir(), "work-plan-path-safety-"));
  const root = path.join(base, "repo");
  const outside = path.join(base, "victim.md");
  await mkdir(path.join(root, "docs"), { recursive: true });
  await writeFile(path.join(root, "docs", "plan.md"), "# safe\n");
  await writeFile(outside, "secret\n");
  return { root, outside };
}

describe("resolveContainedFile", () => {
  it("accepts an ordinary plan file inside the repo", async () => {
    const { root } = await fixture();
    assert.equal(
      await resolveContainedFile(root, "docs/plan.md"),
      await realpath(path.join(root, "docs", "plan.md")),
    );
  });

  it("rejects a .. traversal outside the repo", async () => {
    const { root } = await fixture();
    assert.equal(await resolveContainedFile(root, "../victim.md"), null);
  });

  it("rejects an absolute path", async () => {
    const { root, outside } = await fixture();
    assert.equal(await resolveContainedFile(root, outside), null);
  });

  it("rejects an in-repo symlink that resolves outside", async () => {
    const { root, outside } = await fixture();
    await symlink(outside, path.join(root, "docs", "linked.md"));
    assert.equal(await resolveContainedFile(root, "docs/linked.md"), null);
  });
});
