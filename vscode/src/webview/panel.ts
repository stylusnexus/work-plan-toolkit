/**
 * WorkPlanPanel — singleton webview panel manager.
 *
 * Responsibilities:
 *  - Create or reveal the webview panel.
 *  - Render the Mermaid graph + track detail on demand.
 *  - Handle inbound postMessages from the webview.
 *
 * This is the ONLY new file that imports from vscode.
 * It is thin glue over the pure functions in html.ts, graph.ts, detail.ts.
 */

import * as vscode from "vscode";
import type { Export } from "../model.ts";
import { toMermaid } from "./graph.ts";
import { renderDetail } from "./detail.ts";
import { buildHtml, esc } from "./html.ts";

// ---------------------------------------------------------------------------
// Injected move handler
// ---------------------------------------------------------------------------

/**
 * Performs a track-to-track move for the given issue. Injected by extension.ts
 * so the webview's drag-move goes through the SAME audited path as the
 * `workPlan.move` command — `executeWrite` + the public-repo confirm modal —
 * instead of spawning the CLI directly here. This keeps all spawn logic inside
 * the single audited runner in cli.ts and guarantees a public-repo move
 * surfaces the confirm dialog like every other write verb (#197).
 *
 * The implementation owns its own success/error/cancel notifications and the
 * post-write re-render; this module only collects the destination track.
 */
export type MoveHandler = (
  issue: number,
  fromTrack: string,
  toTrack: string,
) => Promise<void>;

// ---------------------------------------------------------------------------
// Mermaid bundle filename (UMD, self-contained, no chunks required)
// ---------------------------------------------------------------------------

/**
 * The filename of the Mermaid bundle copied into dist/ by esbuild.js.
 * UMD build: exposes global `mermaid` via a classic <script> tag.
 */
const MERMAID_FILE = "mermaid.min.js";

// ---------------------------------------------------------------------------
// Message types (webview → extension)
// ---------------------------------------------------------------------------

interface SelectTrackMessage {
  type: "selectTrack";
  name: string;
}

interface OpenIssueMessage {
  type: "openIssue";
  repo: string;
  number: number;
}

interface SetFocusMessage {
  type: "setFocus";
  focus: boolean;
}

interface MoveIssueMessage {
  type: "moveIssue";
  number: number;
}

interface FilterMilestoneMessage {
  type: "filterMilestone";
  milestone: string;
}

/** Open the current track's .md (#211). No payload — the host resolves the
 *  path from the current track, so the webview never carries it. */
interface OpenTrackFileMessage {
  type: "openTrackFile";
}

/** Open the current track's linked plan doc (#285). No payload — the host
 *  resolves the path from the current track's `plan` badge + repo local path. */
interface OpenPlanMessage {
  type: "openPlan";
}

/** Close a tracked issue on GitHub (#305). Carries the issue number; the host
 *  resolves the current track's repo + the issue's title and delegates to the
 *  workPlan.closeIssue command (which shows the mandatory modal). */
interface CloseIssueMessage {
  type: "closeIssue";
  number: number;
}

/** Mark or clear the work-plan:in-progress label on an issue (#271 B4). The
 *  host resolves the current track's repo and delegates to workPlan.toggleInProgress,
 *  which calls executeWrite so the public-repo confirm-token flow is reused. */
interface ToggleInProgressMessage {
  type: "toggleInProgress";
  number: number;
  clear: boolean;
}

type WebviewMessage =
  | SelectTrackMessage
  | OpenIssueMessage
  | SetFocusMessage
  | MoveIssueMessage
  | FilterMilestoneMessage
  | OpenTrackFileMessage
  | OpenPlanMessage
  | CloseIssueMessage
  | ToggleInProgressMessage;

// ---------------------------------------------------------------------------
// WorkPlanPanel
// ---------------------------------------------------------------------------

export class WorkPlanPanel {
  // Singleton reference — cleared on disposal.
  private static _instance: WorkPlanPanel | undefined;

