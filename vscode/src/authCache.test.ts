import { describe, test } from "node:test";
import assert from "node:assert/strict";

import {
  SNAPSHOT_VERSION,
  SNAPSHOT_MAX_AGE_MS,
  SNAPSHOT_MAX_BYTES,
  SNAPSHOT_MIN_WRITE_INTERVAL_MS,
  fitsSizeCap,
  makeSnapshot,
  readSnapshot,
  shouldPersist,
} from "./authCache.ts";
import type { Snapshot, SnapshotStore } from "./authCache.ts";
import type { Export } from "./model.ts";

// ---------------------------------------------------------------------------
// authCache (#485) — last-good tree survives a window reload
// ---------------------------------------------------------------------------

const EXPORT = {
  tracks: [{ name: "alpha", repo: "o/r" }],
  repos: [{ github: "o/r" }],
} as unknown as Export;

/** In-memory stand-in for the globalState memento. */
function memStore(initial?: unknown): SnapshotStore & { written: unknown } {
  let held = initial;
  return {
    get written() { return held; },
    get: () => held as Snapshot | undefined,
    set: (v) => { held = v; },
  };
}

const NOW = 1_700_000_000_000;

describe("authCache", () => {
  test("a snapshot written now round-trips back", () => {
    const store = memStore();
    store.set(makeSnapshot(EXPORT, { authenticated: true }, NOW));
    const got = readSnapshot(store, NOW);
    assert.deepEqual(got?.export, EXPORT);
    assert.equal(got?.wasAuthenticated, true);
  });

  test("stamps the current schema version", () => {
    assert.equal(makeSnapshot(EXPORT, { authenticated: true }, NOW).version, SNAPSHOT_VERSION);
  });

  test("empty store → null (cold first run, no crash)", () => {
    assert.equal(readSnapshot(memStore(), NOW), null);
  });

  test("a snapshot from a future schema version is ignored", () => {
    // Forward-compat: a newer extension wrote a shape we can't read. Dropping it
    // costs one refresh; misreading it would corrupt the tree.
    const store = memStore({ ...makeSnapshot(EXPORT, { authenticated: true }, NOW), version: SNAPSHOT_VERSION + 1 });
    assert.equal(readSnapshot(store, NOW), null);
  });

  test("a snapshot from an older schema version is ignored", () => {
    const store = memStore({ ...makeSnapshot(EXPORT, { authenticated: true }, NOW), version: SNAPSHOT_VERSION - 1 });
    assert.equal(readSnapshot(store, NOW), null);
  });

  test("a snapshot within the age cap is kept", () => {
    const store = memStore(makeSnapshot(EXPORT, { authenticated: true }, NOW));
    assert.notEqual(readSnapshot(store, NOW + SNAPSHOT_MAX_AGE_MS - 1), null);
  });

  test("a snapshot past the age cap is dropped", () => {
    // A tree from a fortnight ago is misinformation, not a cache.
    const store = memStore(makeSnapshot(EXPORT, { authenticated: true }, NOW));
    assert.equal(readSnapshot(store, NOW + SNAPSHOT_MAX_AGE_MS + 1), null);
  });

  test("a snapshot stamped in the future is dropped (clock skew)", () => {
    const store = memStore(makeSnapshot(EXPORT, { authenticated: true }, NOW + 60_000));
    assert.equal(readSnapshot(store, NOW), null);
  });

  test("garbage in the store never throws", () => {
    for (const junk of [null, 42, "nope", [], {}, { version: SNAPSHOT_VERSION }]) {
      assert.equal(readSnapshot(memStore(junk), NOW), null, `junk: ${JSON.stringify(junk)}`);
    }
  });

  test("a snapshot with a non-object export is rejected", () => {
    const store = memStore({ version: SNAPSHOT_VERSION, savedAt: NOW, export: "tracks", wasAuthenticated: true });
    assert.equal(readSnapshot(store, NOW), null);
  });

  test("only an authenticated state is ever persisted as authenticated", () => {
    // We restore the signed-in context key optimistically on cold start, so a
    // negative state must never be resurrected — that would show a sign-in
    // banner before the probe has even run.
    assert.equal(makeSnapshot(EXPORT, { authenticated: false }, NOW).wasAuthenticated, false);
    assert.equal(makeSnapshot(EXPORT, null, NOW).wasAuthenticated, false);
  });

  test("the first write is never throttled", () => {
    assert.equal(shouldPersist(null, NOW), true);
  });

  test("a second write inside the throttle window is skipped", () => {
    assert.equal(shouldPersist(NOW, NOW + SNAPSHOT_MIN_WRITE_INTERVAL_MS - 1), false);
  });

  test("a write past the throttle window goes through", () => {
    assert.equal(shouldPersist(NOW, NOW + SNAPSHOT_MIN_WRITE_INTERVAL_MS), true);
  });

  test("a backwards clock doesn't wedge the throttle shut", () => {
    // Without this, a clock correction could block persistence indefinitely.
    assert.equal(shouldPersist(NOW, NOW - 60_000), true);
  });

  test("a normal export fits the size cap", () => {
    assert.equal(fitsSizeCap(makeSnapshot(EXPORT, { authenticated: true }, NOW)), true);
  });

  test("an oversized export is rejected rather than bloating globalState", () => {
    const huge = { tracks: [{ name: "x".repeat(SNAPSHOT_MAX_BYTES + 1) }] } as unknown as Export;
    assert.equal(fitsSizeCap(makeSnapshot(huge, { authenticated: true }, NOW)), false);
  });

  test("an unserialisable export is rejected, not thrown", () => {
    const cyclic: Record<string, unknown> = { tracks: [] };
    cyclic.self = cyclic;
    assert.equal(fitsSizeCap(makeSnapshot(cyclic as unknown as Export, null, NOW)), false);
  });

  test("readSnapshot does not mutate the store", () => {
    const store = memStore(makeSnapshot(EXPORT, { authenticated: true }, NOW));
    const before = store.written;
    readSnapshot(store, NOW);
    assert.equal(store.written, before);
  });
});
