import * as vscode from "vscode";
import type { Export, Issue } from "./model.ts";
import { buildTree, mergeFetchedUntracked, shouldExpandRepos, sortTracks, repoDescription, visibilityTierBadge, suggestedIssueNode } from "./treeModel.ts";
import type { RepoNode, TrackNode, UntrackedGroupNode, UntrackedIssueNode, EmptyRepoNode, FetchUntrackedNode, TierDupWarningNode, SuggestedGroupNode, SuggestedIssueNode, NeedsReviewGroupNode, StatusCategory, TrackSort } from "./treeModel.ts";
import type { SuggestionBuckets } from "./suggestions.ts";
import { applyLens } from "./webview/lenses.ts";
import type { Lens } from "./webview/lenses.ts";
import { lensShouldApply } from "./autofocus.ts";
import type { LensSource } from "./autofocus.ts";
import type { AuthState } from "./cli.ts";
import { SingleFlight } from "./singleFlight.ts";

// Re-export the node types so extension.ts only needs to import from tree.ts.
export type { RepoNode, TrackNode, UntrackedGroupNode, UntrackedIssueNode, EmptyRepoNode, FetchUntrackedNode, TierDupWarningNode, SuggestedGroupNode, SuggestedIssueNode, NeedsReviewGroupNode };

