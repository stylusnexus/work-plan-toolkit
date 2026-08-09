import type { Export } from "./model.ts";

// ---------------------------------------------------------------------------
// Last-good tree persistence (#485)
// ---------------------------------------------------------------------------
//
// `gh auth status` makes a live token-validation call, so a momentary network
// failure — waking from sleep, a reconnecting VPN — reports a healthy session as
// signed out. tree.ts already keeps the last-good tree through an untrustworthy
// probe, but only while a tree exists in memory: after a window reload the cache
// is null, so the blip wipes the view and shows a sign-in banner to someone who
// never signed out. That's the "annoying every time I come back" case.
//
// Persisting the last-good export closes it. The snapshot is only ever consulted
// as a fallback — the very next successful refresh overwrites it — so the worst
// case is briefly showing tracks that are a few minutes stale, which is exactly
// what the load-error indicator is for.

/** Bump when the persisted shape changes. A mismatch is dropped, not migrated —
 *  the cost is one refresh, and a mis-read snapshot would corrupt the tree. */
export const SNAPSHOT_VERSION = 1;

/** Past this, a snapshot is misinformation rather than a cache. A week covers a
 *  long weekend offline without resurrecting a tree from a previous sprint. */
export const SNAPSHOT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export type Snapshot = {
  version: number;
  /** Epoch ms when this was written. */
  savedAt: number;
  export: Export;
  /** Whether the probe that produced this export said we were signed in. Only
   *  ever true for an authoritative success — a negative state is never
   *  resurrected, since we restore the signed-in context key optimistically. */
  wasAuthenticated: boolean;
};

/** The slice of `vscode.Memento` we need, narrowed so this module stays testable
 *  without the vscode runtime. */
export interface SnapshotStore {
  get(): Snapshot | undefined;
  set(value: Snapshot | undefined): void;
}

/** The globalState key. Exported so extension.ts and any future migration agree
 *  on one spelling. */
export const SNAPSHOT_KEY = "workPlan.lastGoodSnapshot";

export function makeSnapshot(
  exp: Export,
  auth: { authenticated: boolean } | null,
  now: number,
): Snapshot {
  return {
    version: SNAPSHOT_VERSION,
    savedAt: now,
    export: exp,
    wasAuthenticated: auth?.authenticated === true,
  };
}

/**
 * Returns the persisted snapshot when it's still trustworthy, else null. Never
 * throws: the store holds whatever a previous version (or a corrupted profile
 * sync) left behind, and a bad snapshot must degrade to "no cache", never to a
 * broken activation.
 */
export function readSnapshot(store: SnapshotStore, now: number): Snapshot | null {
  let raw: unknown;
  try {
    raw = store.get();
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;

  const snap = raw as Partial<Snapshot>;
  if (snap.version !== SNAPSHOT_VERSION) return null;
  if (typeof snap.savedAt !== "number" || !Number.isFinite(snap.savedAt)) return null;
  // Future-stamped means the clock moved backwards; the age check can't bound it.
  const age = now - snap.savedAt;
  if (age < 0 || age > SNAPSHOT_MAX_AGE_MS) return null;
  if (typeof snap.export !== "object" || snap.export === null || Array.isArray(snap.export)) {
    return null;
  }
  if (!Array.isArray((snap.export as Export).tracks)) return null;

  return {
    version: SNAPSHOT_VERSION,
    savedAt: snap.savedAt,
    export: snap.export as Export,
    wasAuthenticated: snap.wasAuthenticated === true,
  };
}
