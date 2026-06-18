import { createHash } from "node:crypto";

/**
 * The compare-and-swap fingerprint of a track's issue list (#241). MUST byte-match
 * the CLI's `lib/membership_guard.issues_fingerprint`, which in Python is:
 *
 *   sha256(json.dumps(sorted(issue_ints), separators=(",",":")).encode()).hexdigest()[:16]
 *
 * `JSON.stringify` of a sorted number array yields `"[1,2,3]"` — no spaces —
 * exactly matching Python's compact `separators=(",",":")` output, so the two
 * sides hash identical bytes. The sort is numeric (not the default lexicographic
 * `Array.prototype.sort`) so `[20,10]` and `[10,20]` collapse to the same value.
 *
 * The viewer passes the result as `--expect=<fp>`: if the on-disk list changed
 * since the suggestion was offered, the CLI aborts with `{stale}` and the caller
 * re-offers on fresh state instead of clobbering.
 */
export function issuesFingerprint(issues: number[]): string {
  const sorted = [...issues].sort((a, b) => a - b);
  return createHash("sha256").update(JSON.stringify(sorted)).digest("hex").slice(0, 16);
}
