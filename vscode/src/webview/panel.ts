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
import { buildHtml } from "./html.ts";

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

type WebviewMessage = SelectTrackMessage | OpenIssueMessage | SetFocusMessage;

// ---------------------------------------------------------------------------
// WorkPlanPanel
// ---------------------------------------------------------------------------

export class WorkPlanPanel {
  // Singleton reference — cleared on disposal.
  private static _instance: WorkPlanPanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private readonly _extensionUri: vscode.Uri;
  private _currentExport: Export | null = null;
  private _currentTrackName: string | null = null;
  /** Whether the graph is in focused mode (show only selected track's neighbourhood). */
  private _focused = true;

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
      WorkPlanPanel._instance = undefined;
    });

    // Handle messages from the webview.
    panel.webview.onDidReceiveMessage((raw: unknown) => {
      this._handleMessage(raw);
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

    const graphDef = toMermaid(exp, selectedTrackName, { focus: this._focused });
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
    }
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _buildEmptyHtml(message: string): string {
    const esc = (s: string) =>
      s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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
    default:
      return false;
  }
}
