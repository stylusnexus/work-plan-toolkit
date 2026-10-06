import { test } from "node:test";
import assert from "node:assert/strict";
import {
  packageName, findBlocked, findUnreviewedInstallScripts,
  changedRegistryPackages, versionStatus,
} from "./lockfile-integrity.mjs";

const R = "https://registry.npmjs.org/";
const pkg = (version, extra = {}) => ({ version, resolved: `${R}x/-/x-${version}.tgz`, ...extra });

test("packageName takes the innermost, scope-aware name", () => {
  assert.equal(packageName("node_modules/a"), "a");
  assert.equal(packageName("node_modules/a/node_modules/@s/b"), "@s/b");
});

test("findBlocked catches a nested blocked package", () => {
  const lock = { packages: { "": {}, "node_modules/ok": pkg("1.0.0"),
    "node_modules/ok/node_modules/plain-crypto-js": pkg("1.0.0") } };
  assert.deepEqual(findBlocked(lock), ["plain-crypto-js"]);
});

test("findBlocked is silent on a clean lockfile", () => {
  assert.deepEqual(findBlocked({ packages: { "node_modules/ok": pkg("1.0.0") } }), []);
});

test("install scripts: allowlisted passes, others are reported", () => {
  const lock = { packages: {
    "node_modules/esbuild": pkg("1.0.0", { hasInstallScript: true }),
    "node_modules/evil": pkg("1.0.0", { hasInstallScript: true }),
    "node_modules/plain": pkg("1.0.0") } };
  assert.deepEqual(findUnreviewedInstallScripts(lock), ["evil"]);
});

test("allowlist does not match by prefix", () => {
  const lock = { packages: { "node_modules/esbuild-evil": pkg("1.0.0", { hasInstallScript: true }) } };
  assert.deepEqual(findUnreviewedInstallScripts(lock), ["esbuild-evil"]);
});

test("changed packages: unchanged is skipped, bumped and new are returned", () => {
  const base = { packages: { "node_modules/a": pkg("1.0.0"), "node_modules/b": pkg("1.0.0") } };
  const lock = { packages: { "node_modules/a": pkg("1.0.0"), "node_modules/b": pkg("1.1.0"),
    "node_modules/c": pkg("2.0.0") } };
  assert.deepEqual(changedRegistryPackages(lock, base),
    [{ name: "b", version: "1.1.0" }, { name: "c", version: "2.0.0" }]);
});

test("changed packages: a nested copy is checked, not just the top level", () => {
  const base = { packages: { "node_modules/a": pkg("1.0.0") } };
  const lock = { packages: { "node_modules/a": pkg("1.0.0"),
    "node_modules/a/node_modules/dep": pkg("3.0.0") } };
  assert.deepEqual(changedRegistryPackages(lock, base), [{ name: "dep", version: "3.0.0" }]);
});

test("changed packages: no base means everything counts, non-registry skipped", () => {
  const lock = { packages: { "": {}, "node_modules/a": pkg("1.0.0"),
    "node_modules/g": { version: "1.0.0", resolved: "git+https://x/y.git" } } };
  assert.deepEqual(changedRegistryPackages(lock, null), [{ name: "a", version: "1.0.0" }]);
});

test("versionStatus: 404 is missing, 200 ok, 500 and network errors unknown", async () => {
  const f = (status) => async () => ({ status, ok: status < 400 });
  assert.equal(await versionStatus({ name: "a", version: "1" }, f(404)), "missing");
  assert.equal(await versionStatus({ name: "a", version: "1" }, f(200)), "ok");
  assert.equal(await versionStatus({ name: "a", version: "1" }, f(500)), "unknown");
  assert.equal(await versionStatus({ name: "a", version: "1" }, async () => { throw new Error("net"); }), "unknown");
});

test("versionStatus encodes the scope slash", async () => {
  let url;
  await versionStatus({ name: "@s/b", version: "1.0.0" }, async (u) => { url = u; return { status: 200, ok: true }; });
  assert.equal(url, `${R}@s%2Fb/1.0.0`);
});
