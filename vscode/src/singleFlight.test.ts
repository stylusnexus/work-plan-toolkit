import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { SingleFlight } from "./singleFlight.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * A controllable gate: the task awaits `gate.promise`; calling `gate.open()`
 * unblocks it. Each `makeGate()` call returns a fresh one-shot gate.
 * This lets tests hold a task in-flight and release it deterministically
 * without timers or Date.now().
 */
function makeGate(): { promise: Promise<void>; open: () => void } {
  let open!: () => void;
  const promise = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { promise, open };
}

/**
 * Builds a task that:
 *  - increments `calls` each time it runs,
 *  - awaits the next gate in the `gates` queue (if any; otherwise resolves immediately).
 */
function makeGatedTask(
  state: { calls: number },
  gates: Array<{ promise: Promise<void>; open: () => void }>
): () => Promise<void> {
  return async () => {
    state.calls += 1;
    const gate = gates.shift();
    if (gate) {
      await gate.promise;
    }
  };
}

// ---------------------------------------------------------------------------
// Single call
// ---------------------------------------------------------------------------

describe("SingleFlight — single call", () => {
  test("run() once → task executes exactly once; promise resolves", async () => {
    const state = { calls: 0 };
    const sf = new SingleFlight(makeGatedTask(state, []));

    await sf.run();

    assert.equal(state.calls, 1, "task should run exactly once");
  });
});

// ---------------------------------------------------------------------------
// Coalescing
// ---------------------------------------------------------------------------

describe("SingleFlight — coalescing", () => {
  test("two mid-flight run() calls coalesce: task runs 2 total (1 leading + 1 trailing), all promises resolve", async () => {
    const state = { calls: 0 };
    const gate = makeGate();
    const sf = new SingleFlight(makeGatedTask(state, [gate]));

    // Start the leading run (will be held open by the gate).
    const p1 = sf.run();

    // Yield to let the task start and block on the gate.
    await Promise.resolve();

    // Two more calls arrive while the task is in-flight.
    const p2 = sf.run();
    const p3 = sf.run();

    // Release the gate → leading run finishes → trailing run fires.
    gate.open();

    // All three promises must resolve.
    await Promise.all([p1, p2, p3]);

    // Exactly 2 runs: 1 leading + 1 trailing covering both mid-flight calls.
    assert.equal(state.calls, 2, "task should run exactly twice (leading + 1 trailing)");
  });
});

// ---------------------------------------------------------------------------
// No trailing when nothing arrives during flight
// ---------------------------------------------------------------------------

describe("SingleFlight — no phantom trailing", () => {
  test("sequential run() calls (no overlap) → each is a fresh leading run, task runs N times total", async () => {
    const state = { calls: 0 };
    const sf = new SingleFlight(makeGatedTask(state, []));

    await sf.run();
    await sf.run();

    assert.equal(state.calls, 2, "two sequential runs should produce exactly 2 task executions");
  });
});

// ---------------------------------------------------------------------------
// Burst collapses
// ---------------------------------------------------------------------------

describe("SingleFlight — burst collapses", () => {
  test("5 mid-flight run() calls → exactly 1 trailing run (task total = 2), all promises resolve", async () => {
    const state = { calls: 0 };
    const gate = makeGate();
    const sf = new SingleFlight(makeGatedTask(state, [gate]));

    const p1 = sf.run();

    // Yield to let the task start.
    await Promise.resolve();

    const pending: Promise<void>[] = [];
    for (let i = 0; i < 5; i++) {
      pending.push(sf.run());
    }

    gate.open();

    await Promise.all([p1, ...pending]);

    assert.equal(state.calls, 2, "burst of 5 mid-flight calls should still produce only 2 task executions");
  });
});

// ---------------------------------------------------------------------------
// isRunning
// ---------------------------------------------------------------------------

describe("SingleFlight — isRunning", () => {
  test("false initially", () => {
    const sf = new SingleFlight(async () => {});
    assert.equal(sf.isRunning, false);
  });

  test("true while task is in-flight, false after settle", async () => {
    const gate = makeGate();
    let sawRunningTrue = false;

    const sf = new SingleFlight(async () => {
      await gate.promise;
    });

    const p = sf.run();

    // Yield to let the task start.
    await Promise.resolve();

    sawRunningTrue = sf.isRunning;
    gate.open();
    await p;

    assert.equal(sawRunningTrue, true, "isRunning should be true while task is in-flight");
    assert.equal(sf.isRunning, false, "isRunning should be false after settle");
  });

  test("true during a trailing run (entire sequence is considered in-flight)", async () => {
    const gate1 = makeGate();
    const gate2 = makeGate();
    const state = { calls: 0 };
    const sf = new SingleFlight(makeGatedTask(state, [gate1, gate2]));

    const p1 = sf.run();
    await Promise.resolve();

    // Queue a trailing run.
    const p2 = sf.run();

    // Release leading run → trailing run starts.
    gate1.open();
    // Yield so the trailing iteration can start.
    await Promise.resolve();
    await Promise.resolve();

    // Still running (trailing gate is still held).
    assert.equal(sf.isRunning, true, "isRunning should still be true during trailing run");

    gate2.open();
    await Promise.all([p1, p2]);

    assert.equal(sf.isRunning, false, "isRunning should be false after trailing run finishes");
  });
});

// ---------------------------------------------------------------------------
// Error propagation
// ---------------------------------------------------------------------------

describe("SingleFlight — error propagation", () => {
  test("task rejection propagates to the run() promise", async () => {
    const err = new Error("boom");
    const sf = new SingleFlight(async () => {
      throw err;
    });

    await assert.rejects(() => sf.run(), (thrown: unknown) => {
      assert.strictEqual(thrown, err, "should be the exact error thrown by the task");
      return true;
    });
  });

  test("isRunning is false after a task error (finally clears _inflight)", async () => {
    const sf = new SingleFlight(async () => {
      throw new Error("kaboom");
    });

    try {
      await sf.run();
    } catch {
      // expected
    }

    assert.equal(sf.isRunning, false, "isRunning must be false after a rejected run");
  });

  test("a subsequent run() after an error starts a fresh leading run", async () => {
    const state = { calls: 0 };
    let shouldFail = true;

    const sf = new SingleFlight(async () => {
      state.calls += 1;
      if (shouldFail) {
        throw new Error("first failure");
      }
    });

    // First run fails.
    try {
      await sf.run();
    } catch {
      // expected
    }

    // Second run should succeed.
    shouldFail = false;
    await sf.run();

    assert.equal(state.calls, 2, "should have executed the task twice total");
    assert.equal(sf.isRunning, false);
  });
});