  /**
   * Injected handler that performs a move via the audited write path.
   * Set once during activation (extension.ts). When unset, the drag-move is a
   * no-op rather than falling back to an ad-hoc spawn.
   */
  private static _moveHandler: MoveHandler | undefined;

  /** Registers the move handler used by the webview drag-move (#197). */
  static setMoveHandler(handler: MoveHandler): void {
    WorkPlanPanel._moveHandler = handler;
  }

  /**
   * Set by extension.ts — applies a milestone lens to the whole view when the
   * user clicks a milestone band header in the detail panel (#218). Injected so
   * the panel doesn't reach into the tree provider directly.
   */
  private static _filterHandler: ((milestone: string) => void) | undefined;

  /** Registers the milestone-filter handler used by the band-header click (#218). */
  static setFilterHandler(handler: (milestone: string) => void): void {
    WorkPlanPanel._filterHandler = handler;
  }

  private readonly _panel: vscode.WebviewPanel;
  private readonly _extensionUri: vscode.Uri;
  private _currentExport: Export | null = null;
  private _currentTrackName: string | null = null;
  /** Whether the graph is in focused mode (show only selected track's neighbourhood). */
  private _focused = true;
  /** Theme-change subscription — re-renders so the graph follows the editor (#207). */
  private _themeSub: vscode.Disposable | undefined;

  /** The track name most recently passed to render(), or null before first render. */
  get currentTrackName(): string | null {
    return this._currentTrackName;
  }

  // ---------------------------------------------------------------------------
  // Public static API
  // ---------------------------------------------------------------------------

