import * as path from "node:path";
import { lstat, realpath } from "node:fs/promises";

/**
 * Resolve a repo-relative plan path for opening in the editor.
 *
 * Returns the canonical existing file path, or null for an absolute path,
 * lexical escape, symlink, missing/non-file target, or realpath escape.
 */
export async function resolveContainedFile(root: string, rel: string): Promise<string | null> {
  if (path.isAbsolute(rel)) return null;

  const lexicalRoot = path.resolve(root);
  const lexicalCandidate = path.resolve(lexicalRoot, rel);
  if (!isDescendant(lexicalRoot, lexicalCandidate)) return null;

  try {
    const [realRoot, realCandidate, candidateInfo] = await Promise.all([
      realpath(lexicalRoot),
      realpath(lexicalCandidate),
      lstat(lexicalCandidate),
    ]);
    if (candidateInfo.isSymbolicLink() || !candidateInfo.isFile()) return null;
    return isDescendant(realRoot, realCandidate) ? realCandidate : null;
  } catch {
    return null;
  }
}

function isDescendant(root: string, candidate: string): boolean {
  const rel = path.relative(root, candidate);
  return rel.length > 0
    && rel !== ".."
    && !rel.startsWith(`..${path.sep}`)
    && !path.isAbsolute(rel);
}
