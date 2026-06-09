import * as vscode from "vscode";
import type { Export } from "./model.ts";
import { buildTree, shouldExpandRepos, sortTracks, repoDescription } from "./treeModel.ts";
import type { RepoNode, TrackNode, UntrackedGroupNode, UntrackedIssueNode, StatusCategory, TrackSort } from "./treeModel.ts";
import { applyLens } from "./webview/lenses.ts";
import type { Lens } from "./webview/lenses.ts";
import { SingleFlight } from "./singleFlight.ts";

// Re-export the node types so extension.ts only needs to import from tree.ts.
export type { RepoNode, TrackNode, UntrackedGroupNode, UntrackedIssueNode };
// Re-export Lens so extension.ts only needs to import from tree.ts.
export type { Lens };
// Re-export TrackSort so extension.ts only needs to import from tree.ts.
export type { TrackSort };

// ---------------------------------------------------------------------------
// Icon helper (pure mapping — kept in tree.ts because it references vscode)
// ---------------------------------------------------------------------------

interface IconSpec {
  icon: string;
  color: string;
}

function categoryIcon(category: StatusCategory): IconSpec {
  switch (category) {
    case "blocked":
      return { icon: "circle-filled", color: "charts.red" };
    case "active":
      return { icon: "circle-filled", color: "charts.blue" };
    case "shipped":
      return { icon: "pass-filled", color: "charts.gray" };
    case "parked":
      return { icon: "circle-outline", color: "charts.gray" };
  }
}

// ---------------------------------------------------------------------------
// WorkPlanTreeProvider
// ---------------------------------------------------------------------------

