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
import type { Export, Track, TrackKey } from "../model.ts";
import { parseTrackKey, resolveTrack, trackKey, trackRepoQualifier } from "../model.ts";
import { toMermaid } from "./graph.ts";
import { renderDetail } from "./detail.ts";
import { buildHtmlIfChanged, esc } from "./html.ts";
import { isWebviewMessage } from "./messages.ts";
import type { GraphMode } from "./messages.ts";
import { computeCriticalPath, criticalPickItems } from "./criticalPath.ts";
import { fitToCap, lensVisibleIssues, nextCritState, visibleTrackOrder } from "./criticalPathRender.ts";
import type { CriticalFilter, CritEvent } from "./criticalPathRender.ts";
import type { CriticalViewOptions } from "./html.ts";

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
  repoQualifier: string,
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
  private _currentTrackKey: TrackKey | null = null;
  /** Raw (unfiltered) export — critical-path ranks are computed from this, not the lens-filtered one. */
  private _rawExport: Export | null = null;
  /** Graph mode: selected track's neighbourhood, whole repo, or the critical path. */
  private _mode: GraphMode = "focus";
  /** Critical-path filters; reset/cleared by nextCritState. */
  private _critFilter: CriticalFilter = { trackKey: null, focusIssue: null, showClosed: false };
  /** Repo the critical-path filters were set against. */
  private _critRepo: string | null = null;
  /** True after the user explicitly cleared the track filter (skips auto-fit). */
  private _autoFitSuppressed = false;

  /** Run a view-state transition through the pure reducer and store the result. */
  private _apply(ev: CritEvent): string | null {
    const next = nextCritState(
      { mode: this._mode, filter: this._critFilter, repo: this._critRepo,
        autoFitSuppressed: this._autoFitSuppressed },
      ev,
    );
    this._mode = next.mode;
    this._critFilter = next.filter;
    this._critRepo = next.repo;
    this._autoFitSuppressed = next.autoFitSuppressed;
    return next.note;
  }
  /** Theme-change subscription — re-renders so the graph follows the editor (#207). */
  private _themeSub: vscode.Disposable | undefined;
  /** Content key of the graph document currently shown; null after an empty state (#423). */
  private _htmlKey: string | null = null;

  /** Canonical identity of the selected track, or null before a valid render. */
  get currentTrackKey(): TrackKey | null {
    return this._currentTrackKey;
  }

  /** Display-name compatibility accessor for existing extension callers. */
  get currentTrackName(): string | null {
    return this._currentTrack()?.name ?? null;
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
      if (this._currentExport && this._currentTrackKey) {
        this.render(this._currentExport, this._currentTrackKey, this._rawExport ?? undefined);
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
   * @param selection        - Canonical key, or a unique legacy display name.
   * @param rawExp           - Unfiltered export for critical-path ranks (defaults to `exp`).
   */
  render(exp: Export, selection: TrackKey | string, rawExp?: Export): void {
    const track = resolveTrack(exp.tracks, selection);
    this._currentExport = exp;
    this._rawExport = rawExp ?? exp;

    if (!track) {
      this._currentTrackKey = null;
      this._htmlKey = null;
      const parts = parseTrackKey(selection);
      const label = parts?.[1] ?? selection;
      // Track not found (or a legacy name is ambiguous) — show an empty state
      // rather than selecting an arbitrary same-named track from another repo.
      this._panel.webview.html = this._buildEmptyHtml(
        `Track "${label}" not found uniquely in export.`,
      );
      return;
    }

    const selectedTrackKey = trackKey(track);
    // A new track resets "full" to "focus" and clears filters from another repo.
    if (selectedTrackKey !== this._currentTrackKey) {
      this._apply({ type: "selectTrack", repo: track.repo });
    }
    this._currentTrackKey = selectedTrackKey;

    const webview = this._panel.webview;
    const mermaidUri = webview
      .asWebviewUri(vscode.Uri.joinPath(this._extensionUri, "dist", MERMAID_FILE))
      .toString();

    const isDark = isDarkTheme();
    let graphDef: string;
    let critical: CriticalViewOptions | undefined;
    if (this._mode === "critical") {
      const built = this._buildCritical(this._rawExport, exp, selectedTrackKey, track.repo, isDark);
      graphDef = built.graphDef;
      critical = built.critical;
    } else {
      // Full map is repo-scoped: only show tracks in the same repo as the
      // selected track.  Focus mode is already scoped to the neighbourhood.
      const focus = this._mode === "focus";
      const graphExp = focus
        ? exp
        : { ...exp, tracks: exp.tracks.filter(t => t.repo === track.repo) };
      graphDef = toMermaid(graphExp, selectedTrackKey, { focus, dark: isDark });
    }
    const showNextUpPreset = vscode.workspace
      .getConfiguration("workPlan")
      .get<boolean>("showNextUpPreset", true);
    const detailHtml = renderDetail(track, { showNextUpPreset });

    // Skip the write when nothing rendered changed (#423): replacing
    // webview.html reloads the page and re-runs Mermaid on every auto-refresh.
    const next = buildHtmlIfChanged(this._htmlKey, {
      cspSource: webview.cspSource,
      nonce: nonce(),
      mermaidUri,
      graphDef,
      detailHtml,
      trackName: track.name,
      isModule: false, // UMD bundle → global mermaid
      mode: this._mode,
      critical,
      isDark,
      hasTrackFile: !!track.path,
    });
    if (!next) return;

    this._htmlKey = next.key;
    webview.html = next.html;
  }

  /**
   * Critical-path graph + control state for the selected track's repo. Clears
   * stale filters (vanished track/issue) and surfaces why via autoFilterNote.
   */
  private _buildCritical(
    raw: Export,
    exp: Export,
    selected: TrackKey,
    repo: string | null,
    isDark: boolean,
  ): { graphDef: string; critical: CriticalViewOptions } {
    const base: CriticalViewOptions = {
      trackFilter: null,
      focusIssueLabel: null,
      showClosed: this._critFilter.showClosed,
      banner: null,
      legend: [],
      tooLargeMessage: null,
      autoFilterNote: null,
      emptyMessage: null,
      trackOptions: [],
    };
    if (repo === null) {
      return { graphDef: "", critical: { ...base, emptyMessage: "This track has no GitHub repo" } };
    }
    const model = computeCriticalPath(raw, repo);
    const nameOf = (k: TrackKey): string => exp.tracks.find(t => trackKey(t) === k)?.name
      ?? raw.tracks.find(t => trackKey(t) === k)?.name ?? k;
    // Ranks come from `raw`; the sidebar lens (`exp`) only hides tracks (spec §4).
    const visibleTracks = repoTrackKeys(exp, repo);
    const shownTracks = visibleTrackOrder(model, visibleTracks);
    const shownIssues = lensVisibleIssues(model, visibleTracks).map(i => i.id);
    const refreshNote = this._apply({
      type: "refresh", knownTracks: shownTracks, knownIssues: shownIssues,
      hiddenTracks: model.trackOrder.filter(k => !shownTracks.includes(k)),
      hiddenIssues: model.issues.map(i => i.id).filter(id => !shownIssues.includes(id)),
    });
    const fit = fitToCap(model, this._critFilter, selected, {
      dark: isDark, suppressAutoFit: this._autoFitSuppressed, visibleTracks,
      selectedName: nameOf(selected),
    });
    // Save the auto-applied track so a later explicit clear is distinguishable.
    if (fit.autoFiltered && fit.filter.trackKey) {
      this._apply({ type: "autoFit", trackKey: fit.filter.trackKey });
    }
    const focused = fit.filter.focusIssue
      ? model.issues.find(i => i.id === fit.filter.focusIssue)
      : undefined;
    return {
      graphDef: fit.render.mermaid,
      critical: {
        trackFilter: fit.filter.trackKey,
        focusIssueLabel: focused ? `#${focused.number} ${focused.title}` : null,
        showClosed: fit.filter.showClosed,
        banner: fit.render.banner,
        legend: fit.render.legend.map(l => ({ label: l.label, color: l.color })),
        tooLargeMessage: fit.render.tooLargeMessage,
        autoFilterNote: fit.autoFiltered ?? refreshNote,
        emptyMessage: fit.render.empty,
        trackOptions: shownTracks.map(k => ({ key: k, label: nameOf(k) })),
        nodeTitles: fit.render.nodeTitles,
      },
    };
  }

  /** Re-render the current track with the stored exports (state change from the webview). */
  private _rerender(): void {
    if (this._currentExport && this._currentTrackKey) {
      this.render(this._currentExport, this._currentTrackKey, this._rawExport ?? undefined);
    }
  }

  /** Host-side focus-issue picker; the issue id never comes from the webview. */
  private async _pickFocusIssue(): Promise<void> {
    const track = this._currentTrack();
    if (!this._rawExport || !track || track.repo === null) return;
    // Same lens rule as the graph: an issue only in lens-hidden tracks can't be focused.
    const model = computeCriticalPath(this._rawExport, track.repo);
    const visible = this._currentExport ? repoTrackKeys(this._currentExport, track.repo) : undefined;
    const items = criticalPickItems({ ...model, issues: lensVisibleIssues(model, visible) }, {
      showClosed: this._critFilter.showClosed,
    });
    if (items.length === 0) {
      vscode.window.showInformationMessage("Work Plan: No issues to focus on in this repo.");
      return;
    }
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: "Focus the critical path on which issue?",
      matchOnDescription: true,
    });
    if (!picked) return;
    this._apply({ type: "setFocusIssue", id: picked.id });
    this._rerender();
  }

  /**
   * Renders an empty-state message in the panel.
   * Used when a lens filters out every track while the panel is open.
   */
  renderEmpty(message: string): void {
    this._htmlKey = null;
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
          this.render(
            this._currentExport,
            "key" in raw ? raw.key : raw.name,
            this._rawExport ?? undefined,
          );
        }
        break;
      }
      case "setGraphMode": {
        this._apply({ type: "setMode", mode: raw.mode });
        this._rerender();
        break;
      }
      case "setCriticalTrackFilter": {
        this._apply({ type: "setTrackFilter", key: raw.key });
        this._rerender();
        break;
      }
      case "setShowClosed": {
        this._apply({ type: "setShowClosed", show: raw.show });
        this._rerender();
        break;
      }
      case "clearFocusIssue": {
        this._apply({ type: "setFocusIssue", id: null });
        this._rerender();
        break;
      }
      case "pickFocusIssue": {
        this._pickFocusIssue().catch((err: unknown) => {
          vscode.window.showErrorMessage(
            `Work Plan: Failed to pick an issue to focus on — ${String(err)}`,
          );
        });
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
        const track = this._currentTrack();
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
        const track = this._currentTrack();
        const plan = track?.plan;
        if (track && plan?.resolved) {
          const local = this._currentExport?.repos?.find(r =>
            track.folder !== null
              ? r.folder === track.folder
              : r.repo === track.repo,
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
        const track = this._currentTrack();
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
        const track = this._currentTrack();
        if (track?.repo) {
          void vscode.commands.executeCommand("workPlan.toggleInProgress", {
            repo: track.repo, number: raw.number, clear: raw.clear,
          });
        }
        break;
      }
      case "setNextUp": {
        // Resolve the current track and delegate to workPlan.setNext.
        const track = this._currentTrack();
        if (track) {
          void vscode.commands.executeCommand("workPlan.setNext", {
            name: track.name,
            repoQualifier: trackRepoQualifier(track),
            track,
          });
        }
        break;
      }
      case "exportGraph": {
        void this._handleExportGraph(raw.format, raw.data);
        break;
      }
    }
  }

  /**
   * Write the exported dependency graph to disk via a Save dialog (#216). The
   * webview did the rendering (SVG serialize / PNG rasterize); the host only
   * picks a destination and writes bytes — SVG as utf-8 text, PNG decoded from
   * its base64 data-URL payload.
   */
  private async _handleExportGraph(format: "svg" | "png", data: string): Promise<void> {
    const trackSlug = (this.currentTrackName ?? "dependency-graph")
      .replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "") || "dependency-graph";
    const defaultUri = vscode.Uri.file(`${trackSlug}.${format}`);
    const filters: Record<string, string[]> = format === "svg"
      ? { "SVG image": ["svg"] }
      : { "PNG image": ["png"] };
    const target = await vscode.window.showSaveDialog({ defaultUri, filters });
    if (!target) {
      return; // user cancelled
    }
    try {
      let bytes: Uint8Array;
      if (format === "png") {
        // data is a `data:image/png;base64,…` URL — strip the prefix and decode.
        const comma = data.indexOf(",");
        const b64 = comma >= 0 ? data.slice(comma + 1) : data;
        bytes = Uint8Array.from(Buffer.from(b64, "base64"));
      } else {
        bytes = new TextEncoder().encode(data);
      }
      await vscode.workspace.fs.writeFile(target, bytes);
      vscode.window.showInformationMessage(
        `Work Plan: graph exported to ${target.fsPath}`,
      );
    } catch (err: unknown) {
      vscode.window.showErrorMessage(
        `Work Plan: graph export failed — ${String(err)}`,
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _currentTrack(): Track | undefined {
    if (!this._currentExport || !this._currentTrackKey) return undefined;
    return resolveTrack(this._currentExport.tracks, this._currentTrackKey);
  }

  private async _handleMoveIssue(issueNum: number): Promise<void> {
    const exp = this._currentExport;
    const currentTrack = this._currentTrack();
    if (!exp || !currentTrack) return;
    if (!currentTrack || !currentTrack.repo) return;

    // Find other active tracks in the same repo
    const others = exp.tracks.filter(
      t => trackKey(t) !== this._currentTrackKey && t.repo === currentTrack.repo,
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
    await handler(
      issueNum,
      currentTrack.name,
      picked.label,
      trackRepoQualifier(currentTrack),
    );
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

/** Keys of the tracks in `repo` that the (possibly lens-filtered) export still shows. */
function repoTrackKeys(exp: Export, repo: string): Set<TrackKey> {
  return new Set(exp.tracks.filter(t => t.repo === repo).map(t => trackKey(t)));
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
