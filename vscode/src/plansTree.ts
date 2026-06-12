import * as vscode from "vscode";
import type { PlanDoc } from "./model.ts";
import { planStatus, CliError } from "./cli.ts";
import type { CliRunner } from "./cli.ts";
import { planBucket, planDescription } from "./planModel.ts";
import type { PlanBucket } from "./planModel.ts";

// ---------------------------------------------------------------------------
// Node types — three variants. `repo` and `doc` are the real tree nodes;
// `message` is a leaf used for empty / error / no-clone states so a repo that
// can't be scanned still renders an explanatory child instead of vanishing.
// ---------------------------------------------------------------------------

export type PlanNode =
  | { kind: "repo"; repoKey: string; label: string }   // repoKey = folder key; label = slug for display
  | { kind: "doc"; repoKey: string; repoRoot: string; doc: PlanDoc }
  | { kind: "message"; text: string; icon: string };

// ---------------------------------------------------------------------------
// Bucket ordering + verdict→icon mapping
// ---------------------------------------------------------------------------

/** Sort rank for a bucket — loud verdicts (stalled, lie-gap) float to the top. */
const BUCKET_RANK: Record<PlanBucket, number> = {
  stalled: 0,
  "lie-gap": 1,
  active: 2,
  shipped: 3,
  dead: 4,
  other: 5,
};

/** verdict-bucket → [codicon, ThemeColor id]. */
const BUCKET_ICON: Record<PlanBucket, [string, string]> = {
  stalled: ["warning", "charts.red"],
  "lie-gap": ["error", "charts.red"],
  active: ["circle-filled", "charts.yellow"],
  shipped: ["pass-filled", "charts.gray"],
  dead: ["circle-slash", "charts.gray"],
  other: ["question", "descriptionForeground"],
};

// ---------------------------------------------------------------------------
// PlansProvider
// ---------------------------------------------------------------------------

export class PlansProvider implements vscode.TreeDataProvider<PlanNode> {
  private _onDidChangeTreeData = new vscode.EventEmitter<PlanNode | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  // Per-repo scan cache (folder key → docs + the resolved repo root). Populated
  // lazily on expand; cleared by refresh(). repoRoot is derived from the first
  // doc's absolute path minus its rel, so doc nodes can form resourceUris.
  private cache = new Map<string, { docs: PlanDoc[]; repoRoot: string }>();

  constructor(
    private readonly runner: CliRunner,
    private readonly repos: () => { repoKey: string; label: string }[],
    private readonly stallDays: () => number | null,
    private readonly isAcked: (repoKey: string, rel: string) => boolean,
  ) {}

  async getChildren(element?: PlanNode): Promise<PlanNode[]> {
    if (!element) {
      // Roots — one collapsed node per distinct repo (folder key).
      return this.repos().map(
        (r): PlanNode => ({ kind: "repo", repoKey: r.repoKey, label: r.label }),
      );
    }

    if (element.kind === "repo") {
      return this._childrenForRepo(element.repoKey);
    }

    // doc / message → leaves.
    return [];
  }