/** Every node kind the Tracks tree can render. */
type TreeNode =
  | RepoNode
  | TrackNode
  | UntrackedGroupNode
  | UntrackedIssueNode
  | EmptyRepoNode
  | FetchUntrackedNode
  | TierDupWarningNode
  | SuggestedGroupNode
  | SuggestedIssueNode
  | NeedsReviewGroupNode;
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
      // tellable apart without colour (#208). List-semantic token (not
      // charts.red) so it meets non-text contrast in dark themes (a11y pass).
      return { icon: "circle-slash", color: "list.errorForeground" };
    case "active":
      return { icon: "circle-filled", color: "charts.blue" };
    case "shipped":
      // charts.green (vivid "done") not charts.gray, which goes muted on dark.
      return { icon: "pass-filled", color: "charts.green" };
    case "parked":
      // descriptionForeground is the theme-tuned de-emphasized token — legible
      // where charts.gray dipped below 3:1 on dark themes.
      return { icon: "circle-outline", color: "descriptionForeground" };
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
  // Who set _activeLens (#357). Auto-focus uses this to never override a lens the
  // user picked. Starts "auto" so the first activation auto-focus can apply.
  private _lensSource: LensSource = "auto";
  private _activeSort: TrackSort = "default";
  // On-demand open-issue fetches for trackless repos (#303), keyed by github
  // slug. `export` doesn't emit untracked for repos with no tracks, so the user
  // fetches them explicitly; we cache the result here and merge it into the repo
  // node's `untracked` on every (re)build. Survives lens/sort re-renders and a
  // full refresh (a snapshot until the user re-fetches), cleared on nothing.
  private readonly _fetchedUntracked = new Map<string, Issue[]>();
  // Auto-slot suggestions (#241), keyed by github slug: the suggested/needsReview
  // buckets parsed from each repo's per-repo answers file, plus the batch_id of
  // the scan they belong to (so a stale answers file from a prior scan is
  // ignored). Populated by setSuggestions when an fs.watch fires or on cold-open.
  private readonly _suggestionsByRepo = new Map<string, SuggestionBuckets>();
  private readonly _batchIdByRepo = new Map<string, string>();
  // Last GitHub-auth probe result (#auth). null before the first probe. Drives
  // the `workPlanGitHubAuthed` context key + lets activation show its one-time
  // toast off the same probe the tree already ran (no second `gh` call).
  private _lastAuth: AuthState | null = null;
  private readonly _refreshFlight: SingleFlight;

  constructor(
    private readonly load: () => Promise<Export>,
    private readonly checkAuth: () => Promise<AuthState>,
  ) {
    this._refreshFlight = new SingleFlight(() => this._doRefresh());
  }

  /** The most recent auth probe result (null before the first refresh). */
  get lastAuth(): AuthState | null {
    return this._lastAuth;
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
   * Records an on-demand open-issue fetch for `repo` (#303) and re-renders so
   * the trackless repo shows its Untracked bucket. Works off the cached filtered
   * export — no CLI re-fetch of the whole export.
   */
  setFetchedUntracked(repo: string, issues: Issue[]): void {
    this._fetchedUntracked.set(repo, issues);
    const built = this._filteredCache ? buildTree(this._filteredCache) : [];
    this.roots = this._applySortToRepos(mergeFetchedUntracked(built, this._fetchedUntracked));
    this._onDidChangeTreeData.fire();
  }

  /**
   * Records the batch_id of the active auto-slot scan for `repo` (#241), so a
   * later answers-file read can validate the file belongs to this scan. Called by
   * the Suggest Tracks command right after the scan emits its batch.
   */
  setBatchId(repo: string, batchId: string): void {
    this._batchIdByRepo.set(repo, batchId);
  }

  /** The active scan's batch_id for `repo`, or undefined if none scanned yet. */
  getBatchId(repo: string): string | undefined {
    return this._batchIdByRepo.get(repo);
  }

  /**
   * Stores freshly-parsed auto-slot suggestions for `repo` (#241) and re-renders
   * so the Suggested / Needs review buckets appear (or clear). Works off the
   * cached filtered export — no CLI re-fetch. Empty buckets are stored too, so a
   * watch event that empties the file removes the buckets.
   */
  setSuggestions(repo: string, buckets: SuggestionBuckets): void {
    this._suggestionsByRepo.set(repo, buckets);
    this._onDidChangeTreeData.fire();
  }

  /** The parsed suggestions for `repo`, or undefined when none have been read. */
  getSuggestions(repo: string): SuggestionBuckets | undefined {
    return this._suggestionsByRepo.get(repo);
  }

  /**
   * Changes the sort mode and re-renders the tree from the cached filtered
   * export. Does not re-fetch from the CLI. Sort is applied to `roots` (tree)
   * only — `currentExport`/`rawExport` are unaffected.
   */
  setSort(mode: TrackSort): void {
    this._activeSort = mode;
    const filtered = this._filteredCache ? buildTree(this._filteredCache) : [];
    this.roots = this._applySortToRepos(mergeFetchedUntracked(filtered, this._fetchedUntracked));
    this._onDidChangeTreeData.fire();
  }

  /**
   * Applies a new lens and re-renders the tree (works off the cached export — no
   * CLI re-fetch). `source` records who chose it (#357): user choices are sticky,
   * so an `"auto"` call is a no-op once the user has set a lens. Defaults to
   * `"user"` so every existing call site (the QuickPick, the milestone filter, the
   * "All tracks" reset) marks its lens user-chosen without passing the arg.
   */
  setLens(lens: Lens, source: LensSource = "user"): void {
    if (!lensShouldApply(this._lensSource, source)) return;
    this._lensSource = source;
    this._activeLens = lens;
    this._filteredCache = this.cache ? applyLens(this.cache, lens) : null;
    this.roots = this._applySortToRepos(
      mergeFetchedUntracked(
        this._filteredCache ? buildTree(this._filteredCache) : [],
        this._fetchedUntracked,
      ),
    );
    this._onDidChangeTreeData.fire();
  }

  /**
   * Re-arms auto-focus by clearing a prior user override (#357). Called when the
   * workspace folders change, so opening a different folder can auto-focus again.
   * State-only — no re-render. A plain refresh() deliberately does NOT call this,
   * so a background poll can never clobber the lens the user chose.
   */
  resetLensSource(): void {
    this._lensSource = "auto";
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
   *
   * Three-state gate (#398):
   *  1. CLI missing (cliPresent false) — authoritative; clear tree, no-cli banner.
   *  2. Not authenticated:
   *     a. Transient probe error (probeOk false) + last-good tree exists → keep tree.
   *     b. Authoritative logged-out (probeOk true) OR no last-good → clear tree.
   *  3. Authenticated — run export; keep last-good on load failure.
   *
   * viewsWelcome is driven off CONFIG state (repos present) not tracks.length, so a
   * configured-but-empty user never sees "No repos yet" onboarding (#398).
   */
  private async _doRefresh(): Promise<void> {
    await vscode.window.withProgress(
      { location: { viewId: "workPlan.tree" } },
      async () => {
        // Probe GitHub auth FIRST (#auth). Without it, the export below returns
        // tracks with zeroed issues and unknown visibility — a misleading
        // "empty but working" tree.
        const auth = await this.checkAuth();
        this._lastAuth = auth;
        this._setAuthContext(auth);

        // 1. CLI missing — authoritative "install the CLI" state. Clear tree.
        if (!auth.cliPresent) {
          this.roots = [];
          void vscode.commands.executeCommand("setContext", "workPlanLoadError", false);
          this._onDidChangeTreeData.fire();
          return;
        }

        // 2. Not authenticated.
        if (!auth.authenticated) {
          if (!auth.probeOk && this.cache !== null) {
            // Transient probe error AND we have a last-good tree — keep it.
            // Surface a subtle load-error indicator so the user knows the tree
            // may be stale, but don't wipe it with an onboarding banner.
            void vscode.commands.executeCommand("setContext", "workPlanLoadError", true);
            this._onDidChangeTreeData.fire();
            return;
          }
          // Authoritative not-signed-in (probeOk true), or no last-good tree.
          // Clear the tree so the connect banner renders.
          this.roots = [];
          void vscode.commands.executeCommand("setContext", "workPlanLoadError", false);
          this._onDidChangeTreeData.fire();
          return;
        }

        // 3. Authenticated — load export.
        let loaded: import("./model.ts").Export;
        try {
          loaded = await this.load();
        } catch {
          // Load failed (CLI error, parse failure, etc.).
          if (this.cache !== null) {
            // Keep last-good tree; surface load-error indicator.
            void vscode.commands.executeCommand("setContext", "workPlanLoadError", true);
            this._onDidChangeTreeData.fire();
          } else {
            // No last-good tree — show empty view with error context.
            this.roots = [];
            void vscode.commands.executeCommand("setContext", "workPlanLoadError", true);
            this._onDidChangeTreeData.fire();
          }
          return;
        }

        this.cache = loaded;
        void vscode.commands.executeCommand("setContext", "workPlanLoadError", false);
        this._filteredCache = applyLens(this.cache, this._activeLens);
        this.roots = this._applySortToRepos(
          mergeFetchedUntracked(buildTree(this._filteredCache), this._fetchedUntracked),
        );
        this._onDidChangeTreeData.fire();

        // Drive viewsWelcome off CONFIG state (repos present OR tracks present)
        // so a configured-but-empty user never sees "No repos yet" onboarding.
        // Use the RAW (unfiltered) data so an active lens that hides everything
        // doesn't incorrectly flip these flags.
        const configured =
          (this.cache.repos?.length ?? 0) > 0 || this.cache.tracks.length > 0;
        void vscode.commands.executeCommand("setContext", "workPlanConfigured", configured);
        void vscode.commands.executeCommand(
          "setContext",
          "workPlanHasTracks",
          this.cache.tracks.length > 0,
        );
      },
    );
  }

  /** Sets the `workPlanGitHubAuthed` context key that gates the Tracks
   *  viewsWelcome banners: `true` (signed in), `false` (gh present, not signed
   *  in), `"no-gh"` (gh not installed), `"no-cli"` (the work-plan CLI itself
   *  wasn't found on PATH — #402; the most common Remote-WSL failure), or
   *  `"probe-error"` (the CLI ran but returned no trustworthy answer — a runtime
   *  / dependency problem, NOT a sign-in state; e.g. an older launcher gating the
   *  probe behind a missing yq). Order matters: a missing CLI means we never
   *  reached gh; an untrustworthy probe means `ghPresent`/`false` are guesses, so
   *  both are checked before the authoritative signed-out value. */
  private _setAuthContext(auth: AuthState): void {
    const value: boolean | string = auth.authenticated
      ? true
      : !auth.cliPresent
        ? "no-cli"
        : !auth.probeOk
          ? "probe-error"
          : auth.ghPresent
            ? false
            : "no-gh";
    void vscode.commands.executeCommand("setContext", "workPlanGitHubAuthed", value);
  }

  getChildren(element?: TreeNode): TreeNode[] {
    if (!element) {
      // Root: return the cached repo nodes (empty [] before first refresh).
      return this.roots;
    }
    if (element.kind === "repo") {
      const untrackedGroup: UntrackedGroupNode[] =
        element.untracked.length > 0
          ? [{ kind: "untrackedGroup", repo: element.repo, issues: element.untracked }]
          : [];

      // Read-only tier-duplicate advisory (#361), pinned at the top of the repo
      // so the "exists in both tiers" condition is visible at a glance instead
      // of buried in unread stderr. No command — cleanup stays in the CLI.
      const tierDupWarn: TierDupWarningNode[] =
        element.tierDuplicates.length > 0
          ? [{
              kind: "tierDupWarning",
              repo: element.repo,
              folder: element.folder,
              count: element.tierDuplicates.length,
              safeCount: element.tierDuplicates.filter(d => d.safe).length,
            }]
          : [];

      // A configured-but-empty repo (#288): the dimmed "add a track" affordance,
      // plus — for a real repo (has a slug to query) — an on-demand fetch of its
      // open issues (#303), since `export` doesn't emit untracked for a trackless
      // repo. After a fetch, the Untracked bucket renders alongside.
      if (element.tracks.length === 0) {
        // The "add a track" empty-state must only show for a repo that is
        // genuinely empty in the RAW (unfiltered) export. A repo with tracks in
        // the raw data but zero here is hidden by an active lens — rendering
        // "No tracks yet — add one" for it reads as data loss (the repo-lens
        // "my tracks vanished" bug). applyLens already drops lens-filtered repos
        // from the forwarded `repos` list, so post-fix such a node shouldn't
        // reach here at all; this is the belt-and-suspenders guard against any
        // future lens that forwards a repo with no surviving track.
        const genuinelyEmpty =
          !this.cache || !this.cache.tracks.some(t => t.repo === element.repo);
        const children: TreeNode[] = [
          ...tierDupWarn,
          ...(genuinelyEmpty
            ? [{ kind: "emptyRepo", repo: element.repo, folder: element.folder } as TreeNode]
            : []),
          ...untrackedGroup,
        ];
        if (element.repo !== "(no repo)") {
          children.push({
            kind: "fetchUntracked",
            repo: element.repo,
            fetched: this._fetchedUntracked.has(element.repo),
            count: element.untracked.length,
          });
        }
        return children;
      }
      return [...tierDupWarn, ...element.tracks, ...untrackedGroup];
    }
    if (element.kind === "untrackedGroup") {
      // Auto-slot suggestion sub-buckets (#241) nest as the FIRST children of the
      // Untracked group, ahead of the plain untracked issues. They appear only
      // after the user explicitly runs Suggest Tracks for this repo (nothing
      // generates them in the background), so the explicit command IS the opt-in
      // — there's no separate enable setting to forget (#373 follow-up).
      const children: TreeNode[] = [];
      // Issue numbers surfaced in a suggestion sub-bucket are removed from the
      // plain list below, so a suggested issue shows in ONE place, not two.
      const bucketed = new Set<number>();
      const buckets = this._suggestionsByRepo.get(element.repo);
      if (buckets) {
        if (buckets.suggested.length > 0) {
          children.push({ kind: "suggestedGroup", repo: element.repo, suggestions: buckets.suggested });
          for (const s of buckets.suggested) bucketed.add(s.issueNumber);
        }
        if (buckets.needsReview.length > 0) {
          children.push({ kind: "needsReviewGroup", repo: element.repo, suggestions: buckets.needsReview });
          for (const s of buckets.needsReview) bucketed.add(s.issueNumber);
        }
      }
      return [
        ...children,
        ...element.issues
          .filter(issue => !bucketed.has(issue.number))
          .map((issue): UntrackedIssueNode => ({ kind: "untrackedIssue", repo: element.repo, issue })),
      ];
    }
    if (element.kind === "suggestedGroup") {
      const untracked = this.roots.find(r => r.repo === element.repo)?.untracked ?? [];
      return element.suggestions.map(s => suggestedIssueNode(element.repo, s, untracked, "suggested"));
    }
    if (element.kind === "needsReviewGroup") {
      const untracked = this.roots.find(r => r.repo === element.repo)?.untracked ?? [];
      return element.suggestions.map(s => suggestedIssueNode(element.repo, s, untracked, "needsReview"));
    }
    // TrackNode, UntrackedIssueNode, or SuggestedIssueNode — leaves; no children.
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
    if (element.kind === "fetchUntracked") {
      return this.roots.find(r => r.repo === element.repo);
    }
    if (element.kind === "tierDupWarning") {
      return this.roots.find(r => r.repo === element.repo);
    }
    // suggestedGroup / needsReviewGroup / suggestedIssue → the repo's Untracked
    // group (the suggestion sub-buckets and their issues all nest under it).
    if (
      element.kind === "suggestedGroup" ||
      element.kind === "needsReviewGroup" ||
      element.kind === "suggestedIssue"
    ) {
      const repoNode = this.roots.find(r => r.repo === element.repo);
      if (repoNode) {
        return { kind: "untrackedGroup", repo: repoNode.repo, issues: repoNode.untracked };
      }
      return undefined;
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
    if (node.kind === "fetchUntracked") {
      return this._fetchUntrackedTreeItem(node);
    }
    if (node.kind === "untrackedGroup") {
      return this._untrackedGroupTreeItem(node);
    }
    if (node.kind === "untrackedIssue") {
      return this._untrackedIssueTreeItem(node);
    }
    if (node.kind === "tierDupWarning") {
      return this._tierDupWarningTreeItem(node);
    }
    if (node.kind === "suggestedGroup") {
      return this._suggestedGroupTreeItem(node);
    }
    if (node.kind === "needsReviewGroup") {
      return this._needsReviewGroupTreeItem(node);
    }
    if (node.kind === "suggestedIssue") {
      return this._suggestedIssueTreeItem(node);
    }
    return this._trackTreeItem(node);
  }

  private _tierDupWarningTreeItem(node: TierDupWarningNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      `${node.count} track${node.count === 1 ? "" : "s"} duplicated across tiers`,
      vscode.TreeItemCollapsibleState.None,
    );
    const cmd = node.folder ? `dedupe-tiers --repo=${node.folder}` : "dedupe-tiers";
    item.description = cmd;
    item.iconPath = new vscode.ThemeIcon(
      "warning",
      new vscode.ThemeColor("list.warningForeground"),
    );
    item.contextValue = "workPlanTierDupWarning";
    const diverged = node.count - node.safeCount;
    const md = new vscode.MarkdownString(undefined, true);
    md.appendMarkdown(
      `$(warning) **${node.count} track${node.count === 1 ? "" : "s"} ` +
      `exist in both the shared and private tier.**\n\n` +
      `Private copies left behind after a track was promoted to the shared ` +
      `\`.work-plan/\` tier. The CLI uses the shared copy; the private orphan is ignored.\n\n` +
      `- ${node.safeCount} safe to remove automatically (private issues ⊆ shared)\n` +
      `- ${diverged} diverged — need manual review\n\n` +
      `Resolve from a terminal:\n\n\`/work-plan ${cmd}\`\n\n` +
      `(dry-run report; add \`--apply\` to remove the safe ones)`,
    );
    item.tooltip = md;
    return item;
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
    // "N open · C/T" — the closed/total count (#220) makes progress glanceable
    // in the tree (the detail panel has the bar). Omit C/T for an empty track.
    const total = node.open + node.closed;
    const counts = total > 0
      ? `${node.open} open · ${node.closed}/${total}`
      : `${node.open} open`;
    // 🧹 marks a track flagged as a cleanup candidate (#328/#329/#330) — a
    // reversible frontmatter flag, surfaced alongside the visibility/tier badge.
    const cleanup = node.track.cleanup_candidate ? " 🧹" : "";
    item.description = node.hint
      ? `${badge.descriptionPrefix}  ${counts}  ${node.hint}${cleanup}`
      : `${badge.descriptionPrefix}  ${counts}${cleanup}`;

    const { icon, color } = categoryIcon(node.category);
    item.iconPath = new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));

    item.contextValue = "workPlanTrack";
    // MarkdownString (supportThemeIcons) so the $(icon) glyphs render in the tooltip.
    const tip = new vscode.MarkdownString(undefined, true);
    tip.appendMarkdown(`**${node.name}** — ${node.status} · ${node.open} open\n\n`);
    tip.appendMarkdown(badge.tooltipMarkdown);
    if (node.track.cleanup_candidate) {
      const reason = node.track.cleanup_reason;
      tip.appendMarkdown(`\n\n🧹 Cleanup candidate${reason ? ` — ${reason}` : ""}`);
    }
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
        tierDuplicates: [],
        folder: node.folder,
        hasLocal: false,
      }
    );
  }

  private _fetchUntrackedTreeItem(node: FetchUntrackedNode): vscode.TreeItem {
    const label = node.fetched
      ? node.count > 0
        ? "Refresh open issues"
        : "No open issues — re-check"
      : "Fetch open issues";
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    item.iconPath = new vscode.ThemeIcon("cloud-download");
    item.contextValue = "workPlanFetchUntracked";
    item.tooltip =
      `Fetch this repo's open GitHub issues (issues in no track) for ${node.repo}. ` +
      "export doesn't pull these automatically for a repo with no tracks.";
    item.command = {
      command: "workPlan.fetchOpenIssues",
      title: "Fetch open issues",
      arguments: [{ repo: node.repo }],
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

  // --- Auto-slot suggestion nodes (#241) ---

  private _suggestedGroupTreeItem(node: SuggestedGroupNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      "Suggested",
      vscode.TreeItemCollapsibleState.Expanded,
    );
    const offline = this._suggestionsByRepo.get(node.repo)?.source === "heuristic";
    item.description = offline ? `${node.suggestions.length} · offline` : `${node.suggestions.length}`;
    item.iconPath = new vscode.ThemeIcon("sparkle");
    item.contextValue = "workPlanSuggestedGroup";
    item.tooltip =
      `${node.suggestions.length} issue(s) with a confident track suggestion — ` +
      "accept individually, or Accept All from the right-click menu." +
      (offline ? "\n\nOffline matches (no AI) — lower-trust; review before accepting." : "");
    return item;
  }

  private _needsReviewGroupTreeItem(node: NeedsReviewGroupNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      "Needs review",
      vscode.TreeItemCollapsibleState.Collapsed,
    );
    item.description = `${node.suggestions.length}`;
    item.iconPath = new vscode.ThemeIcon("sparkle");
    item.contextValue = "workPlanNeedsReviewGroup";
    item.tooltip =
      `${node.suggestions.length} lower-confidence or close-call suggestion(s) — ` +
      "no one-click accept; click an issue to open it and decide.";
    return item;
  }

  private _suggestedIssueTreeItem(node: SuggestedIssueNode): vscode.TreeItem {
    const item = new vscode.TreeItem(
      `#${node.issue.number}  ${node.issue.title}`,
      vscode.TreeItemCollapsibleState.None,
    );
    // Lead with the rationale + target track, NOT the percentage (the spec keeps
    // the number out of the at-a-glance label; it lives in the tooltip only).
    const rationale = node.rationale.trim();
    item.description = rationale
      ? `→ ${node.suggestedTrack} · ${rationale}`
      : `→ ${node.suggestedTrack}`;
    item.iconPath = new vscode.ThemeIcon("lightbulb");
    item.contextValue =
      node.tier === "suggested" ? "workPlanSuggestedIssue" : "workPlanNeedsReviewIssue";

    const pct = Math.round(node.confidence * 100);
    const tip = new vscode.MarkdownString(undefined, true);
    tip.appendMarkdown(`**#${node.issue.number}** ${node.issue.title}\n\n`);
    tip.appendMarkdown(`$(lightbulb) Suggested track: **${node.suggestedTrack}**\n\n`);
    if (node.runnerUp) {
      tip.appendMarkdown(`Runner-up: ${node.runnerUp}\n\n`);
    }
    tip.appendMarkdown(
      `Confidence: ${pct}% · margin: ${node.margin === "clear" ? "clear" : "narrow (needs review)"}\n\n`,
    );
    if (rationale) tip.appendMarkdown(`_${rationale}_`);
    item.tooltip = tip;

    // A "Suggested" (one-click) issue opens the accept QuickPick on click; a
    // "Needs review" issue opens the issue itself (no one-click accept).
    item.command =
      node.tier === "suggested"
        ? { command: "workPlan.acceptSuggestion", title: "Accept suggestion", arguments: [node] }
        : { command: "workPlan.openIssue", title: "Open Issue", arguments: [{ repo: node.repo, number: node.issue.number }] };

    return item;
  }
}
