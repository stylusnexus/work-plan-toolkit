import * as vscode from "vscode";
import type { Export } from "./model.ts";
import { buildTree } from "./treeModel.ts";
import type { RepoNode, TrackNode, StatusCategory } from "./treeModel.ts";

// Re-export the node types so extension.ts only needs to import from tree.ts.
export type { RepoNode, TrackNode };

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
  implements vscode.TreeDataProvider<RepoNode | TrackNode>
{
  private _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private cache: Export | null = null;
  private roots: RepoNode[] = [];

  constructor(private readonly load: () => Promise<Export>) {}

  /** Returns the last successfully loaded export, or null before first refresh. */
  get currentExport(): Export | null {
    return this.cache;
  }

  /**
   * Fetches fresh data from the CLI and fires a tree refresh.
   * Errors propagate to the caller (extension.ts / Task 8 wraps with showErrorMessage).
   */
  async refresh(): Promise<void> {
    this.cache = await this.load();
    this.roots = buildTree(this.cache);
    this._onDidChangeTreeData.fire();
  }

  getChildren(element?: RepoNode | TrackNode): (RepoNode | TrackNode)[] {
    if (!element) {
      // Root: return the cached repo nodes (empty [] before first refresh).
      return this.roots;
    }
    if (element.kind === "repo") {
      return element.tracks;
    }
    // TrackNode — leaf; no children.
    return [];
  }

  getTreeItem(node: RepoNode | TrackNode): vscode.TreeItem {
    if (node.kind === "repo") {
      return this._repoTreeItem(node);
    }
    return this._trackTreeItem(node);
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _repoTreeItem(node: RepoNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      node.repo,
      vscode.TreeItemCollapsibleState.Expanded
    );
    item.description = node.isPublic
      ? `${node.tier} ⚠ public`
      : node.tier;
    item.contextValue = "workPlanRepo";
    item.iconPath = new vscode.ThemeIcon("repo");
    return item;
  }

  private _trackTreeItem(node: TrackNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      node.name,
      vscode.TreeItemCollapsibleState.None
    );

    item.description = node.hint
      ? `${node.open} open  ${node.hint}`
      : `${node.open} open`;

    const { icon, color } = categoryIcon(node.category);
    item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));

    item.contextValue = "workPlanTrack";
    item.tooltip = `${node.name} — ${node.status} · ${node.open} open`;

    item.command = {
      command: "workPlan.openTrack",
      title: "Open Track",
      arguments: [node.track],
    };

    return item;
  }
}