  /**
   * Lazily scans a repo's plans, caches the result, and returns sorted doc nodes.
   * We can't cheaply know whether a repo has a local clone before expanding it —
   * `plan-status` is what resolves the local path — so the "no local clone"
   * state is surfaced here on expand (the v1 approach) rather than up front.
   */
  private async _childrenForRepo(repoKey: string): Promise<PlanNode[]> {
    if (!this.cache.has(repoKey)) {
      try {
        const res = await planStatus(this.runner, repoKey, this.stallDays() ?? undefined);
        // `res.repo` is the absolute local repo root (plan-status emits
        // `{"repo": str(repo_root), ...}`), so doc nodes form their resourceUri
        // as `<repoRoot>/<rel>`.
        this.cache.set(repoKey, { docs: res.docs, repoRoot: res.repo });
      } catch (err: unknown) {
        if (err instanceof CliError) {
          const blob = `${err.message} ${err.stderr}`.toLowerCase();
          // Exit 2 / "local"-flavoured failures mean the repo has no resolvable
          // local checkout — a recoverable, user-actionable state, not a crash.
          if (err.code === 2 || blob.includes("local")) {
            return [{
              kind: "message",
              text: "No local clone — run work-plan init-repo",
              icon: "circle-slash",
            }];
          }
          return [{ kind: "message", text: `Scan failed: ${err.message}`, icon: "error" }];
        }
        return [{ kind: "message", text: `Scan failed: ${String(err)}`, icon: "error" }];
      }
    }

    const entry = this.cache.get(repoKey)!;
    if (entry.docs.length === 0) {
      return [{ kind: "message", text: "No plans found", icon: "info" }];
    }

    const now = Date.now();
    const stall = this.stallDays();
    const sorted = [...entry.docs].sort(
      (a, b) => BUCKET_RANK[planBucket(a, stall, now)] - BUCKET_RANK[planBucket(b, stall, now)],
    );
    return sorted.map(
      (doc): PlanNode => ({ kind: "doc", repoKey, repoRoot: entry.repoRoot, doc }),
    );
  }

  getTreeItem(node: PlanNode): vscode.TreeItem {
    if (node.kind === "repo") {
      const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Collapsed);
      item.contextValue = "workPlanPlansRepo";
      item.iconPath = new vscode.ThemeIcon("repo");
      return item;
    }

    if (node.kind === "message") {
      const item = new vscode.TreeItem(node.text, vscode.TreeItemCollapsibleState.None);
      item.iconPath = new vscode.ThemeIcon(node.icon);
      return item;
    }

    return this._docTreeItem(node);
  }

  private _docTreeItem(node: Extract<PlanNode, { kind: "doc" }>): vscode.TreeItem {
    const { doc, repoKey, repoRoot } = node;
    const now = Date.now();
    const stall = this.stallDays();
    const bucket = planBucket(doc, stall, now);
    const acked = this.isAcked(repoKey, doc.rel);

    const filename = doc.rel.split("/").pop() ?? doc.rel;
    const item = new vscode.TreeItem(filename, vscode.TreeItemCollapsibleState.None);

    // Icon — verdict-driven, with a muted override when the plan has been ack'd.
    const [icon, color] = acked ? ["circle-outline", "charts.gray"] : BUCKET_ICON[bucket];
    item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));

    item.description = planDescription(doc, stall, now) + (acked ? " · ack'd" : "");

    // joinPath (not string concat) so a Windows repoRoot — backslashes from
    // Python's str(repo_root) — joins with doc.rel's forward slashes without a
    // mixed-separator path.
    const resourceUri = vscode.Uri.joinPath(vscode.Uri.file(repoRoot), doc.rel);
    item.resourceUri = resourceUri;

    // Tooltip (MarkdownString with supportThemeIcons) — rel, the verdict line,
    // the phase/file rollup, and any unchecked items.
    const tip = new vscode.MarkdownString(undefined, true);
    tip.appendMarkdown(`\`${doc.rel}\`\n\n`);
    tip.appendMarkdown(`${doc.glyph} **${doc.verdict}** — ${doc.rationale}\n\n`);
    tip.appendMarkdown(
      `Phases ${doc.checkboxes_done}/${doc.checkboxes_total} · ` +
      `Files ${doc.files_present}/${doc.files_declared}`,
    );
    if (doc.unchecked_items.length > 0) {
      tip.appendMarkdown(`\n\n**Unchecked:**\n`);
      for (const u of doc.unchecked_items) {
        tip.appendMarkdown(`- ${u}\n`);
      }
    }
    item.tooltip = tip;

    item.command = {
      command: "vscode.open",
      title: "Open",
      arguments: [resourceUri],
    };

    item.contextValue = acked ? "workPlanAckedPlan" : `workPlanPlan-${bucket}`;
    return item;
  }

  /** Clears one repo's scan cache (or all) and re-renders the Plans tree. */
  refresh(repoKey?: string): void {
    if (repoKey) {
      this.cache.delete(repoKey);
    } else {
      this.cache.clear();
    }
    this._onDidChangeTreeData.fire(undefined);
  }
}
