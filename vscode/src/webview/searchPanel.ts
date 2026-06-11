/**
 * SearchPanel — a dedicated, reusable webview panel for issue-search results (#272).
 *
 * Separate from the singleton WorkPlanPanel (the dependency-graph detail view) so
 * a search never clobbers an open track. One instance is reused across searches:
 * a new search updates its contents and re-reveals it rather than spawning tabs.
 *
 * The panel is display-only. It relays user intent (open issue, reveal track,
 * refresh) back through injected handlers; it never touches the tree provider
 * directly.
 */

import * as vscode from "vscode";
import type { SearchHit } from "./search.ts";
import { buildSearchHtml } from "./searchHtml.ts";
import { nonce } from "./panel.ts";

export interface SearchResults {
  query: string;
  hits: SearchHit[];
  generatedAt: string;
}

export interface SearchHandlers {
  openIssue: (repo: string, number: number) => void;
  revealTrack: (repo: string, track: string) => void;
  refreshAndSearch: () => void;
}

type InboundMessage =
  | { type: "openIssue"; repo: string; number: number }
  | { type: "revealTrack"; repo: string; track: string }
  | { type: "refreshAndSearch" };

export class SearchPanel {
  private static _instance: SearchPanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private _handlers: SearchHandlers;

  private constructor(panel: vscode.WebviewPanel, handlers: SearchHandlers) {
    this._panel = panel;
    this._handlers = handlers;
    panel.onDidDispose(() => {
      SearchPanel._instance = undefined;
    });
    panel.webview.onDidReceiveMessage((raw: unknown) => this._handle(raw));
  }

  /**
   * Renders results into the (reused or freshly created) search panel and brings
   * it forward. Always passes the latest handlers so the panel stays bound to the
   * current activation's closures.
   */
  static showResults(
    results: SearchResults,
    handlers: SearchHandlers,
  ): void {
    const column = vscode.ViewColumn.Beside;
    if (!SearchPanel._instance) {
      const panel = vscode.window.createWebviewPanel(
        "workPlan.search",
        "Issue Search",
        column,
        { enableScripts: true, retainContextWhenHidden: true },
      );
      SearchPanel._instance = new SearchPanel(panel, handlers);
    } else {
      SearchPanel._instance._handlers = handlers;
    }

    const inst = SearchPanel._instance;
    inst._panel.title = results.query.trim() === ""
      ? "Issue Search"
      : `Issue Search: ${results.query}`;
    inst._panel.webview.html = buildSearchHtml({
      query: results.query,
      hits: results.hits,
      generatedAt: results.generatedAt,
      cspSource: inst._panel.webview.cspSource,
      nonce: nonce(),
    });
    inst._panel.reveal(column);
    // Move keyboard focus into the results after the DOM swaps in.
    void inst._panel.webview.postMessage({ type: "focusResults" });
  }

  private _handle(raw: unknown): void {
    if (typeof raw !== "object" || raw === null) return;
    const msg = raw as InboundMessage;
    switch (msg.type) {
      case "openIssue":
        this._handlers.openIssue(msg.repo, msg.number);
        break;
      case "revealTrack":
        this._handlers.revealTrack(msg.repo, msg.track);
        break;
      case "refreshAndSearch":
        this._handlers.refreshAndSearch();
        break;
    }
  }
}
