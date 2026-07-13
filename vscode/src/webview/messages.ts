/**
 * Webview message types and type guard — pure module, NO vscode import.
 *
 * Extracted from panel.ts so the guard can be unit-tested independently of the
 * vscode extension host. panel.ts re-exports nothing from here — it imports only
 * what it needs (the union type + the guard function).
 *
 * WHY this guard exists: every inbound postMessage from the webview is `unknown`;
 * the guard validates shape + payload before the switch in _handleMessage touches
 * any property. Missing a case here means the handler branch is silently dead —
 * that was the root cause of #305 (closeIssue) and #285 (openPlan) shipping broken.
 */

import type { TrackKey } from "../model.ts";
import { isTrackKey } from "../model.ts";

// ---------------------------------------------------------------------------
// Message interfaces (webview → extension)
// ---------------------------------------------------------------------------

export type SelectTrackMessage =
  | { type: "selectTrack"; key: TrackKey }
  | { type: "selectTrack"; name: string };

export interface OpenIssueMessage {
  type: "openIssue";
  repo: string;
  number: number;
}

export interface SetFocusMessage {
  type: "setFocus";
  focus: boolean;
}

export interface MoveIssueMessage {
  type: "moveIssue";
  number: number;
}

export interface FilterMilestoneMessage {
  type: "filterMilestone";
  milestone: string;
}

/** Open the current track's .md (#211). No payload — the host resolves the
 *  path from the current track, so the webview never carries it. */
export interface OpenTrackFileMessage {
  type: "openTrackFile";
}

/** Open the current track's linked plan doc (#285). No payload — the host
 *  resolves the path from the current track's `plan` badge + repo local path. */
export interface OpenPlanMessage {
  type: "openPlan";
}

/** Close a tracked issue on GitHub (#305). Carries the issue number; the host
 *  resolves the current track's repo + the issue's title and delegates to the
 *  workPlan.closeIssue command (which shows the mandatory modal). */
export interface CloseIssueMessage {
  type: "closeIssue";
  number: number;
}

/** Mark or clear the work-plan:in-progress label on an issue (#271 B4). The
 *  host resolves the current track's repo and delegates to workPlan.toggleInProgress,
 *  which calls executeWrite so the public-repo confirm-token flow is reused. */
export interface ToggleInProgressMessage {
  type: "toggleInProgress";
  number: number;
  clear: boolean;
}

/** Trigger the Set Next-Up flow for the current track from the detail panel.
 *  No payload — the host resolves the current track by name and delegates to
 *  workPlan.setNext, which walks the user through the iterative issue-pick. */
export interface SetNextUpMessage {
  type: "setNextUp";
}

/** Export the rendered dependency graph (#216). The webview serializes the live
 *  Mermaid SVG (format "svg") or rasterizes it to a PNG data URL (format "png")
 *  and the host writes it via a Save dialog. `data` is the SVG XML string, or a
 *  `data:image/png;base64,…` URL for PNG. */
export interface ExportGraphMessage {
  type: "exportGraph";
  format: "svg" | "png";
  data: string;
}

export type WebviewMessage =
  | SelectTrackMessage
  | OpenIssueMessage
  | SetFocusMessage
  | MoveIssueMessage
  | FilterMilestoneMessage
  | OpenTrackFileMessage
  | OpenPlanMessage
  | CloseIssueMessage
  | ToggleInProgressMessage
  | SetNextUpMessage
  | ExportGraphMessage;

// ---------------------------------------------------------------------------
// Type guard for incoming webview messages
// ---------------------------------------------------------------------------

/**
 * Validates that `raw` is a well-formed WebviewMessage before the handler
 * switch in panel.ts touches any property.
 *
 * IMPORTANT: every case handled by _handleMessage's switch MUST have a
 * corresponding case here — omitting one silently kills that button/action
 * in shipped builds (that was the #305 / #285 regression).
 */
export function isWebviewMessage(raw: unknown): raw is WebviewMessage {
  if (typeof raw !== "object" || raw === null) {
    return false;
  }
  const msg = raw as Record<string, unknown>;
  if (typeof msg["type"] !== "string") {
    return false;
  }
  switch (msg["type"]) {
    case "selectTrack":
      return (
        isTrackKey(msg["key"])
        && msg["name"] === undefined
      ) || (
        typeof msg["name"] === "string"
        && (msg["name"] as string).length > 0
        && msg["key"] === undefined
      );
    case "openIssue":
      return typeof msg["repo"] === "string"
        && /^[\w.-]+\/[\w.-]+$/.test(msg["repo"] as string)
        && typeof msg["number"] === "number"
        && Number.isInteger(msg["number"])
        && (msg["number"] as number) > 0;
    case "setFocus":
      return typeof msg["focus"] === "boolean";
    case "moveIssue":
      return typeof msg["number"] === "number"
        && Number.isInteger(msg["number"])
        && (msg["number"] as number) > 0;
    case "filterMilestone":
      return typeof msg["milestone"] === "string" && (msg["milestone"] as string).length > 0;
    case "openTrackFile":
      return true; // no payload to validate
    case "openPlan":
      return true; // no payload to validate
    case "closeIssue":
      return typeof msg["number"] === "number"
        && Number.isInteger(msg["number"])
        && (msg["number"] as number) > 0;
    case "toggleInProgress":
      return typeof msg["number"] === "number"
        && Number.isInteger(msg["number"])
        && (msg["number"] as number) > 0
        && typeof msg["clear"] === "boolean";
    case "setNextUp":
      return true; // no payload to validate
    case "exportGraph":
      return (msg["format"] === "svg" || msg["format"] === "png")
        && typeof msg["data"] === "string" && (msg["data"] as string).length > 0;
    default:
      return false;
  }
}
