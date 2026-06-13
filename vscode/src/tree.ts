import * as vscode from "vscode";
import type { Export } from "./model.ts";
import { buildTree, shouldExpandRepos, sortTracks, repoDescription, visibilityTierBadge } from "./treeModel.ts";
import type { RepoNode, TrackNode, UntrackedGroupNode, UntrackedIssueNode, EmptyRepoNode, StatusCategory, TrackSort } from "./treeModel.ts";
import { applyLens } from "./webview/lenses.ts";
import type { Lens } from "./webview/lenses.ts";
import { SingleFlight } from "./singleFlight.ts";

// Re-export the node types so extension.ts only needs to import from tree.ts.
export type { RepoNode, TrackNode, UntrackedGroupNode, UntrackedIssueNode, EmptyRepoNode };

/** Every node kind the Tracks tree can render. */
type TreeNode = RepoNode | TrackNode | UntrackedGroupNode | UntrackedIssueNode | EmptyRepoNode;
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
      // Distinct SHAPE, not just a red tint — blocked vs active must be
      // tellable apart without colour (#208).
      return { icon: "circle-slash", color: "charts.red" };
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
  implements vscode.TreeDataProvider<TreeNode>
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

  getChildren(element?: TreeNode): TreeNode[] {
    if (!element) {
      // Root: return the cached repo nodes (empty [] before first refresh).
      return this.roots;
    }
    if (element.kind === "repo") {
      // A configured-but-empty repo (#288): show a single dimmed affordance that
      // starts a New Track prefilled for this repo, instead of an empty branch.
      if (element.tracks.length === 0) {
        return [{ kind: "emptyRepo", repo: element.repo, folder: element.folder }];
      }
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

  /**
   * Parent lookup — required for `TreeView.reveal()` (used by Reveal-in-tree
   * from the search results panel, #272). Only the track→repo and
   * untracked→repo edges are needed in practice; repos are roots.
   */
  getParent(
    element: TreeNode,
  ): RepoNode | UntrackedGroupNode | undefined {
    if (element.kind === "repo") return undefined;
    if (element.kind === "emptyRepo") {
      return this.roots.find(r => r.repo === element.repo);
    }
    if (element.kind === "track") {
      return this.roots.find(r => r.tracks.includes(element));
    }
    if (element.kind === "untrackedGroup") {
      return this.roots.find(r => r.repo === element.repo);
    }
    // untrackedIssue → its group
    const repoNode = this.roots.find(r => r.repo === element.repo);
    if (repoNode && repoNode.untracked.length > 0) {
      return { kind: "untrackedGroup", repo: repoNode.repo, issues: repoNode.untracked };
    }
    return undefined;
  }

  /**
   * Finds the live TrackNode for a (name, repo) pair among the current roots, so
   * callers can hand the exact instance to `TreeView.reveal()`. Returns null when
   * the track isn't visible (e.g. filtered out by the active lens).
   */
  findTrackNode(name: string, repo: string | null): TrackNode | null {
    for (const r of this.roots) {
      for (const t of r.tracks) {
        if (t.name === name && (repo === null || t.repo === repo)) {
          return t;
        }
      }
    }
    return null;
  }

  getTreeItem(node: TreeNode): vscode.TreeItem {
    if (node.kind === "repo") {
      return this._repoTreeItem(node);
    }
    if (node.kind === "emptyRepo") {
      return this._emptyRepoTreeItem(node);
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

    // Visibility × tier badge (#259): a codicon cluster prefixing the description,
    // loud only for the public+shared "exposed" state.
    const badge = visibilityTierBadge(node.track);
    item.description = node.hint
      ? `${badge.descriptionPrefix}  ${node.open} open  ${node.hint}`
      : `${badge.descriptionPrefix}  ${node.open} open`;

    const { icon, color } = categoryIcon(node.category);
    item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));

    item.contextValue = "workPlanTrack";
    // MarkdownString (supportThemeIcons) so the $(icon) glyphs render in the tooltip.
    const tip = new vscode.MarkdownString(undefined, true);
    tip.appendMarkdown(`**${node.name}** — ${node.status} · ${node.open} open\n\n`);
    tip.appendMarkdown(badge.tooltipMarkdown);
    item.tooltip = tip;

    item.command = {
      command: "workPlan.openTrack",
      title: "Open Track",
      arguments: [node.track],
    };

    return item;
  }

  private _emptyRepoTreeItem(node: EmptyRepoNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      "No tracks yet — add one",
      vscode.TreeItemCollapsibleState.None,
    );
    // Dimmed/italic via the resource-label theme; ThemeIcon("add") signals the
    // affordance. Clicking starts a New Track prefilled for THIS repo.
    item.description = "";
    item.iconPath = new vscode.ThemeIcon("add");
    item.contextValue = "workPlanEmptyRepo";
    item.tooltip = node.repo === "(no repo)"
      ? "Add a track"
      : `Add a track to ${node.repo}`;
    item.command = {
      command: "workPlan.newTrack",
      title: "New Track",
      // Hand newTrack a RepoNode-shaped arg so it can prefill the github slug.
      arguments: [this._repoNodeFor(node)],
    };
    return item;
  }

  /** Reconstructs a minimal RepoNode from an empty-state child so the click
   *  hands newTrack the same prefill arg as a context-menu invocation. */
  private _repoNodeFor(node: EmptyRepoNode): RepoNode {
    return (
      this.roots.find(r => r.repo === node.repo) ?? {
        kind: "repo",
        repo: node.repo,
        isPublic: false,
        tier: "private",
        tracks: [],
        untracked: [],
        folder: node.folder,
        hasLocal: false,
      }
    );
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
