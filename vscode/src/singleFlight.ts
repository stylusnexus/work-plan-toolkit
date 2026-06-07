// ---------------------------------------------------------------------------
// SingleFlight — leading + trailing coalescing helper (no vscode import)
// ---------------------------------------------------------------------------

/**
 * Runs an async task with single-flight + trailing semantics:
 *
 * - While a run is in flight, concurrent `run()` calls coalesce onto the same
 *   in-flight promise (the task is NOT started again immediately).
 * - If any `run()` arrives during flight, exactly ONE more run executes after
 *   the current one completes (the "trailing" run), so a request made
 *   mid-flight is never served only stale data.
 * - Every caller's returned promise resolves when the whole leading+trailing
 *   sequence settles.
 *
 * Error behaviour: if the task throws, `_inflight` is cleared (via `finally`)
 * and the rejection propagates to all awaiting callers. A trailing run is NOT
 * attempted after an error — the sequence stops and callers receive the error.
 */
export class SingleFlight {
  private readonly _task: () => Promise<void>;
  private _inflight: Promise<void> | null = null;
  private _pending = false;

  constructor(task: () => Promise<void>) {
    this._task = task;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /** True while a run (including any trailing run) is executing. */
  get isRunning(): boolean {
    return this._inflight !== null;
  }

  /**
   * Trigger a run, or coalesce onto the already-in-flight sequence.
   *
   * Returns a promise that resolves once the leading run (and any trailing run
   * triggered by mid-flight arrivals) has completed.
   */
  run(): Promise<void> {
    if (this._inflight !== null) {
      // A run is already in progress — mark that a trailing run is needed and
      // return the same promise so this caller waits for the full sequence.
      this._pending = true;
      return this._inflight;
    }

    this._inflight = this._loop();
    return this._inflight;
  }

  // ---------------------------------------------------------------------------
  // Internal
  // ---------------------------------------------------------------------------

  /**
   * Core loop: runs the task, then re-runs it if any call arrived mid-flight.
   * Clears `_inflight` in a `finally` block so errors still release the slot.
   */
  private async _loop(): Promise<void> {
    try {
      do {
        // Reset _pending BEFORE awaiting the task so that any run() call that
        // arrives *during* the task sets _pending=true, triggering exactly one
        // trailing iteration. Calls during the trailing iteration do the same,
        // naturally collapsing bursts into a single additional run.
        this._pending = false;
        await this._task();
      } while (this._pending);
    } finally {
      this._inflight = null;
    }
  }
}
