import * as vscode from "vscode";
import type { PlanDoc } from "./model.ts";
import { planStatus, CliError } from "./cli.ts";
import type { CliRunner } from "./cli.ts";
import { planBucket, planDescription, isStalledForDisplay, BUCKET_META, BUCKET_RANK } from "./planModel.ts";

// Coalesce a burst of git events (a rebase rewrites many refs) into one re-scan
// per repo (#287). 750ms is long enough to ride out a multi-commit operation,
// short enough that a single commit clears a stalled flag near-instantly.
const RESCAN_DEBOUNCE_MS = 750;

// ---------------------------------------------------------------------------
// Node types — five variants. `repo` and `doc` are the real tree nodes;
// `message` is a leaf used for empty / error / no-clone states so a repo that
// can't be scanned still renders an explanatory child instead of vanishing.
// `rollup` is the synthetic first root: a cross-repo "stalled everywhere" view
// populated by the Scan All command. `unregistered` is a greyed leaf for a repo
// that has tracks but no `repos:` entry — present-but-not-scannable.
// ---------------------------------------------------------------------------

export type PlanNode =
  | { kind: "rollup" }                                  // synthetic cross-repo stalled roll-up (first root)
  | { kind: "repo"; repoKey: string; label: string }   // repoKey = folder key; label = slug for display
  | { kind: "doc"; repoKey: string; repoRoot: string; doc: PlanDoc }
  | { kind: "unregistered"; slug: string }             // track-only repo, no config entry → greyed "Add Repo to scan" row
  | { kind: "message"; text: string; icon: string; command?: string };

