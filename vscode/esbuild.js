// @ts-check
const esbuild = require("esbuild");
const fs = require("fs");
const path = require("path");

const production = process.argv.includes("--production");
const watch = process.argv.includes("--watch");

/** @type {import("esbuild").BuildOptions} */
const buildOptions = {
  entryPoints: ["src/extension.ts"],
  outfile: "dist/extension.js",
  bundle: true,
  platform: "node",
  format: "cjs",
  external: ["vscode"],
  sourcemap: !production,
  minify: production,
};

/**
 * Copy the Mermaid UMD bundle into dist/ so it ships in the VSIX.
 *
 * We ship mermaid.min.js (UMD, self-contained, ~3.3 MB) — the single file
 * that exposes a global `mermaid` object when loaded via a classic <script> tag.
 * This avoids shipping the 160+ ESM chunk files required by the ESM build.
 *
 * The file lands in dist/ which is already gitignored — it must NOT be committed.
 */
function copyMermaid() {
  const src = path.join(
    __dirname,
    "node_modules",
    "mermaid",
    "dist",
    "mermaid.min.js"
  );
  const destDir = path.join(__dirname, "dist");
  const dest = path.join(destDir, "mermaid.min.js");

  if (!fs.existsSync(destDir)) {
    fs.mkdirSync(destDir, { recursive: true });
  }

  fs.copyFileSync(src, dest);
  const stat = fs.statSync(dest);
  console.log(
    `Mermaid bundle copied: dist/mermaid.min.js (${(stat.size / 1024 / 1024).toFixed(1)} MB, UMD)`
  );
}

async function main() {
  if (watch) {
    const ctx = await esbuild.context(buildOptions);
    await ctx.watch();
    copyMermaid();
    console.log("Watching for changes...");
  } else {
    await esbuild.build(buildOptions);
    copyMermaid();
    console.log(`Build complete (${production ? "production" : "development"})`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
