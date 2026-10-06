// Supply-chain checks for an npm lockfile. Pure Node (>=18), no dependencies.
//
//   node lockfile-integrity.mjs <lockfile> [<base-lockfile>]
//
// Errors fail the run; warnings only annotate it. The base lockfile (the
// PR's target branch) is optional: without it every registry package counts as
// changed.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

// Packages that must never appear in the lockfile.
export const BLOCKLIST = [
  "plain-crypto-js",
  "node-hide-console-windows",
  "pluton-logger",
  "event-source-polyfill",
];

// Packages with an install script that we have reviewed (native addons etc.).
export const INSTALL_SCRIPT_ALLOWLIST = [
  /^esbuild$/,
  /^@vscode\/vsce-sign$/,
  /^keytar$/,
];

const REGISTRY = "https://registry.npmjs.org/";
const MAX_PHANTOM_CHECKS = 300;

// "node_modules/a/node_modules/@s/b" -> "@s/b" (the innermost package name).
export function packageName(lockPath) {
  const i = lockPath.lastIndexOf("node_modules/");
  return i === -1 ? lockPath : lockPath.slice(i + "node_modules/".length);
}

export function findBlocked(lock, blocklist = BLOCKLIST) {
  const names = new Set(
    Object.keys(lock.packages ?? {}).filter(Boolean).map(packageName),
  );
  return blocklist.filter((b) => names.has(b));
}

export function findUnreviewedInstallScripts(lock, allow = INSTALL_SCRIPT_ALLOWLIST) {
  return Object.entries(lock.packages ?? {})
    .filter(([p, m]) => p && m.hasInstallScript)
    .map(([p]) => packageName(p))
    .filter((n) => !allow.some((re) => re.test(n)));
}

// Registry packages whose version or resolved URL differs from the base lockfile.
// Keyed on the full lock path, so nested copies are checked too.
export function changedRegistryPackages(lock, base) {
  const before = base?.packages ?? {};
  const out = [];
  for (const [p, m] of Object.entries(lock.packages ?? {})) {
    if (!p || !m.resolved?.startsWith(REGISTRY) || !m.version) continue;
    const prev = before[p];
    if (prev && prev.version === m.version && prev.resolved === m.resolved) continue;
    out.push({ name: packageName(p), version: m.version });
  }
  const seen = new Set();
  return out.filter(({ name, version }) => {
    const k = `${name}@${version}`;
    return seen.has(k) ? false : (seen.add(k), true);
  });
}

// "missing" = registry answered 404; "unknown" = could not tell (network, 5xx).
export async function versionStatus({ name, version }, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${REGISTRY}${name.replace("/", "%2F")}/${version}`, {
      method: "HEAD",
    });
    if (res.status === 404) return "missing";
    return res.ok ? "ok" : "unknown";
  } catch {
    return "unknown";
  }
}

async function mapLimit(items, limit, fn) {
  const out = new Array(items.length);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (next < items.length) {
        const i = next++;
        out[i] = await fn(items[i]);
      }
    }),
  );
  return out;
}

async function main(argv) {
  const [lockPath, basePath] = argv;
  if (!lockPath) {
    console.error("usage: lockfile-integrity.mjs <lockfile> [<base-lockfile>]");
    return 2;
  }
  const lock = JSON.parse(readFileSync(lockPath, "utf8"));
  const base = basePath ? JSON.parse(readFileSync(basePath, "utf8")) : null;
  let failed = false;

  console.log("::group::Known-malicious packages");
  for (const b of findBlocked(lock)) {
    console.log(`::error::BLOCKED package in lockfile: ${b}`);
    failed = true;
  }
  console.log("::endgroup::");

  console.log("::group::Install scripts");
  for (const n of findUnreviewedInstallScripts(lock)) {
    console.log(`::warning::${n} has an install script and is not on the reviewed allowlist.`);
  }
  console.log("::endgroup::");

  console.log("::group::Phantom versions");
  let changed = changedRegistryPackages(lock, base);
  if (changed.length > MAX_PHANTOM_CHECKS) {
    console.log(`::warning::${changed.length} changed packages; checking the first ${MAX_PHANTOM_CHECKS}.`);
    changed = changed.slice(0, MAX_PHANTOM_CHECKS);
  }
  const statuses = await mapLimit(changed, 8, versionStatus);
  changed.forEach((pkg, i) => {
    const id = `${pkg.name}@${pkg.version}`;
    if (statuses[i] === "missing") {
      console.log(`::error::${id} does NOT exist on the npm registry (404). Possible supply-chain attack.`);
      failed = true;
    } else if (statuses[i] === "unknown") {
      console.log(`::warning::could not verify ${id} against the registry.`);
    }
  });
  console.log(`checked ${changed.length} changed package(s)`);
  console.log("::endgroup::");

  return failed ? 1 : 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exit(await main(process.argv.slice(2)));
}