export class WorkPlanTreeProvider
  implements vscode.TreeDataProvider<RepoNode | TrackNode | UntrackedGroupNode | UntrackedIssueNode>
{
  private _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private cache: Export | null = null;
  private _filteredCache: Export | null = null;
  private roots: RepoNode[] = [];
  private _activeLens: Lens = { kind: "all" };
  private _activeSort: TrackSort = "default";
  private readonly _refreshFlight: SingleFlight;

  constructor(private readonly load: () => Promise<Export>) {
    this._refreshFlight = new SingleFlight(() => this._doRefresh());
  }

  /**
   * Returns the lens-filtered export (what the tree and panel currently show).
   * Returns null before first refresh. Cached — computed once per refresh/setLens.
   */
  get currentExport(): Export | null {
    return this._filteredCache;
  }

  /** Returns the raw unfiltered export. Use to populate lens choices. */
  get rawExport(): Export | null {
    return this.cache;
  }

  /** Returns the currently active lens. */
  get activeLens(): Lens {
    return this._activeLens;
  }

  /** Returns the currently active sort mode. */
  get activeSort(): TrackSort {
    return this._activeSort;
  }

  /**
   * Applies sort to each repo's tracks. Returns a new RepoNode[] with each
   * repo's tracks replaced by the sorted result. Does NOT mutate the input
   * nor the RepoNodes produced by buildTree.
   */
  private _applySortToRepos(repos: RepoNode[]): RepoNode[] {
    return repos.map(repo => ({
      ...repo,
      tracks: sortTracks(repo.tracks, this._activeSort),
    }));
  }

  /**
   * Changes the sort mode and re-renders the tree from the cached filtered
   * export. Does not re-fetch from the CLI. Sort is applied to `roots` (tree)
   * only — `currentExport`/`rawExport` are unaffected.
   */
  setSort(mode: TrackSort): void {
    this._activeSort = mode;
    const filtered = this._filteredCache ? buildTree(this._filteredCache) : [];
    this.roots = this._applySortToRepos(filtered);
    this._onDidChangeTreeData.fire();
  }

  /**
   * Applies a new lens and re-renders the tree.
   * Does not re-fetch from the CLI — works off the cached export.
   */
  setLens(lens: Lens): void {
    this._activeLens = lens;
    this._filteredCache = this.cache ? applyLens(this.cache, lens) : null;
    this.roots = this._applySortToRepos(
      this._filteredCache ? buildTree(this._filteredCache) : []
    );
    this._onDidChangeTreeData.fire();
  }

  /**
   * Fetches fresh data from the CLI and fires a tree refresh.
   * Concurrent calls coalesce onto the in-flight run (with a trailing run so
   * the last caller always sees fresh data). Errors propagate to the caller
   * (extension.ts wraps with showErrorMessage).
   */
  async refresh(): Promise<void> {
    return this._refreshFlight.run();
  }

  /**
   * The actual fetch+render work. Wrapped in a VS Code progress indicator so
   * the Tracks view shows a native progress bar while the CLI is running.
   * Errors propagate out of withProgress → out of this method → through
   * SingleFlight → to the refresh() caller.
   */
  private async _doRefresh(): Promise<void> {
    await vscode.window.withProgress(
      { location: { viewId: "workPlan.tree" } },
      async () => {
        this.cache = await this.load();
        this._filteredCache = applyLens(this.cache, this._activeLens);
        this.roots = this._applySortToRepos(buildTree(this._filteredCache));
        this._onDidChangeTreeData.fire();
        // Drive viewsWelcome off the RAW (unfiltered) data so an active lens
        // that hides everything doesn't incorrectly show "No repos yet."
        void vscode.commands.executeCommand(
          "setContext",
          "workPlanHasRepos",
          this.cache.tracks.length > 0,
        );
      },
    );
  }

  getChildren(
    element?: RepoNode | TrackNode | UntrackedGroupNode | UntrackedIssueNode
  ): (RepoNode | TrackNode | UntrackedGroupNode | UntrackedIssueNode)[] {
    if (!element) {
      // Root: return the cached repo nodes (empty [] before first refresh).
      return this.roots;
    }
    if (element.kind === "repo") {
      const untrackedGroup: UntrackedGroupNode[] =
        element.untracked.length > 0
          ? [{ kind: "untrackedGroup", repo: element.repo, issues: element.untracked }]
          : [];
      return [...element.tracks, ...untrackedGroup];
    }
    if (element.kind === "untrackedGroup") {
      return element.issues.map(
        (issue): UntrackedIssueNode => ({ kind: "untrackedIssue", repo: element.repo, issue })
      );
    }
    // TrackNode or UntrackedIssueNode — leaves; no children.
    return [];
  }

  getTreeItem(node: RepoNode | TrackNode | UntrackedGroupNode | UntrackedIssueNode): vscode.TreeItem {
    if (node.kind === "repo") {
      return this._repoTreeItem(node);
    }
    if (node.kind === "untrackedGroup") {
      return this._untrackedGroupTreeItem(node);
    }
    if (node.kind === "untrackedIssue") {
      return this._untrackedIssueTreeItem(node);
    }
    return this._trackTreeItem(node);
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _repoTreeItem(node: RepoNode): vscode.TreeItem {
    const expand = shouldExpandRepos(
      this.roots.length,
      vscode.workspace
        .getConfiguration("workPlan")
        .get<boolean>("expandReposByDefault", false)
    );
    const item = new vscode.TreeItem(
      node.repo,
      expand
        ? vscode.TreeItemCollapsibleState.Expanded
        : vscode.TreeItemCollapsibleState.Collapsed
    );
    item.description = repoDescription(node);
    item.contextValue = "workPlanRepo";
    item.iconPath = new vscode.ThemeIcon("repo");
    return item;
  }

  private _trackTreeItem(node: TrackNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      node.name,
      vscode.TreeItemCollapsibleState.None
    );

    const shared = node.track.tier === "shared";
    const tierPrefix = shared ? "shared  " : "";
    item.description = node.hint
      ? `${tierPrefix}${node.open} open  ${node.hint}`
      : `${tierPrefix}${node.open} open`;

    const { icon, color } = categoryIcon(node.category);
    item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));

    item.contextValue = "workPlanTrack";
    item.tooltip = `${node.name} — ${node.status} · ${node.open} open · ${
      shared ? "Shared — travels via git push/pull" : "Private — local only"
    }`;

    item.command = {
      command: "workPlan.openTrack",
      title: "Open Track",
      arguments: [node.track],
    };

    return item;
  }

  private _untrackedGroupTreeItem(node: UntrackedGroupNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      "Untracked",
      vscode.TreeItemCollapsibleState.Collapsed
    );
    item.description = `${node.issues.length}`;
    item.iconPath = new vscode.ThemeIcon("circle-slash");
    item.contextValue = "workPlanUntrackedGroup";
    item.tooltip = `${node.issues.length} open issue(s) in no track`;
    return item;
  }

  private _untrackedIssueTreeItem(node: UntrackedIssueNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      `#${node.issue.number}  ${node.issue.title}`,
      vscode.TreeItemCollapsibleState.None
    );
    item.iconPath = new vscode.ThemeIcon("issue-opened");
    item.contextValue = "workPlanUntrackedIssue";
    item.tooltip = node.issue.title;
    item.command = {
      command: "workPlan.openIssue",
      title: "Open Issue",
      arguments: [{ repo: node.repo, number: node.issue.number }],
    };
    return item;
  }
}