// Bucket ordering (BUCKET_RANK) and verdict→icon/label metadata (BUCKET_META)
// live in planModel.ts — the pure, vscode-free module the legend + tests share.

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

  // Git-activity watchers + per-repo debounce timers (#287). A watcher exists
  // only for a repo currently in `cache` (i.e. expanded/scanned) — we never
  // eagerly watch a collapsed repo. Both are torn down by refresh()/dispose().
  private gitWatchers = new Map<string, vscode.Disposable>();
  private rescanTimers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor(
    private readonly runner: CliRunner,
    private readonly repos: () => { repoKey: string; label: string }[],
    private readonly stallDays: () => number | null,
    private readonly isAcked: (repoKey: string, rel: string) => boolean,
    private readonly showAcked: () => boolean,
    // Slugs of repos that have tracks but no `repos:` config entry — rendered as
    // greyed "not registered" leaves AFTER the real repo nodes. Kept separate
    // from `repos()` on purpose: these have no folder key, so Scan All and the
    // roll-up (which both work off `repos()`/the cache) must never try them.
    private readonly unregistered: () => string[] = () => [],
    // Whether to auto-update on git activity (#287). Read live so toggling the
    // `workPlan.plansAutoRefresh` setting takes effect without a reload.
    private readonly autoUpdate: () => boolean = () => true,
  ) {}

  /** A doc is acknowledged if EITHER the per-machine workspaceState ack is set
   *  OR the doc carries a durable frontmatter `acknowledged: true` (#286). Both
   *  demote the doc; the durable one also survives across machines/teammates. */
  private _acked(repoKey: string, doc: PlanDoc): boolean {
    return this.isAcked(repoKey, doc.rel) || doc.acknowledged === true;
  }

  async getChildren(element?: PlanNode): Promise<PlanNode[]> {
    if (!element) {
      // Roots — the synthetic stalled roll-up first, then one collapsed node
      // per distinct registered repo (folder key), then any track-only repos as
      // greyed "not registered" leaves so the Tracks/Plans asymmetry is visible
      // and actionable rather than looking like a dropped repo.
      const repoNodes = this.repos().map(
        (r): PlanNode => ({ kind: "repo", repoKey: r.repoKey, label: r.label }),
      );
      const unregisteredNodes = this.unregistered().map(
        (slug): PlanNode => ({ kind: "unregistered", slug }),
      );
      return [{ kind: "rollup" }, ...repoNodes, ...unregisteredNodes];
    }

    if (element.kind === "rollup") {
      return this._childrenForRollup();
    }

    if (element.kind === "repo") {
      return this._childrenForRepo(element.repoKey);
    }

    // doc / message → leaves.
    return [];
  }

  /** Stalled docs across every currently-cached repo, as doc nodes. Empty cache
   *  → prompt to scan; scanned-but-clean → "no stalled plans". */
  private _childrenForRollup(): PlanNode[] {
    let stalled = this._stalledDocs();
    // "Show acknowledged" off → hide acked docs entirely (default is demote-not-hide).
    if (!this.showAcked()) {
      stalled = stalled.filter(({ repoKey, doc }) => !this._acked(repoKey, doc));
    }
    if (stalled.length > 0) {
      return stalled.map(
        ({ repoKey, repoRoot, doc }): PlanNode => ({ kind: "doc", repoKey, repoRoot, doc }),
      );
    }
    if (this.cache.size === 0) {
      return [{
        kind: "message",
        text: "Scan all repos for stalled plans…",
        icon: "telescope",
        command: "workPlan.plans.scanAll",
      }];
    }
    return [{ kind: "message", text: "No stalled plans", icon: "pass" }];
  }

  /** Gather stalled docs across the whole cache (for the roll-up + its count). */
  private _stalledDocs(): { repoKey: string; repoRoot: string; doc: PlanDoc }[] {
    const now = Date.now();
    const stall = this.stallDays();
    const out: { repoKey: string; repoRoot: string; doc: PlanDoc }[] = [];
    for (const [repoKey, entry] of this.cache) {
      for (const doc of entry.docs) {
        if (isStalledForDisplay(doc, stall, now)) {
          out.push({ repoKey, repoRoot: entry.repoRoot, doc });
        }
      }
    }
    return out;
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
        this._ensureGitWatcher(repoKey, res.repo);
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
    // "Show acknowledged" off → hide acked docs in the per-repo list too.
    const visible = this.showAcked()
      ? entry.docs
      : entry.docs.filter((doc) => !this._acked(repoKey, doc));
    const sorted = [...visible].sort(
      (a, b) => BUCKET_RANK[planBucket(a, stall, now)] - BUCKET_RANK[planBucket(b, stall, now)],
    );
    return sorted.map(
      (doc): PlanNode => ({ kind: "doc", repoKey, repoRoot: entry.repoRoot, doc }),
    );
  }

  getTreeItem(node: PlanNode): vscode.TreeItem {
    if (node.kind === "rollup") {
      const item = new vscode.TreeItem(
        "Stalled across repos",
        vscode.TreeItemCollapsibleState.Collapsed,
      );
      item.contextValue = "workPlanPlansRollup";
      item.iconPath = new vscode.ThemeIcon("warning", new vscode.ThemeColor("list.warningForeground"));
      const count = this._stalledDocs().length;
      item.description = String(count);
      return item;
    }

    if (node.kind === "repo") {
      const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Collapsed);
      item.contextValue = "workPlanPlansRepo";
      item.iconPath = new vscode.ThemeIcon("repo");
      return item;
    }

    if (node.kind === "unregistered") {
      // A repo that has tracks but no `repos:` entry — the Plans view can't scan
      // it (no registered local clone). Render a greyed, non-expandable leaf that
      // launches Add Repo prefilled with the slug, so the fix is one click away.
      const item = new vscode.TreeItem(node.slug, vscode.TreeItemCollapsibleState.None);
      item.contextValue = "workPlanPlansUnregistered";
      item.iconPath = new vscode.ThemeIcon("circle-slash", new vscode.ThemeColor("disabledForeground"));
      item.description = "not registered";
      const tip = new vscode.MarkdownString(undefined, true);
      tip.appendMarkdown(
        `\`${node.slug}\` has tracks but **no registered local clone**, so the Plans ` +
        `view can't scan its plans. Click to **Add Repo** — register a checkout path ` +
        `and it becomes a scannable repo here.`,
      );
      item.tooltip = tip;
      item.command = {
        command: "workPlan.addRepo",
        title: "Add Repo",
        arguments: [{ github: node.slug }],
      };
      return item;
    }

    if (node.kind === "message") {
      const item = new vscode.TreeItem(node.text, vscode.TreeItemCollapsibleState.None);
      item.iconPath = new vscode.ThemeIcon(node.icon);
      if (node.command) {
        // Make the empty-state itself actionable — clicking it runs the command
        // (the title-bar icon alone proved undiscoverable; #164 follow-up).
        item.command = { command: node.command, title: node.text };
        item.tooltip = "Click to scan every local-clone repo for stalled plans";
      }
      return item;
    }

    return this._docTreeItem(node);
  }

  private _docTreeItem(node: Extract<PlanNode, { kind: "doc" }>): vscode.TreeItem {
    const { doc, repoKey, repoRoot } = node;
    const now = Date.now();
    const stall = this.stallDays();
    const bucket = planBucket(doc, stall, now);
    // Two ack flavors (#286): a durable frontmatter ack (committed, shared) and
    // the per-machine workspaceState ack. Either demotes the row; the durable
    // one reads "ack'd (saved)" and offers a different (write) menu.
    const docAcked = doc.acknowledged === true;
    const localAcked = this.isAcked(repoKey, doc.rel);
    const acked = docAcked || localAcked;

    const filename = doc.rel.split("/").pop() ?? doc.rel;
    const item = new vscode.TreeItem(filename, vscode.TreeItemCollapsibleState.None);

    // Icon — verdict-driven, with a muted override when the plan has been ack'd.
    const meta = BUCKET_META[bucket];
    const [icon, color] = acked ? ["circle-outline", "descriptionForeground"] : [meta.icon, meta.color];
    item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));

    const ackLabel = docAcked ? " · ✅ ack'd (saved)" : localAcked ? " · ack'd" : "";
    item.description = planDescription(doc, stall, now) + ackLabel;

    // joinPath (not string concat) so a Windows repoRoot — backslashes from
    // Python's str(repo_root) — joins with doc.rel's forward slashes without a
    // mixed-separator path.
    const resourceUri = vscode.Uri.joinPath(vscode.Uri.file(repoRoot), doc.rel);
    item.resourceUri = resourceUri;

    // Tooltip (MarkdownString with supportThemeIcons) — rel, the verdict line,
    // the phase/file rollup, and any unchecked items.
    const tip = new vscode.MarkdownString(undefined, true);
    tip.appendMarkdown(`\`${doc.rel}\`\n\n`);
    // Lead with the plain verdict label + its themed codicon (#348) so the hover
    // decodes the row icon; keep the raw CLI verdict after it for precision.
    tip.appendMarkdown(`$(${meta.icon}) **${meta.label}** · _${doc.verdict}_ — ${doc.rationale}\n\n`);
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
    // Off-tree declared paths (#286) — name them so a typo/misfile is obvious;
    // these resolve outside the repo and can never satisfy the manifest.
    if (doc.offtree_paths && doc.offtree_paths.length > 0) {
      tip.appendMarkdown(`\n\n**⚠ Off-tree declared paths** (resolve outside this repo):\n`);
      for (const p of doc.offtree_paths) {
        tip.appendMarkdown(`- \`${p}\`\n`);
      }
    }
    item.tooltip = tip;

    item.command = {
      command: "vscode.open",
      title: "Open",
      arguments: [resourceUri],
    };

    // contextValue drives the right-click menu (#286). Precedence (a node has
    // ONE value): confirmed → "clear confirmation"; durable frontmatter-ack →
    // "clear saved acknowledgment"; local ack → "un-acknowledge"; otherwise the
    // bucket value, which offers "confirm verdict…", the two acks, and the
    // baseline actions. A " baselined" token is appended on bucket-state docs
    // that carry a baseline so "Clear Baseline" can match via a regex when-clause
    // (the existing bucket menus use prefix/contains matches, so the suffix is
    // transparent to them).
    const base = doc.override
      ? "workPlanPlanConfirmed"
      : docAcked
        ? "workPlanPlanDocAcked"
        : localAcked
          ? "workPlanAckedPlan"
          : `workPlanPlan-${bucket}`;
    item.contextValue = base.startsWith("workPlanPlan-") && doc.verdict_baseline
      ? `${base} baselined`
      : base;
    return item;
  }

  /**
   * Scans every export repo with bounded concurrency (4 workers draining a
   * shared queue — not one git process per repo) and streams results into the
   * cache, firing a re-render after each repo lands so the roll-up fills in
   * progressively. Repos with no local clone / scan errors are left uncached;
   * they'll surface their message leaf when expanded manually.
   */
  async scanAll(): Promise<void> {
    const repos = this.repos();
    const queue = [...repos];
    const worker = async (): Promise<void> => {
      for (let r = queue.shift(); r; r = queue.shift()) {
        try {
          const res = await planStatus(this.runner, r.repoKey, this.stallDays() ?? undefined);
          this.cache.set(r.repoKey, { docs: res.docs, repoRoot: res.repo });
          this._ensureGitWatcher(r.repoKey, res.repo);
        } catch {
          // No local clone / scan error — leave uncached.
        }
        this._onDidChangeTreeData.fire(undefined); // STREAM: re-render per repo.
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(4, repos.length) }, () => worker()),
    );
  }

  /** Clears one repo's scan cache (or all) and re-renders the Plans tree. Also
   *  tears down the matching git watcher(s) (#287) — the watcher is recreated
   *  when the repo is next expanded/scanned, against its fresh repoRoot. */
  refresh(repoKey?: string): void {
    if (repoKey) {
      this.cache.delete(repoKey);
      this._disposeWatcher(repoKey);
    } else {
      this.cache.clear();
      for (const key of [...this.gitWatchers.keys()]) {
        this._disposeWatcher(key);
      }
    }
    this._onDidChangeTreeData.fire(undefined);
  }

  /**
   * Re-renders the Plans tree WITHOUT clearing the scan cache. Use for
   * display-only changes — ack/un-ack, stall-threshold tweaks, repo-list shifts
   * from a fresh export — where the cached per-repo docs are still valid and the
   * render path (getChildren re-reads repos() + this.stallDays/isAcked) picks up
   * the new state on its own. A completed "Scan All" roll-up survives.
   */
  rerender(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  // -------------------------------------------------------------------------
  // Git-activity auto-update (#287)
  // -------------------------------------------------------------------------

  /**
   * Watch a cached repo's git refs so a commit to a plan's declared files clears
   * its stalled state without a manual Refresh. We watch `.git/{HEAD,logs/HEAD,
   * refs/**}` — the files a commit/checkout/reset rewrites — not the objects
   * store (huge + excluded by the default watcherExclude), and debounce-rescan
   * only this repo. No-op when auto-update is off or a watcher already exists.
   */
  private _ensureGitWatcher(repoKey: string, repoRoot: string): void {
    if (!this.autoUpdate() || this.gitWatchers.has(repoKey)) {
      return;
    }
    const pattern = new vscode.RelativePattern(
      vscode.Uri.file(repoRoot), ".git/{HEAD,logs/HEAD,refs/**}",
    );
    const watcher = vscode.workspace.createFileSystemWatcher(pattern);
    const onGit = (): void => this._scheduleRescan(repoKey);
    watcher.onDidChange(onGit);
    watcher.onDidCreate(onGit);
    watcher.onDidDelete(onGit);
    this.gitWatchers.set(repoKey, watcher);
  }

  /** Debounced per-repo re-scan trigger (#287) — coalesces a burst of git events
   *  into a single plan-status run. */
  private _scheduleRescan(repoKey: string): void {
    const pending = this.rescanTimers.get(repoKey);
    if (pending) {
      clearTimeout(pending);
    }
    this.rescanTimers.set(repoKey, setTimeout(() => {
      this.rescanTimers.delete(repoKey);
      void this._rescanRepo(repoKey);
    }, RESCAN_DEBOUNCE_MS));
  }

  /** Re-run plan-status for one already-cached repo and re-render (#287). A repo
   *  that was collapsed/cleared since the event is skipped (we never eagerly scan
   *  a collapsed repo); a transient scan failure keeps the stale cache. */
  private async _rescanRepo(repoKey: string): Promise<void> {
    if (!this.cache.has(repoKey)) {
      return;
    }
    try {
      const res = await planStatus(this.runner, repoKey, this.stallDays() ?? undefined);
      this.cache.set(repoKey, { docs: res.docs, repoRoot: res.repo });
      this._onDidChangeTreeData.fire(undefined);
    } catch {
      // Mid-rebase / index lock / transient failure — keep the last good cache;
      // the next git event or a manual refresh recovers.
    }
  }

  /** Dispose one repo's watcher + pending debounce timer (#287). */
  private _disposeWatcher(repoKey: string): void {
    this.gitWatchers.get(repoKey)?.dispose();
    this.gitWatchers.delete(repoKey);
    const timer = this.rescanTimers.get(repoKey);
    if (timer) {
      clearTimeout(timer);
      this.rescanTimers.delete(repoKey);
    }
  }

  /** Tear down every watcher + timer. Called from extension deactivation so the
   *  provider leaves no file watchers behind (#287). */
  dispose(): void {
    for (const key of [...this.gitWatchers.keys()]) {
      this._disposeWatcher(key);
    }
  }
}
