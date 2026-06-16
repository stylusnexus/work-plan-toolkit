// Repo auto-focus decision logic (#357) — pure, no vscode, so it's unit-tested.
// The tree provider and extension activation are thin glue over these.
import type { CliRunner } from "./cli.ts";
import { whichRepo } from "./cli.ts";

/** Who set the active lens. A user choice is sticky; an auto choice is not. */
export type LensSource = "auto" | "user";

/**
 * Whether an incoming lens should replace the current one, given who set the
 * current lens. The only blocked case is an *auto* attempt over a lens the
 * *user* explicitly chose — auto-focus must never fight a human. Everything
 * else applies (user always wins; auto applies over a prior auto).
 */
export function lensShouldApply(current: LensSource, incoming: LensSource): boolean {
  return !(incoming === "auto" && current === "user");
}

/**
 * Resolve the GitHub slug to auto-focus from a list of workspace folder paths:
 * the first folder that maps to a configured repo *with* a github slug wins.
 * Returns null when no folder matches (or every match is slug-less). Folders are
 * probed in order, so a multi-root workspace focuses its first known repo.
 */
export async function pickAutoFocusSlug(
  run: CliRunner,
  folderPaths: string[],
): Promise<string | null> {
  for (const path of folderPaths) {
    const resolved = await whichRepo(run, path);
    if (resolved && resolved.github) return resolved.github;
  }
  return null;
}