  /**
   * Creates the webview panel if it doesn't exist, or reveals it.
   * Call render() afterwards to set the content.
   */
  static createOrShow(extensionUri: vscode.Uri): WorkPlanPanel {
    const column = vscode.window.activeTextEditor
      ? vscode.ViewColumn.Beside
      : vscode.ViewColumn.Active;

    if (WorkPlanPanel._instance) {
      WorkPlanPanel._instance._panel.reveal(column);
      return WorkPlanPanel._instance;
    }

    const panel = vscode.window.createWebviewPanel(
      "workPlan.graph",
      "Work Plan — Dependencies & flow",
      column,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(extensionUri, "dist")],
      },
    );

    const instance = new WorkPlanPanel(panel, extensionUri);
    WorkPlanPanel._instance = instance;
    return instance;
  }

  /** Returns the singleton if it exists, otherwise undefined. */
  static getCurrent(): WorkPlanPanel | undefined {
    return WorkPlanPanel._instance;
  }

  // ---------------------------------------------------------------------------
  // Constructor (private — callers use createOrShow)
  // ---------------------------------------------------------------------------

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    this._panel = panel;
    this._extensionUri = extensionUri;

    // Dispose the singleton reference when the panel is closed by the user.
    panel.onDidDispose(() => {
      this._themeSub?.dispose();
      WorkPlanPanel._instance = undefined;
    });

    // Handle messages from the webview.
    panel.webview.onDidReceiveMessage((raw: unknown) => {
      this._handleMessage(raw);
    });

    // Re-render when the editor's colour theme changes so the Mermaid graph
    // (which can't read CSS vars) follows light/dark instead of staying dark (#207).
    this._themeSub = vscode.window.onDidChangeActiveColorTheme(() => {
      if (this._currentExport && this._currentTrackName) {
        this.render(this._currentExport, this._currentTrackName);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // render
  // ---------------------------------------------------------------------------

  /**
   * Renders the full graph + detail for the given export and selected track.
   *
   * @param exp              - Full work-plan export (all tracks for the graph).
   * @param selectedTrackName - The track to highlight and show in the detail panel.
   */
  render(exp: Export, selectedTrackName: string): void {
    // Reset focus to true whenever a new track is selected.
    if (selectedTrackName !== this._currentTrackName) {
      this._focused = true;
    }

    this._currentExport = exp;
    this._currentTrackName = selectedTrackName;

    const track = exp.tracks.find(t => t.name === selectedTrackName);
    if (!track) {
      // Track not found — show an empty state rather than crashing.
      this._panel.webview.html = this._buildEmptyHtml(
        `Track "${selectedTrackName}" not found in export.`,
      );
      return;
    }

    const webview = this._panel.webview;
    const mermaidUri = webview
      .asWebviewUri(vscode.Uri.joinPath(this._extensionUri, "dist", MERMAID_FILE))
      .toString();

    // Full map is repo-scoped: only show tracks in the same repo as the
    // selected track.  Focus mode is already scoped to the neighbourhood.
    const graphExp = this._focused
      ? exp
      : { ...exp, tracks: exp.tracks.filter(t => t.repo === track.repo) };
    const isDark = isDarkTheme();
    const graphDef = toMermaid(graphExp, selectedTrackName, { focus: this._focused, dark: isDark });
    const detailHtml = renderDetail(track);

    const html = buildHtml({
      cspSource: webview.cspSource,
      nonce: nonce(),
      mermaidUri,
      graphDef,
      detailHtml,
      trackName: selectedTrackName,
      isModule: false, // UMD bundle → global mermaid
      focused: this._focused,
      isDark,
      hasTrackFile: !!track.path,
    });

    webview.html = html;
  }

  /**
   * Renders an empty-state message in the panel.
   * Used when a lens filters out every track while the panel is open.
   */
  renderEmpty(message: string): void {
    this._panel.webview.html = this._buildEmptyHtml(message);
  }

  // ---------------------------------------------------------------------------
  // Message handler
  // ---------------------------------------------------------------------------

  private _handleMessage(raw: unknown): void {
    if (!isWebviewMessage(raw)) {
      return;
    }

    switch (raw.type) {
      case "selectTrack": {
        if (this._currentExport) {
          this.render(this._currentExport, raw.name);
        }
        break;
      }
      case "setFocus": {
        this._focused = raw.focus;
        if (this._currentExport && this._currentTrackName) {
          // Re-render the current track. Safe to delegate: the track is
          // unchanged, so render()'s _focused reset guard does not fire.
          this.render(this._currentExport, this._currentTrackName);
        }
        break;
      }
      case "openIssue": {
        const url = `https://github.com/${raw.repo}/issues/${raw.number}`;
        vscode.env.openExternal(vscode.Uri.parse(url)).then(
          undefined,
          (err: unknown) => {
            vscode.window.showErrorMessage(
              `Work Plan: Failed to open issue — ${String(err)}`,
            );
          },
        );
        break;
      }
      case "moveIssue": {
        this._handleMoveIssue(raw.number);
        break;
      }
      case "filterMilestone": {
        WorkPlanPanel._filterHandler?.(raw.milestone);
        break;
      }
      case "openTrackFile": {
        // Resolve the current track and delegate to the command so the stat /
        // reveal / preview open logic lives in exactly one place (#211). The
        // command reads node.track.path, so pass a node-shaped { track } arg.
        const track = this._currentExport?.tracks.find(
          t => t.name === this._currentTrackName,
        );
        if (track) {
          void vscode.commands.executeCommand("workPlan.openTrackFile", { track });
        }
        break;
      }
      case "openPlan": {
        // Resolve the current track's linked plan doc to an absolute path and
        // delegate to the open command. The plan badge carries the repo-relative
        // `rel`; the repo's local checkout comes from the export's repos[] by the
        // track's folder key. Only resolved links have a file to open.
        const track = this._currentExport?.tracks.find(
          t => t.name === this._currentTrackName,
        );
        const plan = track?.plan;
        if (track && plan?.resolved) {
          const local = this._currentExport?.repos?.find(
            r => r.folder === track.folder,
          )?.local;
          if (local) {
            void vscode.commands.executeCommand(
              "workPlan.openPlanFile", { local, rel: plan.rel },
            );
          }
        }
        break;
      }
      case "closeIssue": {
        // Resolve the current track's repo + the issue's title, then delegate to
        // the command (which shows the mandatory GitHub-write modal) (#305).
        const track = this._currentExport?.tracks.find(
          t => t.name === this._currentTrackName,
        );
        const issue = track?.issues.find(i => i.number === raw.number);
        if (track?.repo && issue) {
          void vscode.commands.executeCommand("workPlan.closeIssue", {
            repo: track.repo,
            number: issue.number,
            title: issue.title,
          });
        }
        break;
      }
      case "toggleInProgress": {
        // Resolve the current track's repo, then delegate to the command (#271 B4).
        // The command calls executeWrite so the public-repo confirm-token flow is reused.
        const track = this._currentExport?.tracks.find(
          t => t.name === this._currentTrackName,
        );
        if (track?.repo) {
          void vscode.commands.executeCommand("workPlan.toggleInProgress", {
            repo: track.repo, number: raw.number, clear: raw.clear,
          });
        }
        break;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private async _handleMoveIssue(issueNum: number): Promise<void> {
    const exp = this._currentExport;
    const currentName = this._currentTrackName;
    if (!exp || !currentName) return;

    const currentTrack = exp.tracks.find(t => t.name === currentName);
    if (!currentTrack || !currentTrack.repo) return;

    // Find other active tracks in the same repo
    const others = exp.tracks.filter(
      t => t.name !== currentName && t.repo === currentTrack.repo,
    );
    if (others.length === 0) {
      vscode.window.showInformationMessage(
        "Work Plan: No other tracks in this repo to move to.",
      );
      return;
    }

    const picked = await vscode.window.showQuickPick(
      others.map(t => ({
        label: t.name,
        description: `${t.status} · ${t.rollup.open} open`,
      })),
      { placeHolder: `Move #${issueNum} to which track?` },
    );
    if (!picked) return;

    // Route the move through the injected handler so it goes through the same
    // executeWrite + public-repo confirm flow as every other write verb (#197).
    // No ad-hoc spawn here — all spawn logic lives in the audited cli.ts runner.
    const handler = WorkPlanPanel._moveHandler;
    if (!handler) {
      vscode.window.showErrorMessage(
        "Work Plan: move is unavailable — the extension is still starting up.",
      );
      return;
    }
    await handler(issueNum, currentName, picked.label);
  }

  private _buildEmptyHtml(message: string): string {
    return `<!DOCTYPE html>
<html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'"></head>
<body><p>${esc(message)}</p></body></html>`;
  }
}

// ---------------------------------------------------------------------------
// Exported helpers
// ---------------------------------------------------------------------------

/**
 * Generates a cryptographically random nonce string (A-Za-z0-9, 32 chars).
 * Uses crypto.getRandomValues (CSPRNG); the VS Code extension host runs Node ≥19,
 * which exposes globalThis.crypto. Used for CSP nonce generation; lives here
 * (glue code) rather than the pure html.ts.
 */
export function nonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  const buf = new Uint8Array(32);
  globalThis.crypto.getRandomValues(buf);
  return Array.from(buf, (b) => chars[b % chars.length]).join("");
}

/**
 * True when the editor is on a dark or high-contrast-dark theme. Drives the
 * Mermaid theme + graph classDef palette so the webview follows the editor (#207).
 * HighContrastLight is treated as light; HighContrast (dark) as dark.
 */
function isDarkTheme(): boolean {
  const kind = vscode.window.activeColorTheme.kind;
  return (
    kind === vscode.ColorThemeKind.Dark ||
    kind === vscode.ColorThemeKind.HighContrast
  );
}

// ---------------------------------------------------------------------------
// Type guard for incoming webview messages
// ---------------------------------------------------------------------------

function isWebviewMessage(raw: unknown): raw is WebviewMessage {
  if (typeof raw !== "object" || raw === null) {
    return false;
  }
  const msg = raw as Record<string, unknown>;
  if (typeof msg["type"] !== "string") {
    return false;
  }
  switch (msg["type"]) {
    case "selectTrack":
      return typeof msg["name"] === "string";
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
    default:
      return false;
  }
}
