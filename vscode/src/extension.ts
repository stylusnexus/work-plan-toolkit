import * as vscode from "vscode";
import * as fs from "node:fs";
import {
  exportJson, listRepoOpenIssues, makeSpawnRunner, checkVersion, checkAuth, CliError,
  isAlreadyExistsError,
  notesVcsStatus, notesVcsRun, notesVcsUndo, suggestNextUp,
  autoTriageScan, doctorScan,
} from "./cli.ts";
import type { NotesVcsStatus, AuthState, DoctorFinding } from "./cli.ts";
import { buildDoctorStatus } from "./doctor.ts";
import { pickAutoFocusSlug } from "./autofocus.ts";
import { WorkPlanTreeProvider } from "./tree.ts";
import { PlansProvider } from "./plansTree.ts";
import { ackKey, unregisteredTrackRepos, LEGEND, archivableSelection, selectedDocNodes, isStalledForDisplay } from "./planModel.ts";
import type { Lens, TrackNode, UntrackedIssueNode, UntrackedGroupNode, RepoNode, SuggestedIssueNode, SuggestedGroupNode } from "./tree.ts";
import type { Track, Issue, PlanDoc } from "./model.ts";
import { trackedIssueNumbers, collectMilestones, trackKey, trackRepoQualifier } from "./model.ts";
import { badgeCounts } from "./treeModel.ts";
import { readSuggestions } from "./suggestions.ts";
import { issuesFingerprint } from "./fingerprint.ts";
import { buildIssuePickItems } from "./issuePick.ts";
import { WorkPlanPanel } from "./webview/panel.ts";
import { availableLenses, describeView } from "./webview/lenses.ts";
import { searchIssues } from "./webview/search.ts";
import { SearchPanel } from "./webview/searchPanel.ts";
import type { TrackSort } from "./tree.ts";
import { executeWrite } from "./write.ts";
import type { ConfirmPrompt, WriteOutcome } from "./write.ts";
import { resolveContainedFile } from "./pathSafety.ts";

// URL shown in "Update" notification and in CLI-not-found errors.
const TOOLKIT_URL = "https://github.com/stylusnexus/work-plan-toolkit";

export function activate(context: vscode.ExtensionContext): void {
  // -------------------------------------------------------------------------
  // Build the production runner from the configured CLI path.
  // -------------------------------------------------------------------------

  const cliPath = vscode.workspace
    .getConfiguration("workPlan")
    .get<string>("cliPath", "work-plan");
  const runner = makeSpawnRunner(cliPath);

  // -------------------------------------------------------------------------
  // Wire up the tree provider.
  // -------------------------------------------------------------------------

  // Show-archived toggle (#328): when on, the tree export includes archived-tier
  // tracks (greyed). Captured by the load closure so a toggle+refresh flips the
  // `--include-archived` flag without reconstructing the provider.
  let showArchivedTracks = false;

  const provider = new WorkPlanTreeProvider(
    () => exportJson(runner, showArchivedTracks),
    () => checkAuth(runner),
  );
  void vscode.commands.executeCommand("setContext", "workPlanShowArchived", showArchivedTracks);

  const treeView = vscode.window.createTreeView("workPlan.tree", {
    treeDataProvider: provider,
  });
  context.subscriptions.push(treeView);

  // Surface the active lens + sort inline under the Tracks view title (#209).
  // Every state change — refresh, setLens, setSort, the milestone-filter
  // handler, the reset — fires onDidChangeTreeData, so recomputing here keeps
  // the description in lockstep with what the tree actually shows. Empty string
  // (lens "all" + sort "default") clears it back to the bare title.
  const syncViewDescription = (): void => {
    treeView.description =
      describeView(provider.activeLens, provider.activeSort) || undefined;
  };
  context.subscriptions.push(provider.onDidChangeTreeData(syncViewDescription));

  // Activity-bar badge (#215): blocked-track count (the loud signal), falling
  // back to total open issues, cleared at zero. Recomputed on every tree change
  // (refresh/lens/sort) off the RAW export so a lens can't shrink the count.
  const syncBadge = (): void => {
    const exp = provider.rawExport;
    if (!exp) { treeView.badge = undefined; return; }
    const { blocked, open } = badgeCounts(exp.tracks);
    treeView.badge = blocked > 0
      ? { value: blocked, tooltip: `${blocked} blocked track${blocked === 1 ? "" : "s"}` }
      : open > 0
        ? { value: open, tooltip: `${open} open issue${open === 1 ? "" : "s"}` }
        : undefined;
  };
  context.subscriptions.push(provider.onDidChangeTreeData(syncBadge));

  // -------------------------------------------------------------------------
  // Repo auto-focus (#357): default the tree's lens to the repo of the open
  // workspace folder, so you're not reading another repo's issues by accident.
  // Probes each folder via `which-repo` (cwd-scoped) and focuses the first that
  // resolves to a configured repo with a github slug. setLens(..., "auto") is a
  // no-op once the user has picked a lens, so this never fights a manual choice.
  // -------------------------------------------------------------------------

  const autoFocusRepo = async (): Promise<void> => {
    const enabled = vscode.workspace
      .getConfiguration("workPlan")
      .get<boolean>("autoFocusRepo", false);
    if (!enabled) return;
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) return;
    try {
      const slug = await pickAutoFocusSlug(runner, folders.map(f => f.uri.fsPath));
      if (slug) provider.setLens({ kind: "repo", repo: slug }, "auto");
    } catch {
      // Auto-focus is a convenience — never surface its failure.
    }
  };

  // Re-arm + re-resolve when the workspace folders change (folder opened/closed).
  // resetLensSource() clears any prior user override so a deliberate folder switch
  // can focus again; a plain refresh() never resets it.
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      provider.resetLensSource();
      void autoFocusRepo();
    }),
  );

  // React to the auto-focus setting flipping at runtime. Without this, the
  // setting was only read at activation/folder-change, so toggling it OFF did
  // nothing until a reload — the already-applied auto repo lens stayed stuck,
  // hiding every other repo's tracks. ON re-applies the focus; OFF resets the
  // lens to "all" so all repos reappear immediately. setLens(...,"auto") is a
  // no-op over a lens the USER picked, so a manual lens is never clobbered.
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration("workPlan.autoFocusRepo")) return;
      const enabled = vscode.workspace
        .getConfiguration("workPlan")
        .get<boolean>("autoFocusRepo", false);
      if (enabled) {
        void autoFocusRepo();
      } else {
        provider.setLens({ kind: "all" }, "auto");
      }
    }),
  );

  // Repo-focus commands (#357 follow-up). Palette-only (no toolbar/menu entry —
  // the discoverable path is the state-aware toggle the Select View quick-pick
  // prepends); these back that toggle and give keyboard users a direct command.
  // Both are deliberate user actions, so they set the lens with source "user" —
  // they hold regardless of the autoFocusRepo setting, and auto-focus never
  // silently overrides them.
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.showAllRepos", () => {
      provider.setLens({ kind: "all" }, "user");
    }),
    vscode.commands.registerCommand("workPlan.focusCurrentRepo", async () => {
      const folders = vscode.workspace.workspaceFolders;
      const slug = folders
        ? await pickAutoFocusSlug(runner, folders.map(f => f.uri.fsPath))
        : null;
      if (slug) {
        provider.setLens({ kind: "repo", repo: slug }, "user");
      } else {
        // No workspace folder maps to a configured repo — nothing to focus.
        // Stay present in the toolbar (don't shift layout); just say why.
        vscode.window.showInformationMessage(
          "Work Plan: no workspace folder maps to a configured repo to focus.",
        );
      }
    }),
  );

  // -------------------------------------------------------------------------
  // refreshAndRerender — shared helper: reload CLI data + re-render panel.
  // Defined here so workPlan.refresh and all write commands share one copy.
  // -------------------------------------------------------------------------

  const refreshAndRerender = async (): Promise<void> => {
    await provider.refresh();
    const panel = WorkPlanPanel.getCurrent();
    const exp = provider.currentExport;
    if (panel && exp && exp.tracks.length > 0) {
      panel.render(exp, panel.currentTrackKey ?? trackKey(exp.tracks[0]));
    }
  };

  // -------------------------------------------------------------------------
  // notes-vcs local history (#103/#224): when the private notes_root tier has
  // auto-commit on, every viewer write produces an undoable commit. We cache the
  // last-seen commit sha so a write that advances it can offer a one-click Undo.
  // -------------------------------------------------------------------------

  let notesState: NotesVcsStatus | null = null;

  // refreshAfterWrite replaces refreshAndRerender at every WRITE site: it also
  // checks whether the write advanced notes_root's HEAD and, if so, offers Undo.
  // Plain/auto refresh keeps calling refreshAndRerender, so background polls
  // never pop a toast.
  const refreshAfterWrite = async (): Promise<void> => {
    // Snapshot the prior notes-vcs state (root + HEAD) before the refresh so the
    // Undo decision compares against what we last saw.
    const before = notesState;
    await refreshAndRerender();
    const after = await notesVcsStatus(runner);
    notesState = after;
    if (
      before &&
      after &&
      after.auto_commit &&
      after.is_root &&
      // SAME notes_root — a setNotesLocation change makes these differ, so we
      // never offer to Undo a *different* root's pre-existing history.
      after.notes_root === before.notes_root &&
      after.last_commit_sha &&
      after.last_commit_sha !== before.last_commit_sha &&
      // The new HEAD must sit DIRECTLY on the commit we last saw — i.e. this
      // write produced exactly one commit on top. Guards against an unrelated
      // HEAD move (external checkout/reset, a freshly selected root) looking
      // like our commit and being reverted.
      after.head_parent_sha === before.last_commit_sha
    ) {
      const sha = after.last_commit_sha;
      // Fire-and-forget: don't block the write's own success toast on the modal.
      void vscode.window
        .showInformationMessage(
          `Work Plan: saved local history (${sha}).`,
          "Undo",
        )
        .then(async (choice) => {
          if (choice !== "Undo") return;
          try {
            await notesVcsUndo(runner, sha);
            await refreshAndRerender();
            notesState = await notesVcsStatus(runner);
            vscode.window.showInformationMessage(`Work Plan: reverted ${sha}.`);
          } catch (err: unknown) {
            const msg = err instanceof CliError
              ? `Work Plan: ${err.message}`
              : `Work Plan: undo failed — ${String(err)}`;
            vscode.window.showErrorMessage(msg);
          }
        });
    }
  };

  // -------------------------------------------------------------------------
  // workPlan.refresh — reload CLI data, refresh tree, re-render panel if open.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.refresh", () => {
      refreshAndRerender().catch((err: unknown) => {
        const msg =
          err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: refresh failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      });
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.selectView — quick-pick a lens to filter tree + graph.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.selectView", async () => {
      // Ensure we have data to derive lenses from.
      if (!provider.rawExport) {
        try {
          await provider.refresh();
        } catch (err: unknown) {
          const msg =
            err instanceof CliError
              ? `Work Plan: ${err.message}`
              : `Work Plan: failed to load — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
          return;
        }
      }

      const raw = provider.rawExport;
      if (!raw) {
        vscode.window.showErrorMessage("Work Plan: No data loaded.");
        return;
      }

      const lensChoices = availableLenses(raw);
      const activeLens = provider.activeLens;

      // Build the quick-pick items, marking the active one.
      type QuickPickLensItem = vscode.QuickPickItem & { lens: Lens };
      // A repo-scope shortcut also flips the persistent autoFocusRepo setting so
      // the view's default scope tracks the user's last explicit choice.
      type ScopeItem = QuickPickLensItem & { autoFocus: boolean };
      const isLensItem = (i: vscode.QuickPickItem): i is QuickPickLensItem =>
        "lens" in i;
      const isScopeItem = (i: vscode.QuickPickItem): i is ScopeItem =>
        "autoFocus" in i;

      // Repo-scope toggle at the top (#357 follow-up): ONE state-aware entry, not
      // the full per-repo enumeration (that was noise once the tree shows every
      // repo by default). When the tree is showing all repos it offers "Focus
      // current repo"; when already focused on one repo it offers "Display all
      // repos". Folded in here rather than a dedicated toolbar icon to keep the
      // title bar uncluttered. "Focus current repo" appears only when the open
      // workspace folder maps to a configured repo.
      const focused = activeLens.kind === "repo";
      const folders = vscode.workspace.workspaceFolders;
      const focusSlug = !focused && folders
        ? await pickAutoFocusSlug(runner, folders.map(f => f.uri.fsPath))
        : null;
      const shortcuts: (QuickPickLensItem | vscode.QuickPickItem)[] = [];
      if (focused) {
        shortcuts.push({
          label: "$(list-flat) Display all repos",
          lens: { kind: "all" },
          autoFocus: false,
        } as ScopeItem);
      } else if (focusSlug) {
        shortcuts.push({
          label: "$(target) Focus current repo",
          description: focusSlug.split("/").pop() ?? focusSlug,
          lens: { kind: "repo", repo: focusSlug },
          autoFocus: true,
        } as ScopeItem);
      }
      if (shortcuts.length > 0) {
        shortcuts.push({ label: "Lenses", kind: vscode.QuickPickItemKind.Separator });
      }

      const items: QuickPickLensItem[] = lensChoices.map(c => {
        const isActive =
          c.lens.kind === activeLens.kind &&
          (c.lens.kind === "repo"
            ? activeLens.kind === "repo" && c.lens.repo === activeLens.repo
            : c.lens.kind === "milestone"
            ? activeLens.kind === "milestone" && c.lens.milestone === activeLens.milestone
            : c.lens.kind === "status"
            ? activeLens.kind === "status" && c.lens.status === activeLens.status
            : true);
        return {
          label: c.label,
          description: isActive ? "active" : undefined,
          lens: c.lens,
        };
      });

      const pick = await vscode.window.showQuickPick([...shortcuts, ...items], {
        placeHolder: "Filter the Work Plan view",
      });

      // The separator carries no lens (and isn't selectable); the guard narrows
      // the union so the shortcut + lens items are handled by the one path.
      if (!pick || !isLensItem(pick)) {
        return;
      }

      // Apply as a user choice (always wins over auto-focus). Source "user" also
      // makes the config write below a no-op re-apply rather than a fight.
      provider.setLens(pick.lens, "user");

      // A repo-scope shortcut also persists the choice as the default scope, so
      // "Focus current repo" turns auto-focus ON and "Display all repos" turns it
      // OFF. The onDidChangeConfiguration handler then sees a lens the user just
      // set ("user" source) and no-ops, so this only updates the stored default.
      if (isScopeItem(pick)) {
        await vscode.workspace
          .getConfiguration("workPlan")
          .update("autoFocusRepo", pick.autoFocus, vscode.ConfigurationTarget.Global);
      }

      // If the panel is open, re-render it from the (now-filtered) export.
      const panel = WorkPlanPanel.getCurrent();
      const filteredExp = provider.currentExport;
      if (panel && filteredExp) {
        const currentTrack = panel.currentTrackKey;
        // If the current track was filtered out, fall back to the first visible one.
        const trackStillVisible =
          currentTrack !== null &&
          filteredExp.tracks.some(t => trackKey(t) === currentTrack);
        const trackToRender = trackStillVisible
          ? currentTrack!
          : filteredExp.tracks[0] ? trackKey(filteredExp.tracks[0]) : null;
        if (trackToRender) {
          panel.render(filteredExp, trackToRender);
        } else {
          // Lens filtered out every track — replace stale content with an empty state.
          panel.renderEmpty("No tracks match the selected view.");
        }
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.openSettings — gear button: open the Settings UI scoped to this
  // extension's settings (#352), so users reach workPlan.* without searching.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.openSettings", () => {
      void vscode.commands.executeCommand(
        "workbench.action.openSettings",
        "@ext:stylusnexus.work-plan-viewer",
      );
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.sortTracks — quick-pick a sort mode for track order in the tree.
  // Sort is a display concern; currentExport / rawExport are NOT affected.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.sortTracks", async () => {
      type SortItem = vscode.QuickPickItem & { mode: TrackSort };

      const activeSort = provider.activeSort;

      const items: SortItem[] = [
        {
          label: "Default (discovery order)",
          mode: "default",
          description: activeSort === "default" ? "active" : undefined,
        },
        {
          label: "Blocked first",
          mode: "blocked",
          description: activeSort === "blocked" ? "active" : undefined,
        },
        {
          label: "Most open",
          mode: "open",
          description: activeSort === "open" ? "active" : undefined,
        },
        {
          label: "Name (A–Z)",
          mode: "name",
          description: activeSort === "name" ? "active" : undefined,
        },
      ];

      const pick = await vscode.window.showQuickPick(items, {
        placeHolder: "Sort tracks within each repo",
      });

      if (!pick) {
        return;
      }

      provider.setSort(pick.mode);
      // No panel re-render needed — sort is tree-only.
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.openTrack — open the Mermaid graph + detail webview.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.openTrack",
      (track?: Track) => {
        const exp = provider.currentExport;

        if (!exp) {
          // No data yet — kick off a refresh, then open once done.
          provider.refresh().then(() => {
            const freshExp = provider.currentExport;
            if (!freshExp) {
              vscode.window.showErrorMessage(
                "Work Plan: No data loaded. Check workPlan.cliPath in settings.",
              );
              return;
            }
            const panel = WorkPlanPanel.createOrShow(context.extensionUri);
            const selection = track
              ? trackKey(track)
              : freshExp.tracks[0] ? trackKey(freshExp.tracks[0]) : null;
            if (selection) {
              panel.render(freshExp, selection);
            }
          }).catch((err: unknown) => {
            const msg =
              err instanceof CliError
                ? `Work Plan: ${err.message}`
                : `Work Plan: failed to load — ${String(err)}`;
            vscode.window.showErrorMessage(msg);
          });
          return;
        }

        const panel = WorkPlanPanel.createOrShow(context.extensionUri);
        const selection = track
          ? trackKey(track)
          : exp.tracks[0] ? trackKey(exp.tracks[0]) : null;
        if (selection) {
          panel.render(exp, selection);
        } else {
          vscode.window.showInformationMessage(
            "Work Plan: No tracks found in export.",
          );
        }
      },
    ),
  );

  // -------------------------------------------------------------------------
  // workPlan.openTrackFile — open the track's underlying .md in an editor tab.
  // Receives a Track (from the tree context menu or the detail-panel button).
  // Distinct from workPlan.openTrack ("Show in Work Plan"), which opens the
  // detail webview, not the file (#211).
  // -------------------------------------------------------------------------

  // Stat a CLI-emitted path, then open it — revealing an already-open tab in
  // place rather than duplicating it, else opening beside in preview mode. The
  // path comes from the LOCAL CLI; on a remote-SSH/WSL/devcontainer host it may
  // not resolve, so we stat first and fail with a named, actionable message.
  // Shared by openTrackFile (#211) and openPlanFile (#285).
  const revealFileInEditor = async (uri: vscode.Uri, notFoundMsg: string): Promise<void> => {
    try {
      await vscode.workspace.fs.stat(uri);
    } catch {
      vscode.window.showErrorMessage(notFoundMsg);
      return;
    }
    try {
      const doc = await vscode.workspace.openTextDocument(uri);
      const open = vscode.window.visibleTextEditors.find(
        (e) => e.document.uri.toString() === uri.toString(),
      );
      if (open) {
        await vscode.window.showTextDocument(doc, open.viewColumn);
      } else {
        await vscode.window.showTextDocument(doc, {
          viewColumn: vscode.window.activeTextEditor
            ? vscode.ViewColumn.Beside
            : vscode.ViewColumn.Active,
          preview: true,
        });
      }
    } catch (err: unknown) {
      vscode.window.showErrorMessage(`Work Plan: failed to open file — ${String(err)}`);
    }
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.openTrackFile",
      async (node?: TrackNode): Promise<void> => {
        // Context-menu commands receive the tree NODE (TrackNode), not the bare
        // Track — the path lives at node.track.path. (workPlan.openTrack differs:
        // it's a left-click item.command that's handed node.track directly.)
        const filePath = node?.track?.path;
        if (!filePath) {
          vscode.window.showInformationMessage(
            "Work Plan: track file path not available — try refreshing the view.",
          );
          return;
        }
        await revealFileInEditor(
          vscode.Uri.file(filePath),
          `Work Plan: track file not found at ${filePath} — has it moved, ` +
            `or is it on another machine (remote/WSL)?`,
        );
      },
    ),
    // workPlan.openPlanFile — open a track's linked plan doc (#285). Receives
    // { local, rel }: the repo's local checkout path + the repo-relative doc
    // path. joinPath (not string concat) so a Windows `local` joins cleanly with
    // the POSIX `rel`.
    vscode.commands.registerCommand(
      "workPlan.openPlanFile",
      async (arg?: { local?: string; rel?: string }): Promise<void> => {
        if (!arg?.local || !arg?.rel) {
          vscode.window.showInformationMessage(
            "Work Plan: plan path not available — try refreshing the view.",
          );
          return;
        }
        const safePath = await resolveContainedFile(arg.local, arg.rel);
        if (!safePath) {
          vscode.window.showWarningMessage(
            "Work Plan: refusing to open a plan path outside its configured repository.",
          );
          return;
        }
        const uri = vscode.Uri.file(safePath);
        await revealFileInEditor(
          uri,
          `Work Plan: plan doc not found at ${uri.fsPath} — has it moved, ` +
            `or is it on another machine (remote/WSL)?`,
        );
      },
    ),
    // workPlan.fetchOpenIssues — pull a repo's open issues on demand (#303).
    // export only emits untracked for repos that HAVE tracks, so a trackless
    // repo (e.g. agent-armor) never shows its issues; this fetches them and
    // renders them as the repo's Untracked bucket. We EXCLUDE issues already
    // tracked by any of the repo's tracks (#303 fix) — the right-click works on
    // tracked repos too, and without the exclude a tracked issue like #287
    // would wrongly appear under Untracked. Accepts {repo} or a RepoNode.
    vscode.commands.registerCommand(
      "workPlan.fetchOpenIssues",
      async (arg?: { repo?: string }): Promise<void> => {
        const repo = arg?.repo;
        if (!repo || repo === "(no repo)") return;
        // Exclude already-tracked issues so they don't surface as untracked.
        // Use the RAW (unfiltered) export — a lens must not change what's tracked.
        const exclude = provider.rawExport
          ? trackedIssueNumbers(provider.rawExport, repo)
          : [];
        try {
          const res = await withWriteProgress(
            `Work Plan: fetching open issues for ${repo}…`,
            () => listRepoOpenIssues(runner, repo, exclude),
          );
          provider.setFetchedUntracked(repo, res.issues);
          // This list EXCLUDES already-tracked issues (see `exclude` above), so
          // it's the UNTRACKED open issues — not the repo's whole open-issue
          // count. Saying "no open issues" when every open issue is already
          // tracked is just false (the repo plainly has open issues); word both
          // messages as "untracked" so the count matches what the action does.
          vscode.window.showInformationMessage(
            res.issues.length > 0
              ? `Work Plan: ${res.issues.length} untracked open issue(s) in ${repo}.`
              : `Work Plan: no untracked open issues in ${repo} (all open issues are already tracked).`,
          );
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: fetch open issues failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    // GitHub sign-in path (#auth). gh auth login is INTERACTIVE (device-code /
    // browser), so it must run in a visible terminal — never a silent spawn.
    // We can't observe when the flow finishes, so we point the user at Retry.
    vscode.commands.registerCommand("workPlan.signInToGitHub", () => {
      const term = vscode.window.createTerminal({ name: "Work Plan: GitHub Sign-in" });
      term.show(true);
      term.sendText("gh auth login", true);
      vscode.window
        .showInformationMessage(
          "Work Plan: Complete the sign-in in the terminal, then click Retry to load your tracks.",
          "Retry",
        )
        .then((choice) => {
          if (choice === "Retry") {
            void vscode.commands.executeCommand("workPlan.checkGitHubAuth");
          }
        }, () => { /* ignore */ });
    }),
    // Re-probe auth + refresh (#auth) — the post-sign-in retry, also the Retry
    // links in the welcome banners. Refresh re-runs the probe, so on success the
    // banner clears and real data loads; on still-unauth we nudge, not error.
    vscode.commands.registerCommand("workPlan.checkGitHubAuth", async () => {
      await provider.refresh().catch(() => { /* surfaced elsewhere */ });
      const auth = provider.lastAuth;
      if (auth?.authenticated) {
        const who = auth.user ? ` as @${auth.user}` : "";
        vscode.window.showInformationMessage(`Work Plan: Signed in${who} — loading your tracks.`);
      } else if (auth && !auth.cliPresent) {
        vscode.window.showWarningMessage(
          "Work Plan: work-plan CLI still not found — install it in the environment VS Code runs in (e.g. inside WSL), then Retry.",
        );
      } else if (auth && !auth.ghPresent) {
        vscode.window.showWarningMessage(
          "Work Plan: GitHub CLI (gh) not found — install it, then Retry.",
        );
      } else if (auth && !auth.probeOk) {
        // Probe ran but gave no trustworthy answer — a CLI dependency/runtime
        // problem, not a sign-in state. Don't claim "still not signed in".
        const detail = auth.error ? ` (${auth.error})` : "";
        vscode.window.showWarningMessage(
          `Work Plan: couldn't verify GitHub sign-in — the work-plan CLI didn't return a result${detail}. Check its dependencies (gh, git, yq), then Retry.`,
        );
      } else {
        vscode.window.showInformationMessage(
          "Work Plan: Still not signed in — finish the flow in the terminal, then Retry.",
        );
      }
    }),
    // Open the gh install docs (#auth) — the fix for the "gh not found" state.
    vscode.commands.registerCommand("workPlan.openGhInstallDocs", () => {
      vscode.env.openExternal(vscode.Uri.parse("https://cli.github.com")).then(
        undefined, () => { /* ignore */ },
      );
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.openIssue — open a GitHub issue in the external browser.
  // Accepts { repo: string, number: number } (from tree node or webview message).
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.openIssue",
      (arg?: { repo?: string; number?: number } | number) => {
        // Support legacy numeric call shape (pre-Task-8 stubs passed a bare number).
        let repo: string | undefined;
        let issueNumber: number | undefined;

        if (typeof arg === "number") {
          issueNumber = arg;
        } else if (arg && typeof arg === "object") {
          repo = arg.repo;
          issueNumber = arg.number;
        }

        if (!issueNumber) {
          vscode.window.showInformationMessage("Work Plan: No issue number provided.");
          return;
        }

        // If repo is missing or malformed, we can't safely form a URL.
        // The owner/name guard kills open-redirect via "../evil" paths.
        if (!repo || !/^[\w.-]+\/[\w.-]+$/.test(repo)) {
          vscode.window.showInformationMessage(
            `Work Plan: Cannot open issue #${issueNumber} — repo not specified or invalid.`,
          );
          return;
        }

        const url = `https://github.com/${repo}/issues/${issueNumber}`;
        vscode.env.openExternal(vscode.Uri.parse(url)).then(
          undefined,
          (err: unknown) => {
            vscode.window.showErrorMessage(
              `Work Plan: Failed to open issue — ${String(err)}`,
            );
          },
        );
      },
    ),
    // workPlan.closeIssue (#305) — one of two GitHub-mutating actions (the other is issueInProgress). Accepts an
    // untracked-issue NODE ({repo, issue:{number,title}}) or a detail-panel
    // {repo, number, title}. Flow: reason pick → optional comment → mandatory
    // "writes to GitHub, can't be undone" modal (EVERY close) → executeWrite.
    vscode.commands.registerCommand(
      "workPlan.closeIssue",
      async (arg?: { repo?: string; number?: number; title?: string; issue?: Issue }) => {
        const repo = arg?.repo;
        const number = arg?.number ?? arg?.issue?.number;
        const title = arg?.title ?? arg?.issue?.title ?? (number ? `#${number}` : "");
        if (!repo || !number) {
          vscode.window.showInformationMessage("Work Plan: no issue to close.");
          return;
        }

        const pick = await vscode.window.showQuickPick(
          [
            { label: "$(pass-filled) Completed", reason: "completed" as const, description: "Work is done (default)" },
            { label: "$(circle-slash) Not planned", reason: "not_planned" as const, description: "Won't do / out of scope" },
          ],
          { title: `Close #${number} on GitHub`, placeHolder: "Close reason" },
        );
        if (!pick) return;

        const comment = await vscode.window.showInputBox({
          title: `Closing comment for #${number} (optional)`,
          placeHolder: "Closed via dev-branch merge (#PR) — leave blank for no comment",
          ignoreFocusOut: true,
        });
        if (comment === undefined) return; // Escape cancels the whole operation

        const ok = await vscode.window.showWarningMessage(
          `Close issue #${number} "${title}" on GitHub?\n\nThis writes to GitHub — it cannot be undone from the extension.`,
          { modal: true },
          "Close on GitHub",
        );
        if (ok !== "Close on GitHub") return;

        try {
          const outcome = await withWriteProgress(
            `Work Plan: closing #${number} on GitHub…`,
            () => executeWrite(
              runner,
              { kind: "closeIssue", repo, number, reason: pick.reason, comment: comment || undefined },
              confirmPublicWrite,
            ),
          );
          if (outcome.status === "written") {
            await refreshAfterWrite();
            vscode.window.showInformationMessage(
              comment
                ? `Work Plan: closed #${number} on GitHub with comment.`
                : `Work Plan: closed #${number} on GitHub.`,
            );
          } else {
            vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: close failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    // workPlan.toggleInProgress (#271 B4) — mark or clear the work-plan:in-progress
    // label on an issue via the detail-webview toggle button. Accepts {repo, number,
    // clear}. Routes through executeWrite so the public-repo confirm-token flow is
    // reused (no extra modal — unlike closeIssue, this is reversible and low-risk).
    vscode.commands.registerCommand(
      "workPlan.toggleInProgress",
      async (arg?: { repo?: string; number?: number; clear?: boolean }) => {
        const repo = arg?.repo;
        const number = arg?.number;
        const clear = arg?.clear ?? false;
        if (!repo || !number) {
          vscode.window.showInformationMessage("Work Plan: no issue to update.");
          return;
        }

        try {
          const outcome = await withWriteProgress(
            `Work Plan: ${clear ? "clearing" : "marking"} #${number} in-progress…`,
            () => executeWrite(
              runner,
              { kind: "issueInProgress", repo, number, clear },
              confirmPublicWrite,
            ),
          );
          if (outcome.status === "written") {
            await refreshAfterWrite();
            vscode.window.showInformationMessage(
              clear
                ? `Work Plan: cleared in-progress on #${number}.`
                : `Work Plan: marked #${number} in-progress.`,
            );
          } else {
            vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: toggle in-progress failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
  );

  // -------------------------------------------------------------------------
  // Write command helpers (shared across all five write verbs)
  // -------------------------------------------------------------------------

  // Confirm prompt shown when the target repo is public.
  const confirmPublicWrite: ConfirmPrompt = async (reason: string): Promise<"writeAnyway" | "cancel"> => {
    const choice = await vscode.window.showWarningMessage(
      reason,
      { modal: true },
      "Write anyway",
      "Keep private",
    );
    return choice === "Write anyway" ? "writeAnyway" : "cancel";
  };

  // Wrap a write in an unobtrusive status-bar progress spinner so every write
  // verb gives "working…" feedback instead of a silent UI freeze. Covers only
  // the executeWrite spawn — the interactive prompts run before it, and the tree
  // reload that follows shows its own view-located progress bar. The three slow
  // verbs (refresh-md, reconcile, hygiene) keep their Notification-located bars.
  const withWriteProgress = <T>(title: string, task: () => Promise<T>): Thenable<T> =>
    vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title },
      task,
    );

  // Webview drag-move goes through the same audited write path as workPlan.move:
  // executeWrite + the public-repo confirm modal (#197). No ad-hoc spawn in the panel.
  WorkPlanPanel.setMoveHandler(async (issue, fromTrack, toTrack, repoKey) => {
    try {
      const outcome: WriteOutcome = await withWriteProgress(
        `Work Plan: moving #${issue} to ${toTrack}…`,
        () => executeWrite(
          runner,
          { kind: "move", fromTrack, toTrack, repoKey, issue },
          confirmPublicWrite,
        ),
      );
      if (outcome.status === "written") {
        await refreshAfterWrite();
        vscode.window.showInformationMessage(
          `Work Plan: moved #${issue} from ${fromTrack} to ${toTrack}`,
        );
      } else {
        vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
      }
    } catch (err: unknown) {
      const msg = err instanceof CliError
        ? `Work Plan: ${err.message}`
        : `Work Plan: move failed — ${String(err)}`;
      vscode.window.showErrorMessage(msg);
    }
  });

  // Clicking the milestone filter control in the detail panel filters the whole
  // view by that milestone (#218) — same milestone lens the Select View quick-pick
  // applies. Re-render the panel from the now-filtered export, falling back to the
  // first visible track if the current one was filtered out. The success toast
  // carries a "Clear filter" action so the filter is reversible at the point of
  // action, not only from the title-bar Select View (#249).
  const rerenderPanelForLens = (): void => {
    const panel = WorkPlanPanel.getCurrent();
    const exp = provider.currentExport;
    if (!panel || !exp) return;
    const currentTrack = panel.currentTrackKey;
    const trackStillVisible =
      currentTrack !== null && exp.tracks.some(t => trackKey(t) === currentTrack);
    const trackToRender = trackStillVisible
      ? currentTrack!
      : exp.tracks[0] ? trackKey(exp.tracks[0]) : null;
    if (trackToRender) {
      panel.render(exp, trackToRender);
    } else {
      panel.renderEmpty("No tracks match the selected view.");
    }
  };

  WorkPlanPanel.setFilterHandler((milestone: string) => {
    provider.setLens({ kind: "milestone", milestone });
    rerenderPanelForLens();
    void vscode.window
      .showInformationMessage(
        `Work Plan: filtered the view to milestone "${milestone}".`,
        "Clear filter",
      )
      .then((choice) => {
        if (choice === "Clear filter") {
          provider.setLens({ kind: "all" });
          rerenderPanelForLens();
        }
      }, () => { /* ignore */ });
  });

  // Output channel for reconcile draft output (created once; disposed via subscriptions).
  const outputChannel = vscode.window.createOutputChannel("Work Plan");
  context.subscriptions.push(outputChannel);

  // -------------------------------------------------------------------------
  // Doctor config-drift status bar (#439): a status-bar item surfaces config
  // findings (e.g. renamed/redirected GitHub repos) found by `doctor --json`.
  // Convenience signal only — hidden whenever there's nothing to report or
  // the scan itself fails for any reason (see doctorScan's null-on-failure
  // contract in cli.ts). Populated by the activation-time scan below.
  // -------------------------------------------------------------------------

  const doctorStatusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left);
  doctorStatusItem.command = "workPlan.showDoctorReport";
  context.subscriptions.push(doctorStatusItem);
  let lastDoctorFindings: DoctorFinding[] = [];

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.showDoctorReport", () => {
      outputChannel.clear();
      outputChannel.appendLine("Work Plan: config-drift report");
      for (const f of lastDoctorFindings) {
        outputChannel.appendLine(`  • ${f.message}`);
      }
      outputChannel.show();
    }),
  );

  const repoKeyForTrack = (track: Track): string | undefined =>
    track.folder ?? track.repo ?? undefined;

  // Resolve the complete track identity: use the context-menu node's raw Track
  // or retain it on a palette QuickPick item. A name alone is not unique across
  // configured repos (#430).
  const resolveTrack = async (node?: TrackNode): Promise<Track | undefined> => {
    if (node?.track) {
      return node.track;
    }
    const exp = provider.currentExport;
    if (!exp || exp.tracks.length === 0) {
      vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
      return undefined;
    }
    type TrackItem = vscode.QuickPickItem & { track: Track };
    const picked = await vscode.window.showQuickPick<TrackItem>(
      exp.tracks.map(track => ({
        label: track.name,
        description: repoKeyForTrack(track),
        track,
      })),
      { placeHolder: "Select a track", matchOnDescription: true },
    );
    return picked?.track;
  };

  // -------------------------------------------------------------------------
  // workPlan.editFields — edit a named field on a track (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.editFields", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        type FieldItem = vscode.QuickPickItem & { field: string };
        const fieldPick = await vscode.window.showQuickPick<FieldItem>(
          [
            { label: "status",              field: "status" },
            { label: "launch_priority",     field: "launch_priority" },
            { label: "milestone_alignment", field: "milestone_alignment" },
            { label: "blockers",            field: "blockers" },
            { label: "next_up",             field: "next_up" },
          ],
          { placeHolder: "Field to edit" },
        );
        if (!fieldPick) return;

        const field = fieldPick.field;
        let value: string | undefined;

        if (field === "status") {
          value = await vscode.window.showQuickPick(
            ["active", "in-progress", "blocked", "parked", "shipped", "abandoned"],
            { placeHolder: "New status" },
          );
        } else if (field === "blockers" || field === "next_up") {
          value = await vscode.window.showInputBox({
            prompt: `${field} — comma-separated issue numbers (empty to clear)`,
            validateInput: (v) => {
              if (v.trim() === "") return null; // empty is valid (clear)
              if (/^\s*\d+(\s*,\s*\d+)*\s*$/.test(v)) return null;
              return "Enter comma-separated issue numbers, e.g. 42,87";
            },
          });
          if (value !== undefined) {
            // Normalize: strip spaces, trim
            value = value.trim() === "" ? "" : value.split(",").map(s => s.trim()).join(",");
          }
        } else if (field === "launch_priority") {
          // Constrain to P0–P3 — same affordance as New Track (#213), so the
          // edit path can't write arbitrary priority text.
          value = await vscode.window.showQuickPick(
            ["P0", "P1", "P2", "P3"],
            { placeHolder: "New launch_priority" },
          );
        } else if (field === "milestone_alignment") {
          // Suggest milestones already present in the export, with an escape
          // hatch for a new value and a clear option (#213). Read from the RAW
          // export so an active lens can't narrow the suggestions.
          const milestoneExp = provider.rawExport ?? provider.currentExport;
          const TYPE_NEW = "$(pencil) Type a new milestone…";
          const CLEAR = "$(x) Clear milestone";
          const existing = milestoneExp ? collectMilestones(milestoneExp) : [];
          const picked = await vscode.window.showQuickPick(
            [TYPE_NEW, CLEAR, ...existing],
            { placeHolder: "New milestone_alignment" },
          );
          if (picked === undefined) return; // cancelled
          if (picked === CLEAR) {
            value = "";
          } else if (picked === TYPE_NEW) {
            const raw = await vscode.window.showInputBox({ prompt: "New milestone (e.g. v1.0.0)" });
            if (raw === undefined) return; // cancelled
            value = raw.trim();
          } else {
            value = picked;
          }
        } else {
          value = await vscode.window.showInputBox({ prompt: `New value for ${field}` });
        }

        if (value === undefined) return; // cancelled

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: setting ${field} on ${track}…`,
          () => executeWrite(
            runner,
            { kind: "editFields", track, repoKey, fields: { [field]: value } },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: set ${field} on ${track}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: edit-fields failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.setNext — set next-up via a handoff. Unlike Edit Track Fields →
  // next_up (which only writes the frontmatter field), this runs `handoff
  // --set-next`, so it ALSO appends a session-log entry and refreshes the body
  // status table. Surfaced as "Set Next-Up & Log Session" to signal that.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.setNext", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        // Pick next-up from the track's OPEN issues in priority order. Order is
        // captured by ITERATIVE single-selects: a multi-select QuickPick returns
        // items in display order, not click order, so it can't express a
        // deliberate priority sequence (#212). Closed issues are excluded —
        // next-up is forward-looking.
        const exp = provider.rawExport ?? provider.currentExport;
        if (!exp || exp.tracks.length === 0) {
          vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
          return;
        }
        const openItems = buildIssuePickItems(trackObj.issues, { includeClosed: false });
        if (openItems.length === 0) {
          vscode.window.showInformationMessage(`Work Plan: ${track} has no open issues to queue.`);
          return;
        }

        const DONE_SENTINEL = -1;
        const doneItem = { label: "$(check) Done", description: "finish selection", issueNumber: DONE_SENTINEL };
        const ordered: number[] = [];
        for (;;) {
          const remaining = openItems.filter(it => !ordered.includes(it.issueNumber));
          if (remaining.length === 0) break; // everything queued
          const soFar = ordered.length
            ? `Next-up so far: ${ordered.map(n => `#${n}`).join(", ")} — `
            : "";
          const pick = await vscode.window.showQuickPick(
            [doneItem, ...remaining],
            {
              placeHolder: `${soFar}pick #${ordered.length + 1} (or Done)`,
              matchOnDescription: true,
              ignoreFocusOut: true,
            },
          );
          if (!pick) return; // Escape → cancel the whole op (no write, no session log)
          if (pick.issueNumber === DONE_SENTINEL) break;
          ordered.push(pick.issueNumber);
        }
        // Done with nothing chosen → cancel, so we never silently wipe next-up.
        if (ordered.length === 0) return;
        const issues = ordered;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: setting next-up on ${track}…`,
          () => executeWrite(
            runner,
            { kind: "setNext", track, repoKey, issues },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: set next-up on ${track} (session logged)`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: set-next failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.autoNext — native auto-next picker (#274). Reimplements the CLI's
  // interactive `--auto-next` (a TTY prompt that no-ops under VS Code's non-TTY
  // stdin, #183): read the algorithmic suggestion via the read-only
  // `handoff --suggest-next` (no write), let the user uncheck candidates in a
  // multi-select QuickPick (display order = the CLI's priority order, so the
  // sequence is preserved), then write via the audited `setNext` path.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.autoNext", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        const suggestion = await withWriteProgress(
          `Work Plan: computing next-up suggestion for ${track}…`,
          () => suggestNextUp(runner, track, repoKey),
        );

        if (suggestion.suggested.length === 0) {
          const why = suggestion.error
            ? ` (${suggestion.error})`
            : suggestion.skipped.length
              ? ` — ${suggestion.skipped.length} candidate(s) already queued on a sibling track`
              : "";
          vscode.window.showInformationMessage(
            `Work Plan: no auto next-up suggestion for ${track}${why}.`,
          );
          return;
        }

        type Cand = vscode.QuickPickItem & { number: number };
        const items: Cand[] = suggestion.suggested.map((s) => ({
          label: `#${s.number}  ${s.title}`,
          description: [s.priority, s.milestone].filter(Boolean).join(" · "),
          number: s.number,
          picked: true,
        }));
        const skippedNote = suggestion.skipped.length
          ? ` · ${suggestion.skipped.length} skipped (queued on a sibling)`
          : "";
        const picked = await vscode.window.showQuickPick(items, {
          canPickMany: true,
          ignoreFocusOut: true,
          placeHolder: `Auto next-up for ${track}${skippedNote} — uncheck any to drop, Enter to apply`,
        });
        if (!picked) return; // Escape → cancel, no write
        if (picked.length === 0) {
          vscode.window.showInformationMessage("Work Plan: nothing selected — next-up unchanged.");
          return;
        }
        // Multi-select returns items in DISPLAY order, which here IS the CLI's
        // priority order — so the queue keeps the algorithm's sequence (#274).
        const issues = picked.map((p) => p.number);

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: setting next-up on ${track}…`,
          () => executeWrite(
            runner,
            { kind: "setNext", track, repoKey, issues },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: set next-up on ${track} (session logged)`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: auto next-up failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.setNextUpPreset — set per-track next-up ordering preset (#326)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.setNextUpPreset", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        // Resolve the full track object so we can surface the current preset and auto state.
        const currentPreset = trackObj.next_up_preset;
        const currentAuto = trackObj.next_up_auto ?? false;

        type PresetItem = vscode.QuickPickItem & {
          preset?: string;
          clear?: boolean;
          custom?: boolean;
          auto?: "on" | "off";
        };

        // Auto toggle items at the top (#338), then a separator, then presets.
        const autoOnItem: PresetItem = {
          label: "$(sync) Auto next-up: ON",
          description: "rank automatically with the preset",
          auto: "on",
        };
        const autoOffItem: PresetItem = {
          label: "$(circle-slash) Auto next-up: OFF",
          description: "keep a hand-curated next-up list",
          auto: "off",
        };
        // Mark the current auto state with a ✓.
        if (currentAuto) {
          autoOnItem.description = `✓ current · ${autoOnItem.description ?? ""}`.trim();
        } else {
          autoOffItem.description = `✓ current · ${autoOffItem.description ?? ""}`.trim();
        }

        const separator: PresetItem = {
          label: "",
          kind: vscode.QuickPickItemKind.Separator,
        };

        const presets: PresetItem[] = [
          autoOnItem,
          autoOffItem,
          separator,
          {
            label: "$(symbol-event) Flow (default)",
            description: "preset: flow",
            preset: "flow",
          },
          {
            label: "$(list-ordered) Priority-driven",
            description: "preset: priority-driven",
            preset: "priority-driven",
          },
          {
            label: "$(inbox) Backlog / maintenance",
            description: "preset: backlog",
            preset: "backlog",
          },
          {
            label: "$(tools) Custom… (advanced — edit the track file)",
            description: "set next_up_order in frontmatter manually",
            custom: true,
          },
          {
            label: "$(discard) Clear (use default)",
            description: "remove any set preset (falls back to flow)",
            clear: true,
          },
        ];

        // Mark the active preset with a ✓ description prefix.
        if (currentPreset) {
          for (const item of presets) {
            if (item.preset === currentPreset) {
              item.description = `✓ current · ${item.description ?? ""}`.trim();
            }
          }
        }

        const pick = await vscode.window.showQuickPick<PresetItem>(presets, {
          placeHolder: currentPreset
            ? `Current: ${currentPreset} — pick a new preset`
            : "Pick a next-up ordering preset",
        });
        if (!pick) return;

        // Custom is not a CLI write — instruct the user to edit the file.
        if (pick.custom) {
          const msg =
            `To use a custom order, edit the track's frontmatter and set:\n` +
            `  next_up_order:\n    preset: custom\n    order: [<issue-numbers>]`;
          const action = trackObj?.path
            ? await vscode.window.showInformationMessage(msg, "Open Track File")
            : await vscode.window.showInformationMessage(msg);
          if (action === "Open Track File") {
            void vscode.commands.executeCommand("workPlan.openTrackFile", { track: trackObj });
          }
          return;
        }

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: setting next-up preset on ${track}…`,
          () => executeWrite(
            runner,
            { kind: "setNextUpPreset", track, repoKey, preset: pick.preset, clear: pick.clear, auto: pick.auto },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          let label: string;
          if (pick.auto) {
            label = `auto set to ${pick.auto}`;
          } else if (pick.clear) {
            label = "cleared (using default)";
          } else {
            label = `set to ${pick.preset}`;
          }
          vscode.window.showInformationMessage(`Work Plan: next-up preset ${label} on ${track}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: set-next-up-preset failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.refreshMd — refresh a track's body markdown (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.refreshMd", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Work Plan: refreshing ${track}…`,
            cancellable: false,
          },
          async () => {
            const outcome: WriteOutcome = await executeWrite(
              runner,
              { kind: "refresh", track, repoKey },
              confirmPublicWrite,
            );

            if (outcome.status === "written") {
              await refreshAfterWrite();
              vscode.window.showInformationMessage(`Work Plan: refreshed ${track}`);
            } else {
              vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
            }
          },
        );
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: refresh-md failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.reconcile — draft label-drift preview (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.reconcile", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: reconciling ${track} (draft)…`,
          () => executeWrite(runner, { kind: "reconcileDraft", track, repoKey }, confirmPublicWrite),
        );

        if (outcome.status !== "written") {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          return;
        }

        outputChannel.clear();
        outputChannel.append(outcome.stdout);
        outputChannel.show(true);

        // Offer a one-click apply of the drift the draft just showed (#221)
        // instead of forcing a trip to the terminal. The message resolves only
        // once the draft progress has cleared, so the spinner doesn't linger
        // while we wait for the user's choice. The apply re-runs the analysis
        // non-interactively (`--yes`) and self-skips MOVEs into PUBLIC tracks.
        const action = await vscode.window.showInformationMessage(
          "Work Plan: label-drift preview (draft) — see the Work Plan output channel.",
          "Apply reconcile",
        );
        if (action !== "Apply reconcile") return;

        const applied: WriteOutcome = await withWriteProgress(
          `Work Plan: applying reconcile to ${track}…`,
          () => executeWrite(runner, { kind: "reconcileApply", track, repoKey }, confirmPublicWrite),
        );

        if (applied.status === "written") {
          outputChannel.clear();
          outputChannel.append(applied.stdout);
          outputChannel.show(true);
          await refreshAfterWrite();
          vscode.window.showInformationMessage(
            `Work Plan: reconcile applied to ${track} — see the Work Plan output channel.`,
          );
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: reconcile failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.slot — slot an issue into a track (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.slot", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        // Resolve the track's repo + current issues so we can offer the repo's
        // OPEN issues as a pick-list, excluding ones already in the track (#282).
        const repo = trackObj.repo;

        let issue: number | undefined;
        if (repo) {
          const alreadyIn = trackObj!.issues.map(i => i.number);
          let candidates: Issue[] = [];
          try {
            const res = await vscode.window.withProgress(
              { location: vscode.ProgressLocation.Window, title: `Work Plan: fetching open issues in ${repo}…` },
              () => listRepoOpenIssues(runner, repo, alreadyIn),
            );
            candidates = res.issues;
          } catch {
            // Fetch failed (offline, gh hiccup) — fall through to manual entry
            // rather than blocking the whole command on the pick-list.
            candidates = [];
          }

          if (candidates.length > 0) {
            const MANUAL = -1;
            const manualItem = { label: "$(edit) Enter an issue number…", description: "not in the list", issueNumber: MANUAL };
            const picked = await vscode.window.showQuickPick(
              [manualItem, ...buildIssuePickItems(candidates)],
              {
                placeHolder: `Select an open issue to add to ${track}`,
                matchOnDescription: true,
                ignoreFocusOut: true,
              },
            );
            if (!picked) return; // cancelled
            if (picked.issueNumber !== MANUAL) issue = picked.issueNumber;
          }
        }

        // Manual entry: chosen explicitly, no candidates to show, or no repo.
        if (issue === undefined) {
          const raw = await vscode.window.showInputBox({
            prompt: `Issue number to slot into ${track}`,
            validateInput: (v) => {
              if (/^\d+$/.test(v) && parseInt(v, 10) > 0) return null;
              return "Enter a positive integer issue number (e.g. 42)";
            },
          });
          if (raw === undefined) return; // cancelled
          issue = parseInt(raw, 10);
        }

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: adding #${issue} to ${track}…`,
          () => executeWrite(
            runner,
            { kind: "slot", track, repoKey, issue },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: added #${issue} to ${track}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: slot failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.move — move an issue from one track to another (context menu)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.move", async (node?: TrackNode) => {
      try {
        const srcTrack = await resolveTrack(node);
        if (!srcTrack) return;
        const fromTrack = srcTrack.name;
        const repoKey = repoKeyForTrack(srcTrack);

        // Load the export FIRST so we can offer the source track's issues as a
        // pick-list instead of asking the user to retype a number (#212).
        const exp = provider.rawExport ?? provider.currentExport;
        if (!exp || exp.tracks.length === 0) {
          vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
          return;
        }

        // Pick the issue from the known list. Closed issues are shown (muted) so
        // a "closed it in the wrong track" correction is still possible.
        if (srcTrack.issues.length === 0) {
          vscode.window.showInformationMessage(`Work Plan: ${fromTrack} has no issues to move.`);
          return;
        }
        const picked = await vscode.window.showQuickPick(
          buildIssuePickItems(srcTrack.issues, { includeClosed: true }),
          {
            placeHolder: `Select an issue to move from ${fromTrack}`,
            matchOnDescription: true,
            ignoreFocusOut: true,
          },
        );
        if (!picked) return; // cancelled
        const issue = picked.issueNumber;

        // Destination candidates: other active tracks in the same repo.
        const candidates = exp.tracks.filter(
          t => t.name !== fromTrack && t.repo === srcTrack.repo,
        );
        if (candidates.length === 0) {
          vscode.window.showInformationMessage(
            `Work Plan: No other tracks in ${srcTrack.repo} to move to.`,
          );
          return;
        }

        const toTrack = await vscode.window.showQuickPick(
          candidates.map(t => t.name),
          { placeHolder: `Move #${issue} to which track?`, ignoreFocusOut: true },
        );
        if (!toTrack) return; // cancelled

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: moving #${issue} from ${fromTrack} to ${toTrack}…`,
          () => executeWrite(
            runner,
            { kind: "move", fromTrack, toTrack, repoKey, issue },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(
            `Work Plan: moved #${issue} from ${fromTrack} to ${toTrack}`,
          );
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: move failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.slotUntracked — slot an untracked issue into a track (context menu only)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.slotUntracked", async (node?: UntrackedIssueNode) => {
      if (!node || node.kind !== "untrackedIssue") {
        return;
      }

      try {
        const issue = node.issue.number;

        // Build the track list from the RAW (unfiltered) export, so an active
        // lens doesn't hide otherwise-valid target tracks from the picker.
        // Prefer tracks whose repo matches the issue's repo; fall back to all.
        const exp = provider.rawExport ?? provider.currentExport;
        if (!exp || exp.tracks.length === 0) {
          vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
          return;
        }

        const sameRepoTracks = exp.tracks.filter(t => t.repo === node.repo);
        const candidateTracks = sameRepoTracks.length > 0 ? sameRepoTracks : exp.tracks;

        type TrackItem = vscode.QuickPickItem & { track: Track };
        const pickedTrack = await vscode.window.showQuickPick<TrackItem>(
          candidateTracks.map(track => ({
            label: track.name,
            description: repoKeyForTrack(track),
            track,
          })),
          { placeHolder: `Slot #${issue} into a track`, matchOnDescription: true },
        );
        if (!pickedTrack) return; // cancelled
        const track = pickedTrack.track.name;
        const repoKey = repoKeyForTrack(pickedTrack.track);

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: adding #${issue} to ${track}…`,
          () => executeWrite(
            runner,
            { kind: "slot", track, repoKey, issue },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: added #${issue} to ${track}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: slot-untracked failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.batchSlotUntracked — batch-slot untracked issues into a track (context menu on UntrackedGroup)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.batchSlotUntracked", async (node?: UntrackedGroupNode) => {
      if (!node || node.kind !== "untrackedGroup") {
        return;
      }

      try {
        // Multi-select quick-pick of untracked issues.
        type IssueItem = vscode.QuickPickItem & { issueNumber: number };
        const issueItems: IssueItem[] = node.issues.map(issue => ({
          label: `#${issue.number}  ${issue.title}`,
          issueNumber: issue.number,
        }));

        const picks = await vscode.window.showQuickPick(issueItems, {
          canPickMany: true,
          placeHolder: `Select untracked issues to slot (${node.repo})`,
        });
        if (!picks || picks.length === 0) return; // cancelled

        const issueNumbers = picks.map(p => p.issueNumber);

        // Build the track list from the RAW (unfiltered) export.
        const exp = provider.rawExport ?? provider.currentExport;
        if (!exp || exp.tracks.length === 0) {
          vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
          return;
        }

        const sameRepoTracks = exp.tracks.filter(t => t.repo === node.repo);
        const candidateTracks = sameRepoTracks.length > 0 ? sameRepoTracks : exp.tracks;

        type TrackItem = vscode.QuickPickItem & { track: Track };
        const pickedTrack = await vscode.window.showQuickPick<TrackItem>(
          candidateTracks.map(track => ({
            label: track.name,
            description: repoKeyForTrack(track),
            track,
          })),
          {
            placeHolder: `Slot ${issueNumbers.length} issue(s) into a track`,
            matchOnDescription: true,
          },
        );
        if (!pickedTrack) return; // cancelled
        const track = pickedTrack.track.name;
        const repoKey = repoKeyForTrack(pickedTrack.track);

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: adding ${issueNumbers.length} issue(s) to ${track}…`,
          () => executeWrite(
            runner,
            { kind: "batchSlot", track, repoKey, issues: issueNumbers },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: added ${issueNumbers.length} issue(s) to ${track}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: batch-slot-untracked failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // Auto-slot suggestions (#241): offer to slot untracked issues into tracks.
  //
  // Flow: Suggest Tracks runs `auto-triage --json` → stores {batchId, answersPath}
  // for the repo + relays the prompt → a Claude session writes answers to
  // answersPath → an fs.watch fires → we re-read + bucket (suggestions.ts) and
  // store on the provider → the tree shows Suggested / Needs review sub-buckets.
  // Accept computes a CAS fingerprint (#241) of the target track's current issues
  // and slots with --expect, branching on the staleness/rebase outcome.
  // -------------------------------------------------------------------------

  // Per-repo answers-file paths (the CLI-emitted absolute path, used verbatim)
  // and their live fs.watchers, so a repo re-scanned mid-session swaps watchers
  // cleanly and all watchers tear down on deactivation.
  const autoSlotAnswersPath = new Map<string, string>();
  const autoSlotWatchers = new Map<string, fs.FSWatcher>();
  // Per-repo debounce timers — editors write the answers file in several syncs,
  // so coalesce a burst of change events into one re-read (~300ms).
  const autoSlotDebounce = new Map<string, ReturnType<typeof setTimeout>>();

  const autoSlotThreshold = (): number => {
    const raw = vscode.workspace
      .getConfiguration("workPlan")
      .get<number>("autoSlotConfidenceThreshold", 0.7);
    // Clamp to [0,1] so a hand-edited setting can't invert the buckets.
    return Math.min(1, Math.max(0, raw));
  };

  // Dismissed suggestions (#241): per-repo, per-issue, persisted in workspaceState
  // so a dismissed issue stays dropped to plain untracked across reloads. Keyed
  // `autoSlot.dismissed.<repo>.<issueNumber>`.
  const dismissKey = (repo: string, issueNumber: number): string =>
    `autoSlot.dismissed.${repo}.${issueNumber}`;
  const isDismissed = (repo: string, issueNumber: number): boolean =>
    context.workspaceState.get<boolean>(dismissKey(repo, issueNumber), false);

  // Re-read a repo's answers file, bucket it, and push onto the provider. Safe to
  // call when the file doesn't exist yet (cold) — readSuggestions tolerates it.
  const readAndStoreSuggestions = (repo: string): void => {
    const path = autoSlotAnswersPath.get(repo);
    const batchId = provider.getBatchId(repo);
    if (!path || !batchId) return;
    const buckets = readSuggestions(
      path,
      batchId,
      autoSlotThreshold(),
      (issueNumber) => isDismissed(repo, issueNumber),
    );
    if (buckets.batchMismatch) {
      // A stale answers file from a prior scan — surface it once rather than
      // silently applying nothing.
      vscode.window.showWarningMessage(
        `Work Plan: the suggestions file for ${repo} is from a different scan — re-run Suggest Tracks.`,
      );
    }
    provider.setSuggestions(repo, buckets);
  };

  // Arm (or re-arm) an fs.watch on a repo's answers file. fs.watch fires on the
  // file's directory entry; we debounce and re-read. The cache dir is created by
  // the CLI before it prints answers_path, so the parent exists.
  const watchAnswers = (repo: string, path: string): void => {
    autoSlotWatchers.get(repo)?.close();
    autoSlotAnswersPath.set(repo, path);
    try {
      const watcher = fs.watch(path, { persistent: false }, () => {
        const prior = autoSlotDebounce.get(repo);
        if (prior) clearTimeout(prior);
        autoSlotDebounce.set(
          repo,
          setTimeout(() => {
            autoSlotDebounce.delete(repo);
            readAndStoreSuggestions(repo);
          }, 300),
        );
      });
      watcher.on("error", () => { /* file vanished/renamed — ignore */ });
      autoSlotWatchers.set(repo, watcher);
    } catch {
      // The file may not exist yet (Claude hasn't written it). fs.watch on a
      // missing path throws; the cold-open read below still picks it up once it
      // lands on the next Suggest Tracks / reload. Best-effort — never fatal.
    }
    // Cold read: pick up an answers file already on disk from a prior session.
    readAndStoreSuggestions(repo);
  };

  // Tear down every answers-file watcher + pending debounce on deactivation.
  context.subscriptions.push({
    dispose: () => {
      for (const w of autoSlotWatchers.values()) w.close();
      autoSlotWatchers.clear();
      for (const t of autoSlotDebounce.values()) clearTimeout(t);
      autoSlotDebounce.clear();
    },
  });

  // Re-bucket all repos when the threshold flips (it shifts suggested↔needsReview).
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("workPlan.autoSlotConfidenceThreshold")) {
        for (const repo of autoSlotAnswersPath.keys()) readAndStoreSuggestions(repo);
      }
    }),
  );

  // Pick the repo for a palette invocation of Suggest Tracks: the configured repos
  // (with a folder key — the --repo arg) drawn from the raw export.
  const pickAutoSlotRepo = async (): Promise<{ repo: string; folder: string } | undefined> => {
    const raw = provider.rawExport;
    const choices = (raw?.repos ?? [])
      .filter((r): r is typeof r & { repo: string; folder: string } =>
        typeof r.repo === "string" && r.repo !== "" && typeof r.folder === "string" && r.folder !== "")
      .map(r => ({ label: r.repo, repo: r.repo, folder: r.folder }));
    if (choices.length === 0) {
      vscode.window.showInformationMessage("Work Plan: no configured repos to triage — Add Repo first.");
      return undefined;
    }
    if (choices.length === 1) return { repo: choices[0].repo, folder: choices[0].folder };
    const pick = await vscode.window.showQuickPick(choices, {
      placeHolder: "Suggest tracks for which repo?",
    });
    return pick ? { repo: pick.repo, folder: pick.folder } : undefined;
  };

  // Shared scan driver for both Suggest Tracks variants. heuristic=false runs the
  // LLM path (relays a prompt for a Claude session to answer); heuristic=true runs
  // the offline scorer (#373) — the CLI writes the answers file itself, so
  // suggestions appear immediately via the watcher's cold read, no session needed.
  const runSuggestScan = async (
    node: { repo?: string; folder?: string | null } | undefined,
    heuristic: boolean,
  ): Promise<void> => {
    try {
      let repo = typeof node?.repo === "string" ? node.repo : undefined;
      let folder = typeof node?.folder === "string" ? node.folder : undefined;
      if (repo && !folder) {
        folder = provider.rawExport?.repos?.find(r => r.repo === repo)?.folder ?? undefined;
      }
      if (!repo || !folder) {
        const picked = await pickAutoSlotRepo();
        if (!picked) return;
        repo = picked.repo;
        folder = picked.folder;
      }

      const scan = await withWriteProgress(
        `Work Plan: scanning ${repo} for untracked issues…`,
        () => autoTriageScan(runner, folder!, { heuristic }),
      );

      // No tracks to suggest INTO — suggestions are impossible until one exists.
      // (The CLI takes this early-exit only when there are zero active tracks,
      // so the normal batch path always has a non-empty tracks list.)
      if (scan.note === "no_active_tracks") {
        vscode.window.showInformationMessage(
          `Work Plan: ${repo} has no active tracks to suggest into — create one first ` +
            "(right-click the repo → New Track, or run Group Issues).",
        );
        return;
      }

      if (scan.note === "full_coverage" || (scan.untracked ?? []).length === 0) {
        vscode.window.showInformationMessage(
          `Work Plan: ${repo} has no untracked issues — full coverage.`,
        );
        return;
      }

      // Record the batch + arm the watcher on the CLI-emitted answers path (used
      // verbatim). The watcher's cold read picks up the heuristic answers the CLI
      // just wrote; for the LLM path it fires when the Claude session writes them.
      provider.setBatchId(repo, scan.batch_id);
      watchAnswers(repo, scan.answers_path);

      if (heuristic) {
        // watchAnswers cold-read just populated the buckets — report the REAL
        // count so we don't promise suggestions when everything abstained.
        const b = provider.getSuggestions(repo);
        const n = (b?.suggested.length ?? 0) + (b?.needsReview.length ?? 0);
        if (n === 0) {
          vscode.window.showInformationMessage(
            `Work Plan: offline matching found no confident track for ${repo}'s ` +
              `${scan.untracked.length} untracked issue(s) — all left untracked. ` +
              "Try Suggest Tracks (with AI) for smarter matches.",
          );
        } else {
          vscode.window.showInformationMessage(
            `Work Plan: ${n} offline match(es) under ${repo}'s Untracked bucket ` +
              "(no AI — lower-trust; review before accepting).",
          );
        }
        return;
      }

      // LLM path: relay the prompt for a Claude session to answer.
      outputChannel.clear();
      outputChannel.appendLine(
        `Ask Claude to produce suggestions and save to ${scan.answers_path}`,
      );
      outputChannel.appendLine("");
      outputChannel.append(scan.prompt);
      outputChannel.show(true);

      vscode.window.showInformationMessage(
        `Work Plan: scanned ${scan.untracked.length} untracked issue(s) in ${repo}. ` +
          "Ask Claude with the prompt in the Work Plan output channel; suggestions appear under Untracked.",
      );
    } catch (err: unknown) {
      const msg = err instanceof CliError
        ? `Work Plan: ${err.message}`
        : `Work Plan: suggest-tracks failed — ${String(err)}`;
      vscode.window.showErrorMessage(msg);
    }
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.suggestTracks",
      (node?: { repo?: string; folder?: string | null }) => runSuggestScan(node, false),
    ),
    vscode.commands.registerCommand(
      "workPlan.suggestTracksOffline",
      (node?: { repo?: string; folder?: string | null }) => runSuggestScan(node, true),
    ),
  );

  // Build the candidate-track QuickPick for accept: the suggested track pre-listed
  // first, then a separator + the rest (same same-repo-first logic as slotUntracked).
  type AcceptTrackItem = vscode.QuickPickItem & { track?: Track };
  const buildAcceptTrackItems = (repo: string, suggestedTrack: string): AcceptTrackItem[] => {
    const exp = provider.rawExport ?? provider.currentExport;
    const all = exp?.tracks ?? [];
    const sameRepo = all.filter(t => t.repo === repo);
    const candidates = sameRepo.length > 0 ? sameRepo : all;
    const suggested = candidates.find(t => t.name === suggestedTrack);
    const others = candidates.filter(t => t !== suggested);
    const items: AcceptTrackItem[] = [];
    if (suggested) {
      items.push({
        label: suggested.name,
        description: `suggested · ${repoKeyForTrack(suggested) ?? suggested.repo}`,
        track: suggested,
      });
    }
    if (others.length > 0) {
      items.push({ label: "Other tracks", kind: vscode.QuickPickItemKind.Separator });
      for (const track of others) {
        items.push({ label: track.name, description: repoKeyForTrack(track), track });
      }
    }
    return items;
  };

  // Compute the CAS fingerprint (#241) of a target track's CURRENT issue list, as
  // the viewer last saw it, so --expect can detect an on-disk change. Returns
  // undefined when the track isn't in the export (then we slot unguarded).
  const expectFor = (track: Track): string =>
    issuesFingerprint(track.issues.map(i => i.number));

  // workPlan.acceptSuggestion — slot one suggested issue, picking/confirming the
  // track. Branches on the CAS outcome (stale/needsRebase).
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.acceptSuggestion",
      async (node?: SuggestedIssueNode) => {
        if (!node || node.kind !== "suggestedIssue") return;
        try {
          const issue = node.issue.number;
          const pick = await vscode.window.showQuickPick(
            buildAcceptTrackItems(node.repo, node.suggestedTrack),
            {
              placeHolder: `Slot #${issue} into a track`,
              ...({ detail: `${Math.round(node.confidence * 100)}% · ${node.rationale}` } as object),
            },
          );
          if (!pick || !pick.track) return;
          const trackObj = pick.track;
          const track = trackObj.name;
          const repoKey = repoKeyForTrack(trackObj);

          const outcome = await withWriteProgress(
            `Work Plan: adding #${issue} to ${track}…`,
            () => executeWrite(
              runner,
              { kind: "slot", track, repoKey, issue, expect: expectFor(trackObj) },
              confirmPublicWrite,
            ),
          );

          if (outcome.status === "written") {
            await refreshAfterWrite();
            readAndStoreSuggestions(node.repo); // drop the just-accepted suggestion
            vscode.window.showInformationMessage(`Work Plan: added #${issue} to ${track}`);
          } else if (outcome.status === "cancelled") {
            vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          } else if (outcome.status === "stale") {
            vscode.window.showInformationMessage(
              `Work Plan: ${track} changed since the suggestion — re-scan and try again.`,
            );
            await refreshAfterWrite();
            readAndStoreSuggestions(node.repo);
          } else {
            // needsRebase
            vscode.window.showWarningMessage(
              `Work Plan: ${track}'s shared plan branch diverged — pull/resolve, then retry.`,
            );
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: accept-suggestion failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    // workPlan.dismissSuggestion — drop a suggestion (suggested OR needs-review)
    // back to plain untracked. Persists the dismiss key; no toast.
    vscode.commands.registerCommand(
      "workPlan.dismissSuggestion",
      async (node?: SuggestedIssueNode) => {
        if (!node || node.kind !== "suggestedIssue") return;
        await context.workspaceState.update(dismissKey(node.repo, node.issue.number), true);
        readAndStoreSuggestions(node.repo);
      },
    ),
    // workPlan.batchAcceptSuggestions — accept multiple suggested issues at once,
    // grouped by their suggested track, each batch slotted with its own --expect.
    vscode.commands.registerCommand(
      "workPlan.batchAcceptSuggestions",
      async (node?: SuggestedGroupNode) => {
        if (!node || node.kind !== "suggestedGroup") return;
        try {
          type Item = vscode.QuickPickItem & { issueNumber: number; track: string };
          const items: Item[] = node.suggestions.map(s => ({
            label: `#${s.issueNumber} → ${s.suggestedTrack}`,
            description: s.rationale,
            issueNumber: s.issueNumber,
            track: s.suggestedTrack,
            picked: true,
          }));
          const picks = await vscode.window.showQuickPick(items, {
            canPickMany: true,
            placeHolder: `Accept suggestions for ${node.repo} (each goes to its suggested track)`,
          });
          if (!picks || picks.length === 0) return;

          // Group the chosen issues by their suggested track.
          const byTrack = new Map<string, number[]>();
          for (const p of picks) {
            const list = byTrack.get(p.track) ?? [];
            list.push(p.issueNumber);
            byTrack.set(p.track, list);
          }

          let accepted = 0;
          let staleTracks = 0;
          let rebaseTracks = 0;
          const exp = provider.rawExport ?? provider.currentExport;
          for (const [track, issues] of byTrack) {
            const trackObj = exp?.tracks.find(t => t.repo === node.repo && t.name === track);
            if (!trackObj) continue;
            const repoKey = repoKeyForTrack(trackObj);
            const outcome = await withWriteProgress(
              `Work Plan: adding ${issues.length} issue(s) to ${track}…`,
              () => executeWrite(
                runner,
                { kind: "batchSlot", track, repoKey, issues, expect: expectFor(trackObj) },
                confirmPublicWrite,
              ),
            );
            if (outcome.status === "written") {
              accepted += issues.length;
            } else if (outcome.status === "stale") {
              staleTracks++;
            } else if (outcome.status === "needsRebase") {
              rebaseTracks++;
            }
            // "cancelled" → user kept private for that track; skip silently.
          }

          if (accepted > 0) await refreshAfterWrite();
          readAndStoreSuggestions(node.repo);

          const parts: string[] = [];
          if (accepted > 0) parts.push(`added ${accepted} issue(s)`);
          if (staleTracks > 0) parts.push(`${staleTracks} track(s) changed — re-scan`);
          if (rebaseTracks > 0) parts.push(`${rebaseTracks} track(s) need a pull/rebase`);
          vscode.window.showInformationMessage(
            `Work Plan: ${parts.length ? parts.join("; ") + "." : "no changes written."}`,
          );
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: batch-accept failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    // workPlan.dismissAllSuggestions — dismiss every suggested issue in a group
    // after a non-modal confirm.
    vscode.commands.registerCommand(
      "workPlan.dismissAllSuggestions",
      async (node?: SuggestedGroupNode) => {
        if (!node || node.kind !== "suggestedGroup") return;
        const ok = await vscode.window.showWarningMessage(
          `Dismiss all ${node.suggestions.length} suggestion(s) for ${node.repo}? They drop back to plain untracked.`,
          "Dismiss all",
        );
        if (ok !== "Dismiss all") return;
        for (const s of node.suggestions) {
          await context.workspaceState.update(dismissKey(node.repo, s.issueNumber), true);
        }
        readAndStoreSuggestions(node.repo);
      },
    ),
  );

  // -------------------------------------------------------------------------
  // workPlan.close — close a track with a state (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.close", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        const state = await vscode.window.showQuickPick(
          ["shipped", "parked", "abandoned"],
          { placeHolder: "Close track as…" },
        );
        if (!state) return; // cancelled

        // Abandon is the destructive close — it archives the track to
        // archive/abandoned/. Gate it behind an explicit modal (#219); shipped
        // and parked are routine lifecycle and proceed without the extra step.
        if (state === "abandoned") {
          const ok = await vscode.window.showWarningMessage(
            `Abandon track "${track}"? It will be archived to archive/abandoned/.`,
            { modal: true },
            "Abandon track",
          );
          if (ok !== "Abandon track") return;
        }

        const noteRaw = await vscode.window.showInputBox({
          prompt: "Wrap-up note (optional — press Enter or Escape to skip)",
        });
        // undefined = Esc = proceed with no note (don't hard-cancel on optional field)
        const note = noteRaw && noteRaw.trim() !== "" ? noteRaw.trim() : undefined;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: closing ${track} as ${state}…`,
          () => executeWrite(
            runner,
            { kind: "close", track, repoKey, state: state as "shipped" | "parked" | "abandoned", ...(note ? { note } : {}) },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: closed ${track} as ${state}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: close failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.renameTrack — rename a track's slug (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.renameTrack", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        const newSlug = await vscode.window.showInputBox({
          prompt: `New slug for "${track}"`,
          value: track,
          validateInput: (v) => {
            if (!/^[a-z][a-z0-9-]*$/.test(v)) {
              return "Slug must be lowercase, start with a letter, e.g. my-feature";
            }
            if (v === track) return "Enter a slug different from the current one";
            return null;
          },
        });
        if (newSlug === undefined) return; // cancelled

        // Rename moves the track's file on disk and rewrites its frontmatter —
        // confirm before doing it (#219).
        const okRename = await vscode.window.showWarningMessage(
          `Rename track "${track}" to "${newSlug}"? This moves its file and rewrites the frontmatter.`,
          { modal: true },
          "Rename track",
        );
        if (okRename !== "Rename track") return;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: renaming ${track} → ${newSlug}…`,
          () => executeWrite(
            runner,
            { kind: "renameTrack", track, repoKey, newSlug },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: renamed ${track} → ${newSlug}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: rename-track failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
    // workPlan.pushTrack (#306) — promote a private track to the shared tier +
    // push. Confirm modal names the repo and warns on a PUBLIC repo (the track
    // becomes world-visible). executeWrite drives the CLI's public-repo token.
    vscode.commands.registerCommand("workPlan.pushTrack", async (node?: TrackNode) => {
      const track = node?.track;
      if (!track) return;
      if (track.tier === "shared") {
        vscode.window.showInformationMessage(
          `Work Plan: "${track.name}" is already in the shared tier.`,
        );
        return;
      }
      const repoLabel = track.repo ?? "this repo";
      const exposure = track.visibility === "PUBLIC"
        ? `\n\n⚠ ${repoLabel} is PUBLIC — promoting + pushing makes this track visible to anyone on the internet, and it stays in public git history.`
        : "";
      const ok = await vscode.window.showWarningMessage(
        `Promote track "${track.name}" to the shared tier of ${repoLabel} and push it to the plan branch?${exposure}`,
        { modal: true },
        "Push to Shared Tier",
      );
      if (ok !== "Push to Shared Tier") return;
      try {
        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: promoting ${track.name} to shared tier…`,
          () => executeWrite(
            runner,
            { kind: "pushTrack", track: track.name, repoKey: repoKeyForTrack(track) },
            confirmPublicWrite,
          ),
        );
        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: promoted ${track.name} to the shared tier.`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: push-track failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.markCleanup / workPlan.unmarkCleanup — flag/unflag a track as a
  // cleanup candidate (#328/#329/#330). A reversible, non-destructive frontmatter
  // flag (NOT deletion); public repos go through the CLI's confirm-token flow.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.markCleanup", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        const reasonRaw = await vscode.window.showInputBox({
          prompt: `Flag "${track}" as a cleanup candidate`,
          placeHolder: "Reason (optional)",
        });
        if (reasonRaw === undefined) return; // Esc = cancel
        const reason = reasonRaw.trim() !== "" ? reasonRaw.trim() : undefined;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: flagging ${track} for cleanup…`,
          () => executeWrite(
            runner,
            { kind: "markCleanup", track, repoKey, ...(reason ? { reason } : {}) },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: flagged ${track} for cleanup`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: mark-cleanup failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),

    vscode.commands.registerCommand("workPlan.unmarkCleanup", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: clearing cleanup flag on ${track}…`,
          () => executeWrite(
            runner,
            { kind: "unmarkCleanup", track, repoKey },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: cleared cleanup flag on ${track}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: unmark-cleanup failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),

    // workPlan.archiveTrack / workPlan.unarchiveTrack — set a track aside into
    // archive/parked/ (reversible), or restore it (#328). Distinct from Close.
    vscode.commands.registerCommand("workPlan.archiveTrack", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);
        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: archiving ${track}…`,
          () => executeWrite(runner, { kind: "archiveTrack", track, repoKey }, confirmPublicWrite),
        );
        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: archived ${track} — restore via Unarchive Track (or Show archived).`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError ? `Work Plan: ${err.message}` : `Work Plan: archive-track failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),

    vscode.commands.registerCommand("workPlan.unarchiveTrack", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);
        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: restoring ${track}…`,
          () => executeWrite(runner, { kind: "unarchiveTrack", track, repoKey }, confirmPublicWrite),
        );
        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: restored ${track} to the active set.`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError ? `Work Plan: ${err.message}` : `Work Plan: unarchive-track failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),

    // workPlan.toggleShowArchived — flip whether archived tracks appear in the
    // Tracks tree (greyed). Re-exports with/without --include-archived (#328).
    vscode.commands.registerCommand("workPlan.toggleShowArchived", () => {
      showArchivedTracks = !showArchivedTracks;
      void vscode.commands.executeCommand("setContext", "workPlanShowArchived", showArchivedTracks);
      void provider.refresh();
    }),

    // workPlan.deleteTrack — DELETE a track's .md (#330). Destructive: a hard
    // modal that names the track and states exactly what's removed and what
    // isn't (GitHub issues are untouched); a shared-tier delete additionally
    // requires typing the track name to confirm. Never deletes GitHub issues.
    vscode.commands.registerCommand("workPlan.deleteTrack", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);
        const shared = trackObj.tier === "shared";
        // Recoverability is honest about the default: a shared track is always
        // git-backed; a PRIVATE track is only recoverable when notes-vcs (opt-in,
        // off by default) is on — otherwise the delete is permanent. We can't know
        // notes-vcs state here, so the modal states the condition; the toast below
        // reports what actually happened from the CLI output.
        const recovery = shared
          ? "The deletion is staged in git — recoverable from history until you commit & push."
          : "Recoverable ONLY if notes-vcs (local history) is enabled — otherwise the file is permanently removed.";

        const choice = await vscode.window.showWarningMessage(
          `Delete track "${track}"?`,
          {
            modal: true,
            detail:
              `This removes the track's markdown file only.\n\n` +
              `• GitHub issues are NOT touched — they outlive the track.\n` +
              `• ${recovery}\n\n` +
              (shared ? `This is a SHARED track — you'll be asked to type its name to confirm.` : `Prefer "Archive Track" if you might want it back.`),
          },
          { title: "Delete", isCloseAffordance: false },
        );
        if (!choice || choice.title !== "Delete") return;

        // Shared-tier: type-to-confirm the exact track name (extra guard on the
        // higher-blast-radius delete).
        if (shared) {
          const typed = await vscode.window.showInputBox({
            prompt: `Type the track name to confirm deletion`,
            placeHolder: track,
            validateInput: (v) => v.trim() === track ? undefined : `Type "${track}" exactly to confirm.`,
          });
          if (typed?.trim() !== track) return;
        }

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: deleting ${track}…`,
          () => executeWrite(runner, { kind: "deleteTrack", track, repoKey }, confirmPublicWrite),
        );
        if (outcome.status === "written") {
          await refreshAfterWrite();
          // The CLI prints "⚠ PERMANENT" when it fell back to a bare unlink
          // (no notes-vcs) — report that honestly rather than a blanket "undo".
          const permanent = outcome.stdout?.includes("PERMANENT");
          const tail = shared
            ? "Commit & push to remove it for teammates."
            : permanent
              ? "PERMANENT — notes-vcs is off, so this can't be undone."
              : "Recoverable via notes-vcs undo.";
          vscode.window.showInformationMessage(`Work Plan: deleted ${track} — GitHub issues untouched. ${tail}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError ? `Work Plan: ${err.message}` : `Work Plan: delete-track failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.newTrack — create a new track (view/title overflow + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.newTrack", async (node?: RepoNode) => {
      try {
        let repo: string | undefined;

        // Invoked from a repo node (context menu / empty-state click): prefill the
        // github slug and skip the repo prompt. A "(no repo)" node has no real slug,
        // so fall through to prompting as if invoked bare.
        const prefilledRepo =
          node && node.kind === "repo" && node.repo && node.repo !== "(no repo)"
            ? node.repo
            : undefined;

        if (prefilledRepo) {
          repo = prefilledRepo;
        } else {
          // --- Repo selection (palette / title-bar invocation) ---
          const MANUAL_ENTRY_LABEL = "$(add) Enter a repo (org/repo)…";
          const existingRepos = Array.from(
            new Set(
              (provider.currentExport?.tracks ?? [])
                .map(t => t.repo)
                .filter((r): r is string => typeof r === "string" && r.trim() !== ""),
            ),
          );

          type RepoItem = vscode.QuickPickItem & { isManual?: boolean };
          const repoItems: RepoItem[] = [
            ...existingRepos.map(r => ({ label: r })),
            { label: MANUAL_ENTRY_LABEL, isManual: true },
          ];

          if (existingRepos.length === 0) {
            // No repos loaded — go straight to manual entry.
            repo = await vscode.window.showInputBox({
              prompt: "Repo (org/repo)",
              validateInput: (v) =>
                /^[\w.-]+\/[\w.-]+$/.test(v) ? null : "Enter an org/repo slug, e.g. your-org/myproject",
            });
          } else {
            const repoPick = await vscode.window.showQuickPick<RepoItem>(repoItems, {
              placeHolder: "Select a repo or enter a new one",
            });
            if (!repoPick) return; // cancelled

            if (repoPick.isManual) {
              repo = await vscode.window.showInputBox({
                prompt: "Repo (org/repo)",
                validateInput: (v) =>
                  /^[\w.-]+\/[\w.-]+$/.test(v) ? null : "Enter an org/repo slug, e.g. your-org/myproject",
              });
            } else {
              repo = repoPick.label;
            }
          }
        }
        if (!repo) return; // cancelled

        // --- Slug ---
        const slug = await vscode.window.showInputBox({
          prompt: "New track slug",
          validateInput: (v) =>
            /^[a-z][a-z0-9-]*$/.test(v) ? null : "Slug must be lowercase, start with a letter, e.g. my-feature",
        });
        if (slug === undefined) return; // cancelled

        // --- Optional priority ---
        const PRIORITY_DEFAULT = "(default P2)";
        const priorityPick = await vscode.window.showQuickPick(
          [PRIORITY_DEFAULT, "P0", "P1", "P2", "P3"],
          { placeHolder: "Priority (optional)" },
        );
        // undefined (Esc) or "(default P2)" → omit priority
        const priority = priorityPick && priorityPick !== PRIORITY_DEFAULT ? priorityPick : undefined;

        // --- Optional milestone ---
        const milestoneRaw = await vscode.window.showInputBox({
          prompt: "Milestone (optional, default v1.0.0 — press Enter to skip)",
        });
        // undefined (Esc) or empty → proceed without milestone
        const milestone = milestoneRaw && milestoneRaw.trim() !== "" ? milestoneRaw.trim() : undefined;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: creating track ${slug}…`,
          () => executeWrite(
            runner,
            {
              kind: "newTrack",
              repo,
              slug,
              ...(priority ? { priority } : {}),
              ...(milestone ? { milestone } : {}),
            },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: created track ${slug} for ${repo}`);
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: new-track failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.addRepo — register a new repo (view/title overflow + palette + welcome)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.addRepo", async (seed?: { github?: string; key?: string }) => {
      try {
        // The Plans "not registered" row passes {github: slug}; menu/palette pass
        // nothing. Derive a default key from the slug's repo half (lowercased,
        // non-key chars → '-') so the common case is one Enter away. Guard on the
        // string type so an unexpected menu context can't masquerade as a seed.
        const seedGithub = typeof seed?.github === "string" ? seed.github : undefined;
        const seedKey = typeof seed?.key === "string"
          ? seed.key
          : seedGithub?.split("/")[1]?.toLowerCase().replace(/[^a-z0-9-]/g, "-") ?? "";

        const key = await vscode.window.showInputBox({
          prompt: "Short repo key (lowercase, e.g. my-project)",
          value: seedKey,
          validateInput: (v) =>
            /^[a-z][a-z0-9-]*$/.test(v) ? null : "Key must be lowercase, start with a letter, e.g. my-project",
        });
        if (key === undefined) return; // cancelled

        const github = await vscode.window.showInputBox({
          prompt: "GitHub repo (org/repo)",
          value: seedGithub ?? "",
          validateInput: (v) =>
            /^[\w.-]+\/[\w.-]+$/.test(v) ? null : "Enter an org/repo slug, e.g. your-org/myproject",
        });
        if (github === undefined) return; // cancelled

        const localRaw = await vscode.window.showInputBox({
          prompt: "Local checkout path (optional — needed to scan this repo's plans; press Enter to skip)",
        });
        // undefined (Esc) or empty → omit local
        const local = localRaw && localRaw.trim() !== "" ? localRaw.trim() : undefined;

        let outcome: WriteOutcome;
        try {
          outcome = await withWriteProgress(
            `Work Plan: adding repo ${github}…`,
            () => executeWrite(
              runner,
              { kind: "addRepo", key, github, ...(local ? { local } : {}) },
              confirmPublicWrite,
            ),
          );
        } catch (addErr: unknown) {
          // The CLI hard-errors on an already-registered key (now pointing at
          // --update). Offer to set/update its local path instead of just
          // surfacing the error — the common 2nd-run intent is "add the path I
          // skipped".
          if (isAlreadyExistsError(addErr)) {
            const choice = await vscode.window.showWarningMessage(
              `Repo ${key} is already registered. Set/update its local checkout path?`,
              "Set path",
              "Cancel",
            );
            if (choice !== "Set path") return;

            const updateLocalRaw = await vscode.window.showInputBox({
              prompt: "Local checkout path (needed to scan this repo's plans)",
              value: local ?? "",
            });
            if (updateLocalRaw === undefined) return; // cancelled
            const updateLocal = updateLocalRaw.trim();
            if (updateLocal === "") {
              vscode.window.showInformationMessage("Work Plan: no path entered — nothing changed.");
              return;
            }

            const updateOutcome: WriteOutcome = await withWriteProgress(
              `Work Plan: updating repo ${key}…`,
              () => executeWrite(
                runner,
                { kind: "addRepo", key, github, local: updateLocal, update: true },
                confirmPublicWrite,
              ),
            );
            if (updateOutcome.status === "written") {
              await refreshAfterWrite();
              vscode.window.showInformationMessage(
                `Work Plan: set ${key}'s local path — its plans will now be scanned.`,
              );
            } else {
              vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
            }
            return;
          }
          throw addErr;
        }

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(
            `Work Plan: registered ${github} as ${key} — it's now in the sidebar. ` +
              "Right-click it → New Track to start; add a local path to scan its plans.",
          );
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: add-repo failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.removeRepo — unregister a repo (config-only; repo-node context menu)
  // Completes the add/update/remove trio. Removal is config-only: notes, tracks,
  // and the local clone are untouched, so no public-leak guard is needed — but
  // routing through executeWrite keeps the write path uniform (removeRepo never
  // trips needs_confirm).
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.removeRepo", async (node?: RepoNode) => {
      try {
        const key = node?.folder;
        if (!key) {
          vscode.window.showInformationMessage(
            "Work Plan: not a configured repo — nothing to remove.",
          );
          return;
        }

        const ok = await vscode.window.showWarningMessage(
          `Remove “${node!.repo}” from Work Plan?`,
          {
            modal: true,
            detail:
              `Unregisters the repo (key “${key}”) — it disappears from this sidebar.\n\n` +
              "This does NOT delete anything: your track notes, the local clone on " +
              "disk, and everything on GitHub stay exactly as they are. You can " +
              "re-add it any time with Add Repo.",
          },
          "Remove from Work Plan",
        );
        if (ok !== "Remove from Work Plan") return;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: removing ${node!.repo}…`,
          () => executeWrite(runner, { kind: "removeRepo", key }, confirmPublicWrite),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(
            `Work Plan: removed ${node!.repo} — notes, tracks, and clone left in place.`,
          );
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: remove-repo failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.clearRepoLocal — drop a configured repo's local path (keeps the
  // repo). Repo-node context menu. Routes through init-repo --update --clear-local.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.clearRepoLocal", async (node?: RepoNode) => {
      try {
        const key = node?.folder;
        if (!key) {
          vscode.window.showInformationMessage(
            "Work Plan: not a configured repo — nothing to clear.",
          );
          return;
        }
        if (!node!.hasLocal) {
          vscode.window.showInformationMessage(
            `Work Plan: ${node!.repo} has no local path set.`,
          );
          return;
        }

        const ok = await vscode.window.showWarningMessage(
          `Clear the local checkout path for “${node!.repo}”?`,
          {
            modal: true,
            detail:
              `The repo stays registered (key “${key}”) — only the saved local ` +
              "path is forgotten. Plan scanning for this repo turns off until you " +
              "set a path again. The clone on disk is untouched.",
          },
          "Clear path",
        );
        if (ok !== "Clear path") return;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: clearing local path for ${node!.repo}…`,
          () => executeWrite(
            runner,
            { kind: "addRepo", key, github: node!.repo, update: true, clearLocal: true },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(
            `Work Plan: cleared local path for ${node!.repo}.`,
          );
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: clear-local failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.setNotesLocation — set notes root path (view/title overflow + palette + welcome)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.setNotesLocation", async () => {
      try {
        const picked = await vscode.window.showOpenDialog({
          canSelectFolders: true,
          canSelectFiles: false,
          canSelectMany: false,
          openLabel: "Set notes location",
        });
        if (!picked || picked.length === 0) return; // cancelled

        const path = picked[0].fsPath;

        const outcome: WriteOutcome = await withWriteProgress(
          "Work Plan: setting notes location…",
          () => executeWrite(
            runner,
            { kind: "setNotesRoot", path },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: notes location set to ${path}`);
          if (outcome.stdout.includes("WARN")) {
            // Surface only the WARN line (stdout also carries the ✓ success line).
            const warnLine = outcome.stdout
              .split("\n")
              .find((l) => l.includes("WARN")) ?? outcome.stdout.trim();
            vscode.window.showWarningMessage(warnLine);
          }
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: set-notes-location failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.hygiene — run hygiene across all tracks (view/title overflow + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.hygiene", async () => {
      try {
        const go = await vscode.window.showWarningMessage(
          "Run hygiene across all tracks? Refreshes bodies and reconciles labels.",
          { modal: true },
          "Run hygiene",
        );
        if (go !== "Run hygiene") return;

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: "Work Plan: running hygiene…",
            cancellable: false,
          },
          async () => {
            const outcome: WriteOutcome = await executeWrite(
              runner,
              { kind: "hygiene" },
              confirmPublicWrite,
            );

            if (outcome.status === "written") {
              await refreshAfterWrite();
              vscode.window.showInformationMessage("Work Plan: hygiene complete.");
            } else {
              vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
            }
          },
        );
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: hygiene failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // Daily-driver relay verbs (#210): brief / orient / handoff. The CLI's
  // verbatim-relay output is designed to be read as-is, so these pipe stdout
  // straight to the Work Plan output channel.
  // -------------------------------------------------------------------------

  // Shared helper: run a read-only relay verb and show its stdout in the channel.
  const runRelay = async (args: string[], failVerb: string): Promise<void> => {
    const result = await runner(args);
    if (result.code !== 0) {
      throw new CliError({
        message: result.stderr.trim() || `${failVerb} failed (exit ${result.code})`,
        args,
        code: result.code,
        stdout: result.stdout,
        stderr: result.stderr,
      });
    }
    outputChannel.clear();
    outputChannel.append(result.stdout);
    outputChannel.show(true);
  };

  // workPlan.dailyBrief — multi-track daily snapshot (read-only; title bar + palette).
  // Re-entrancy guard: brief takes a few seconds, and the title-bar icon is easy
  // to click repeatedly — without this, each click spawned another concurrent run
  // and a stacked progress toast. While one is in flight, extra invocations no-op.
  let briefInFlight = false;
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.dailyBrief", async () => {
      if (briefInFlight) return;
      briefInFlight = true;
      try {
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: "Work Plan: building daily brief…",
            cancellable: false,
          },
          () => runRelay(["brief"], "brief"),
        );
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: brief failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      } finally {
        briefInFlight = false;
      }
    }),
  );

  // workPlan.orient — re-orient on a track (read-only; context menu + palette).
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.orient", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Work Plan: re-orienting on ${track}…`,
            cancellable: false,
          },
          () => runRelay([
            "where-was-i",
            ...(repoKey ? [`--repo=${repoKey}`] : []),
            "--",
            track,
          ], "where-was-i"),
        );
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: where-was-i failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // workPlan.handoff — wrap up a work session on a track (writes a session log +
  // last_handoff; context menu + palette). Routes through the public-write
  // confirm flow, then relays the paste-ready prompt to the output channel.
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.handoff", async (node?: TrackNode) => {
      try {
        const trackObj = await resolveTrack(node);
        if (!trackObj) return;
        const track = trackObj.name;
        const repoKey = repoKeyForTrack(trackObj);

        const outcome: WriteOutcome = await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Work Plan: wrapping up ${track}…`,
            cancellable: false,
          },
          () => executeWrite(runner, { kind: "handoff", track, repoKey }, confirmPublicWrite),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          outputChannel.clear();
          outputChannel.append(outcome.stdout);
          outputChannel.show(true);
          vscode.window.showInformationMessage(
            `Work Plan: handoff for ${track} — see the Work Plan output channel.`,
          );
        } else {
          vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
        }
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: handoff failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.searchIssues — keyword search of issue titles with %wildcards (#272).
  // Searches the in-memory export (the same snapshot every view reads); results
  // open in a dedicated reusable panel that never clobbers the detail view.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.searchIssues", async () => {
      try {
        if (!provider.rawExport) {
          await provider.refresh();
        }
        const loaded = provider.rawExport;
        if (!loaded || loaded.tracks.length === 0) {
          vscode.window.showInformationMessage("Work Plan: No issues loaded — run Refresh first.");
          return;
        }

        const query = await vscode.window.showInputBox({
          placeHolder: "Search issues — e.g. %depends%, fix%, %audit",
          prompt: "Match issue titles. Bare word = contains; % = wildcard (fix% starts-with, %audit ends-with).",
          validateInput: (v) => {
            const t = v.trim();
            return t !== "" && /^%+$/.test(t)
              ? "A query of % alone matches everything — add text, e.g. %fix% or depends%"
              : null;
          },
        });
        if (query === undefined || query.trim() === "") return;

        // Renders results for `q` from the latest export and wires the row
        // actions. Reused by the panel's "Refresh & re-run" affordance.
        const runAndShow = (q: string): void => {
          const current = provider.rawExport;
          if (!current) return;
          SearchPanel.showResults(
            { query: q, hits: searchIssues(current, q), generatedAt: current.generated_at },
            {
              openIssue: (repo, number) =>
                void vscode.commands.executeCommand("workPlan.openIssue", { repo, number }),
              revealTrack: async (repo, track) => {
                const node = provider.findTrackNode(track, repo);
                if (node) {
                  await treeView.reveal(node, { focus: true, select: true, expand: true });
                } else {
                  vscode.window.showInformationMessage(
                    `Work Plan: "${track}" isn't visible in the current view (it may be filtered out by the active lens).`,
                  );
                }
              },
              refreshAndSearch: async () => {
                try {
                  await provider.refresh();
                  runAndShow(q);
                } catch (err: unknown) {
                  const m = err instanceof CliError
                    ? `Work Plan: ${err.message}`
                    : `Work Plan: refresh failed — ${String(err)}`;
                  vscode.window.showErrorMessage(m);
                }
              },
            },
          );
        };
        runAndShow(query);
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: search failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // workPlan.notesVcs — manage opt-in local history for the private tier (#224)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.notesVcs", async () => {
      try {
        const st = await notesVcsStatus(runner);
        notesState = st;

        type Item = vscode.QuickPickItem & { action: "init" | "enable" | "disable" | "status" };
        const items: Item[] = [];
        if (st === null) {
          vscode.window.showWarningMessage(
            "Work Plan: this CLI doesn't support local history — update with: npm install -g @stylusnexus/work-plan",
          );
          return;
        }
        if (!st.is_root) {
          items.push({
            label: "$(repo) Enable local history",
            detail: "git-init notes_root as a personal, never-pushed repo and turn on auto-commit",
            action: "init",
          });
        } else if (st.auto_commit) {
          items.push({
            label: "$(circle-slash) Turn off auto-commit",
            detail: "Stop committing edits (existing history is kept)",
            action: "disable",
          });
        } else {
          items.push({
            label: "$(check) Turn on auto-commit",
            detail: "Commit every track edit so it's undoable",
            action: "enable",
          });
        }
        items.push({
          label: "$(info) Show status",
          detail: st.is_root
            ? `Local repo · auto-commit ${st.auto_commit ? "on" : "off"} · last: ${st.last_commit_subject ?? "none"}`
            : "Not a git repo yet",
          action: "status",
        });

        const pick = await vscode.window.showQuickPick(items, {
          placeHolder: "Work Plan: local history (private notes)",
        });
        if (!pick) return;

        if (pick.action === "status") {
          vscode.window.showInformationMessage(
            st.is_root
              ? `Work Plan: local history ${st.auto_commit ? "ON" : "off"} · ${st.last_commit_subject ?? "no commits yet"}`
              : "Work Plan: notes_root has no local history — choose “Enable local history”.",
          );
          return;
        }

        await notesVcsRun(runner, pick.action);
        notesState = await notesVcsStatus(runner);
        const done =
          pick.action === "init" ? "local history enabled"
          : pick.action === "enable" ? "auto-commit on"
          : "auto-commit off";
        vscode.window.showInformationMessage(`Work Plan: ${done}.`);
      } catch (err: unknown) {
        const msg = err instanceof CliError
          ? `Work Plan: ${err.message}`
          : `Work Plan: notes-vcs failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      }
    }),
  );

  // -------------------------------------------------------------------------
  // Plans view (#164): a second tree rendering plan-status verdicts, scanned
  // lazily per-repo on expand. Repos are the distinct config FOLDER KEYS from
  // the export (the `plan-status --repo=<key>` arg resolves a local checkout by
  // folder key, not github slug), labelled by their slug for display.
  // -------------------------------------------------------------------------

  // Read the stall-days threshold: "match" → null (trust the CLI's own
  // `stalled`), otherwise the parsed integer day count.
  const stallDaysSetting = (): number | null => {
    const raw = vscode.workspace
      .getConfiguration("workPlan")
      .get<string>("stallDays", "match");
    return raw === "match" ? null : parseInt(raw, 10);
  };

  // Whether the Plans view auto-updates on a scanned repo's git activity (#287).
  const plansAutoRefreshSetting = (): boolean =>
    vscode.workspace.getConfiguration("workPlan").get<boolean>("plansAutoRefresh", true);

  // Distinct {repoKey: folder, label: slug} from the export's CONFIGURED repos
  // (#288), deduped by folder. Sourcing from `exp.repos` (not `exp.tracks`) means
  // a registered repo with a local clone but NO track (e.g. agent-armor) still
  // appears and scans in the Plans view. Repos without a folder key are skipped —
  // plan-status resolves a local checkout by folder key, not github slug.
  const reposForPlans = (): { repoKey: string; label: string }[] => {
    const raw = provider.rawExport;
    if (!raw) return [];
    const seen = new Map<string, string>();
    for (const r of raw.repos ?? []) {
      if (r.folder && !seen.has(r.folder)) {
        seen.set(r.folder, r.repo ?? r.folder);
      }
    }
    return Array.from(seen, ([repoKey, label]) => ({ repoKey, label }));
  };

  // Slugs of repos that have tracks but no `repos:` config entry (#288 follow-up)
  // — surfaced in the Plans view as greyed "not registered" rows. Reads the RAW
  // export (not the lens-filtered one) so the row list doesn't shift with the
  // active Tracks lens. Kept separate from reposForPlans so Scan All never tries
  // to scan a repo with no registered local clone.
  const unregisteredForPlans = (): string[] => {
    const raw = provider.rawExport;
    return raw ? unregisteredTrackRepos(raw) : [];
  };

  // Ack state (#164): plans the user has chosen to stop flagging. Persisted in
  // workspaceState (per-workspace, not global) keyed by ackKey(repoKey, rel). We
  // persist ONLY the ack key — never stalled-ness, which is re-derived live, so a
  // plan that's no longer stalled simply leaves the stalled bucket on its own.
  const ACK_KEY = "workPlan.ackedPlans";
  const ackedPlans = new Set<string>(context.workspaceState.get<string[]>(ACK_KEY, []));

  // showAcked toggles whether acked docs still render (demoted/greyed, the
  // default) or are filtered out entirely. In-memory — resets to "show" per session.
  let showAcked = true;

  const plansProvider = new PlansProvider(
    runner,
    reposForPlans,
    stallDaysSetting,
    (repoKey, rel) => ackedPlans.has(ackKey(repoKey, rel)),
    () => showAcked,
    unregisteredForPlans,
    plansAutoRefreshSetting,
  );
  // Tear down the Plans view's git watchers on deactivation (#287).
  context.subscriptions.push({ dispose: () => plansProvider.dispose() });

  const setAck = async (repoKey: string, rel: string, on: boolean): Promise<void> => {
    const k = ackKey(repoKey, rel);
    if (on) ackedPlans.add(k); else ackedPlans.delete(k);
    await context.workspaceState.update(ACK_KEY, [...ackedPlans]);
    plansProvider.rerender();
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.plans.acknowledge",
      async (
        n?: { kind?: string; repoKey?: string; doc?: PlanDoc },
        selected?: Array<{ kind?: string; repoKey?: string; doc?: PlanDoc }>,
      ) => {
        // Mirrors archive's (clickedNode, fullSelection[]) shape (#396).
        // Predicate mirrors when-clause: viewItem =~ /workPlanPlan-(stalled|dead)/
        const nodes = Array.isArray(selected) && selected.length > 1 ? selected : (n ? [n] : []);
        const ackPred = (doc: PlanDoc) =>
          isStalledForDisplay(doc, stallDaysSetting(), Date.now()) || doc.verdict === "dead";
        const targets = selectedDocNodes(nodes, ackPred);
        if (targets.length === 0) {
          // Single-node fallback for backwards compat (no PlanDoc in node)
          if (n?.kind === "doc" && n.repoKey && n.doc?.rel) {
            return setAck(n.repoKey, n.doc.rel, true);
          }
          return;
        }
        if (targets.length === 1) {
          return setAck(targets[0].repoKey, targets[0].rel, true);
        }
        // Batch: acknowledge each target, one rerender covers all.
        for (const t of targets) {
          const k = ackKey(t.repoKey, t.rel);
          ackedPlans.add(k);
        }
        await context.workspaceState.update(ACK_KEY, [...ackedPlans]);
        plansProvider.rerender();
        vscode.window.showInformationMessage(`Work Plan: acknowledged ${targets.length} plan(s).`);
      },
    ),
    vscode.commands.registerCommand(
      "workPlan.plans.unacknowledge",
      (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) =>
        n?.kind === "doc" && n.repoKey && n.doc?.rel
          ? setAck(n.repoKey, n.doc.rel, false)
          : undefined,
    ),
    vscode.commands.registerCommand("workPlan.plans.toggleAcknowledged", () => {
      showAcked = !showAcked;
      plansProvider.rerender();
    }),
  );

  // Confirm-verdict (#286): write a human `verdict_override` into the plan's
  // FRONTMATTER. Two gates stand in front of the write: a mandatory modal that
  // names the exact file and states it edits only frontmatter (the #286 UI
  // safeguard), then — for a PUBLIC repo — executeWrite's existing confirm-token
  // modal. The write is frontmatter-only; the CLI never touches the body.
  const confirmFrontmatterWrite = async (rel: string, verb: string): Promise<boolean> => {
    const choice = await vscode.window.showWarningMessage(
      `${verb} ${rel}?\n\nThis writes ONLY to the document's YAML frontmatter — never its body, checkboxes, or declared-file manifest.`,
      { modal: true },
      "Write frontmatter",
    );
    return choice === "Write frontmatter";
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.plans.confirmVerdict",
      // Intentionally single-only (#396): picks one verdict via QuickPick; operates
      // on the clicked node only, ignoring any multi-selection passed by VS Code.
      async (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) => {
        if (n?.kind !== "doc" || !n.repoKey || !n.doc?.rel) return;
        const { repoKey } = n;
        const rel = n.doc.rel;
        const filename = rel.split("/").pop() ?? rel;
        const pick = await vscode.window.showQuickPick(
          [
            { label: "$(pass-filled) Shipped", verdict: "shipped" as const, description: "Done — the banner is correct" },
            { label: "$(circle-filled) Partial", verdict: "partial" as const, description: "Still in progress" },
            { label: "$(circle-slash) Dead", verdict: "dead" as const, description: "Abandoned" },
          ],
          {
            title: `Confirm verdict for ${filename}`,
            placeHolder: "Pick the verdict to write into the doc's frontmatter",
          },
        );
        if (!pick) return;
        if (!(await confirmFrontmatterWrite(rel, `Write verdict_override: ${pick.verdict} into the frontmatter of`))) {
          return;
        }
        try {
          const outcome = await withWriteProgress(
            `Work Plan: confirming ${pick.verdict}…`,
            () => executeWrite(
              runner,
              { kind: "planConfirm", repoKey, rel, verdict: pick.verdict },
              confirmPublicWrite,
            ),
          );
          if (outcome.status === "written") {
            plansProvider.refresh(repoKey);
            vscode.window.showInformationMessage(`Work Plan: ${filename} confirmed ${pick.verdict}.`);
          } else {
            vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: confirm failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    vscode.commands.registerCommand(
      "workPlan.plans.clearConfirmation",
      async (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) => {
        if (n?.kind !== "doc" || !n.repoKey || !n.doc?.rel) return;
        const { repoKey } = n;
        const rel = n.doc.rel;
        const filename = rel.split("/").pop() ?? rel;
        if (!(await confirmFrontmatterWrite(rel, "Clear the verdict override from the frontmatter of"))) {
          return;
        }
        try {
          const outcome = await withWriteProgress(
            "Work Plan: clearing confirmation…",
            () => executeWrite(
              runner,
              { kind: "planConfirmClear", repoKey, rel },
              confirmPublicWrite,
            ),
          );
          if (outcome.status === "written") {
            plansProvider.refresh(repoKey);
            vscode.window.showInformationMessage(`Work Plan: cleared confirmation on ${filename}.`);
          } else {
            vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: clear failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    // Durable acknowledgment (#286): write `acknowledged: true` to the doc's
    // frontmatter (committed + shared) — distinct from the local-only
    // Acknowledge above. Same file-naming + public-repo gates as Confirm Verdict.
    vscode.commands.registerCommand(
      "workPlan.plans.acknowledgePersist",
      async (
        n?: { kind?: string; repoKey?: string; doc?: PlanDoc },
        selected?: Array<{ kind?: string; repoKey?: string; doc?: PlanDoc }>,
      ) => {
        // Mirrors archive's (clickedNode, fullSelection[]) shape (#396).
        // Predicate mirrors when-clause: viewItem =~ /workPlanPlan-(stalled|dead)/
        const nodes = Array.isArray(selected) && selected.length > 1 ? selected : (n ? [n] : []);
        const ackPred = (doc: PlanDoc) =>
          isStalledForDisplay(doc, stallDaysSetting(), Date.now()) || doc.verdict === "dead";
        const targets = selectedDocNodes(nodes, ackPred);

        if (targets.length <= 1) {
          // Single-doc path — use the clicked node (original behaviour).
          const sn = targets.length === 1
            ? { kind: "doc" as const, repoKey: targets[0].repoKey, doc: targets[0].doc }
            : n;
          if (sn?.kind !== "doc" || !sn.repoKey || !sn.doc?.rel) return;
          const { repoKey } = sn;
          const rel = sn.doc.rel;
          const filename = rel.split("/").pop() ?? rel;
          if (!(await confirmFrontmatterWrite(rel, "Write acknowledged: true into the frontmatter of"))) {
            return;
          }
          try {
            const outcome = await withWriteProgress(
              "Work Plan: saving acknowledgment…",
              () => executeWrite(runner, { kind: "planAck", repoKey, rel }, confirmPublicWrite),
            );
            if (outcome.status === "written") {
              plansProvider.refresh(repoKey);
              vscode.window.showInformationMessage(`Work Plan: ${filename} acknowledged (saved to doc).`);
            } else {
              vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
            }
          } catch (err: unknown) {
            const msg = err instanceof CliError
              ? `Work Plan: ${err.message}`
              : `Work Plan: acknowledge failed — ${String(err)}`;
            vscode.window.showErrorMessage(msg);
          }
          return;
        }

        // Batch (#396): N selected eligible docs → one set-level confirm, write each,
        // one refresh per affected repo, summary toast.
        const names = targets.slice(0, 3).map((t) => t.rel.split("/").pop());
        const more = targets.length > 3 ? `, … and ${targets.length - 3} more` : "";
        const ok = await vscode.window.showWarningMessage(
          `Acknowledge & Save to Doc ${targets.length} selected plan(s)?`,
          { modal: true, detail: `${names.join(", ")}${more}\n\nWrites acknowledged: true to each doc's YAML frontmatter only.` },
          "Write frontmatter");
        if (ok !== "Write frontmatter") { return; }
        let written = 0;
        let skipped = 0;
        try {
          await withWriteProgress(`Work Plan: saving acknowledgment on ${targets.length} plan(s)…`, async () => {
            for (const t of targets) {
              const outcome = await executeWrite(runner, { kind: "planAck", repoKey: t.repoKey, rel: t.rel }, confirmPublicWrite);
              if (outcome.status === "written") { written++; } else { skipped++; }
            }
          });
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: acknowledge failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
          return;
        }
        for (const repoKey of new Set(targets.map((t) => t.repoKey))) {
          plansProvider.refresh(repoKey);
        }
        vscode.window.showInformationMessage(
          skipped
            ? `Work Plan: acknowledged ${written}, skipped ${skipped} (kept private).`
            : `Work Plan: acknowledged ${written} plan(s) (saved to doc).`);
      },
    ),
    vscode.commands.registerCommand(
      "workPlan.plans.clearDocAck",
      async (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) => {
        if (n?.kind !== "doc" || !n.repoKey || !n.doc?.rel) return;
        const { repoKey } = n;
        const rel = n.doc.rel;
        const filename = rel.split("/").pop() ?? rel;
        if (!(await confirmFrontmatterWrite(rel, "Remove acknowledged from the frontmatter of"))) {
          return;
        }
        try {
          const outcome = await withWriteProgress(
            "Work Plan: clearing saved acknowledgment…",
            () => executeWrite(runner, { kind: "planAckClear", repoKey, rel }, confirmPublicWrite),
          );
          if (outcome.status === "written") {
            plansProvider.refresh(repoKey);
            vscode.window.showInformationMessage(`Work Plan: cleared saved acknowledgment on ${filename}.`);
          } else {
            vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: clear failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    // Drift baseline (#286): stamp the current computed verdict so plan-status
    // flags drift if it later changes. Re-running re-stamps to "now" (the
    // accept-the-new-reality path). Same file-naming + public-repo gates.
    vscode.commands.registerCommand(
      "workPlan.plans.stampBaseline",
      async (
        n?: { kind?: string; repoKey?: string; doc?: PlanDoc },
        selected?: Array<{ kind?: string; repoKey?: string; doc?: PlanDoc }>,
      ) => {
        // Mirrors archive's (clickedNode, fullSelection[]) shape (#396).
        // Predicate matches the menu when-clause (viewItem =~ /^workPlanPlan-/):
        // baseline applies to ANY plan doc, and re-stamping a confirmed/acked plan
        // is allowed (the single-doc path stamps any clicked node). So the batch
        // must not silently drop override/acked docs — any doc node is eligible.
        const nodes = Array.isArray(selected) && selected.length > 1 ? selected : (n ? [n] : []);
        const targets = selectedDocNodes(nodes, () => true);

        if (targets.length <= 1) {
          // Single-doc path — use clicked node (original behaviour).
          const sn = targets.length === 1
            ? { kind: "doc" as const, repoKey: targets[0].repoKey, doc: targets[0].doc }
            : n;
          if (sn?.kind !== "doc" || !sn.repoKey || !sn.doc?.rel) return;
          const { repoKey } = sn;
          const rel = sn.doc.rel;
          const filename = rel.split("/").pop() ?? rel;
          if (!(await confirmFrontmatterWrite(rel, "Stamp a verdict baseline (watch for drift) into the frontmatter of"))) {
            return;
          }
          try {
            const outcome = await withWriteProgress(
              "Work Plan: stamping baseline…",
              () => executeWrite(runner, { kind: "planBaseline", repoKey, rel }, confirmPublicWrite),
            );
            if (outcome.status === "written") {
              plansProvider.refresh(repoKey);
              vscode.window.showInformationMessage(`Work Plan: baseline stamped on ${filename}.`);
            } else {
              vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
            }
          } catch (err: unknown) {
            const msg = err instanceof CliError
              ? `Work Plan: ${err.message}`
              : `Work Plan: stamp baseline failed — ${String(err)}`;
            vscode.window.showErrorMessage(msg);
          }
          return;
        }

        // Batch (#396): N selected eligible docs → one set-level confirm, stamp each,
        // one refresh per affected repo, summary toast.
        const names = targets.slice(0, 3).map((t) => t.rel.split("/").pop());
        const more = targets.length > 3 ? `, … and ${targets.length - 3} more` : "";
        const ok = await vscode.window.showWarningMessage(
          `Stamp baseline on ${targets.length} selected plan(s)?`,
          { modal: true, detail: `${names.join(", ")}${more}\n\nWrites verdict_baseline to each doc's YAML frontmatter only.` },
          "Write frontmatter");
        if (ok !== "Write frontmatter") { return; }
        let written = 0;
        let skipped = 0;
        try {
          await withWriteProgress(`Work Plan: stamping baseline on ${targets.length} plan(s)…`, async () => {
            for (const t of targets) {
              const outcome = await executeWrite(runner, { kind: "planBaseline", repoKey: t.repoKey, rel: t.rel }, confirmPublicWrite);
              if (outcome.status === "written") { written++; } else { skipped++; }
            }
          });
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: stamp baseline failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
          return;
        }
        for (const repoKey of new Set(targets.map((t) => t.repoKey))) {
          plansProvider.refresh(repoKey);
        }
        vscode.window.showInformationMessage(
          skipped
            ? `Work Plan: stamped baseline on ${written}, skipped ${skipped} (kept private).`
            : `Work Plan: stamped baseline on ${written} plan(s).`);
      },
    ),
    vscode.commands.registerCommand(
      "workPlan.plans.clearBaseline",
      async (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) => {
        if (n?.kind !== "doc" || !n.repoKey || !n.doc?.rel) return;
        const { repoKey } = n;
        const rel = n.doc.rel;
        const filename = rel.split("/").pop() ?? rel;
        if (!(await confirmFrontmatterWrite(rel, "Remove the verdict baseline from the frontmatter of"))) {
          return;
        }
        try {
          const outcome = await withWriteProgress(
            "Work Plan: clearing baseline…",
            () => executeWrite(runner, { kind: "planBaselineClear", repoKey, rel }, confirmPublicWrite),
          );
          if (outcome.status === "written") {
            plansProvider.refresh(repoKey);
            vscode.window.showInformationMessage(`Work Plan: cleared baseline on ${filename}.`);
          } else {
            vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: clear baseline failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    // workPlan.plans.unarchive — restore an archived plan doc back to the live
    // set (#388): the inverse of plans.archive, on a node inside the 📦 Archived
    // folder. Single-doc (no batch); confirm modal names source → destination.
    vscode.commands.registerCommand(
      "workPlan.plans.unarchive",
      async (n?: { kind?: string; repoKey?: string; doc?: PlanDoc }) => {
        if (n?.kind !== "doc" || !n.repoKey || !n.doc?.rel || !n.doc.archived) { return; }
        const repoKey = n.repoKey;
        const rel = n.doc.rel;
        const filename = rel.split("/").pop() ?? rel;
        // Destination strips the `archive/<kind>/` segments (mirrors the CLI).
        const parts = rel.split("/");
        const ai = parts.lastIndexOf("archive");
        const dest = ai >= 0 ? [...parts.slice(0, ai), filename].join("/") : filename;
        if (await vscode.window.showWarningMessage(
          "Restore plan to live?", { modal: true, detail: `${rel}\n\nMoves back to ${dest}.` }, "Restore") !== "Restore") { return; }
        try {
          const outcome = await withWriteProgress("Work Plan: restoring…", () =>
            executeWrite(runner, { kind: "planUnarchive", repoKey, rel }, confirmPublicWrite));
          if (outcome.status !== "written") {
            vscode.window.showInformationMessage("Work Plan: kept — no change written.");
            return;
          }
          let result: string | null = null;
          try { result = (JSON.parse(outcome.stdout) as { outcome?: string }).outcome ?? null; } catch { /* unparseable */ }
          if (result === "restored" || result === "restored_local") {
            plansProvider.refresh(repoKey);
            vscode.window.showInformationMessage(
              `Work Plan: restored ${filename} → ${dest}${result === "restored" ? " (staged — commit & push to share)" : " (moved on disk; not git-tracked)"}`);
          } else if (result === "skipped_collision") {
            vscode.window.showWarningMessage(`Work Plan: not restored — a live doc already exists at ${dest}.`);
          } else {
            vscode.window.showWarningMessage(`Work Plan: could not restore ${filename}.`);
          }
        } catch (err: unknown) {
          const msg = err instanceof CliError ? `Work Plan: ${err.message}` : `Work Plan: plan-unarchive failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    vscode.commands.registerCommand(
      "workPlan.plans.archive",
      async (
        n?: { kind?: string; repoKey?: string; doc?: PlanDoc },
        selected?: Array<{ kind?: string; repoKey?: string; doc?: PlanDoc }>,
      ) => {
        // view/item/context passes (clickedItem, fullSelection[]) (#393). Use the
        // multi-selection when >1; otherwise the clicked node. archivableSelection
        // drops non-doc / non-archivable nodes so a loose multi-select is safe.
        const nodes = Array.isArray(selected) && selected.length > 1 ? selected : (n ? [n] : []);
        const targets = archivableSelection(nodes);
        if (targets.length === 0) { return; }

        // One archive write → its parsed `outcome` (or null on a non-written /
        // unparseable result). Shared by the single and batch paths.
        const archiveOne = async (t: { repoKey: string; rel: string }): Promise<string | null> => {
          const outcome = await executeWrite(
            runner, { kind: "planArchive", repoKey: t.repoKey, rel: t.rel }, confirmPublicWrite);
          if (outcome.status !== "written") { return null; }
          try { return (JSON.parse(outcome.stdout) as { outcome?: string }).outcome ?? null; }
          catch { return null; }
        };

        try {
          if (targets.length === 1) {
            const t = targets[0];
            const filename = t.rel.split("/").pop() ?? t.rel;
            const dest = `archive/shipped/${filename}`;
            const title = t.lieGap ? "Archive unverified plan?" : "Archive plan?";
            const detail = t.lieGap
              ? `${t.rel}\n\nScored shipped but its phase checkboxes are mostly unticked (unverified). It will move to ${dest}.`
              : `${t.rel}\n\nMoves to ${dest}.`;
            if (await vscode.window.showWarningMessage(title, { modal: true, detail }, "Archive") !== "Archive") { return; }
            const result = await withWriteProgress("Work Plan: archiving…", () => archiveOne(t));
            if (result === "archived") {
              plansProvider.refresh(t.repoKey);
              if (await vscode.window.showInformationMessage(
                `Work Plan: archived ${filename} → archive/shipped/ (staged — commit & push to share)`, "Show") === "Show") {
                await vscode.commands.executeCommand("workPlan.plans.focus");
              }
            } else if (result === "archived_local") {
              plansProvider.refresh(t.repoKey);
              if (await vscode.window.showInformationMessage(
                `Work Plan: archived ${filename} → archive/shipped/ (moved on disk; not git-tracked)`, "Show") === "Show") {
                await vscode.commands.executeCommand("workPlan.plans.focus");
              }
            } else if (result === "skipped_collision") {
              vscode.window.showWarningMessage(`Work Plan: not archived — a file already exists at ${dest}.`);
            } else if (result === "refused_not_shipped") {
              vscode.window.showWarningMessage(`Work Plan: ${filename} isn't shipped — not archived.`);
            }
            return;
          }

          // Batch (#393): N selected archivable docs → one confirm, archive each,
          // one refresh per affected repo, summary toast.
          const names = targets.slice(0, 3).map((t) => t.rel.split("/").pop());
          const more = targets.length > 3 ? `, … and ${targets.length - 3} more` : "";
          const lie = targets.filter((t) => t.lieGap).length;
          const lieNote = lie ? `\n\n(${lie} unverified lie-gap plan(s) included.)` : "";
          const ok = await vscode.window.showWarningMessage(
            `Archive ${targets.length} selected plan(s)?`,
            { modal: true, detail: `${names.join(", ")}${more}\n\nEach moves to its repo's archive/shipped/.${lieNote}` },
            "Archive");
          if (ok !== "Archive") { return; }
          let archived = 0;
          let skipped = 0;
          await withWriteProgress(`Work Plan: archiving ${targets.length} plan(s)…`, async () => {
            for (const t of targets) {
              const r = await archiveOne(t);
              if (r === "archived" || r === "archived_local") { archived++; } else { skipped++; }
            }
          });
          for (const repoKey of new Set(targets.map((t) => t.repoKey))) {
            plansProvider.refresh(repoKey);
          }
          vscode.window.showInformationMessage(
            skipped
              ? `Work Plan: archived ${archived}, skipped ${skipped} (collision / not shipped).`
              : `Work Plan: archived ${archived} plan(s).`);
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: archive failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
    vscode.commands.registerCommand(
      "workPlan.plans.archiveAllShipped",
      async (n?: { kind?: string; repoKey?: string }) => {
        if (n?.kind !== "repo" || !n.repoKey) return;
        const { repoKey } = n;
        const docs = plansProvider.cachedDocs(repoKey);
        if (!docs) {
          vscode.window.showInformationMessage(
            "Work Plan: expand the repo first to scan its plans, then archive.");
          return;
        }
        const shipped = docs.filter((d) => d.verdict === "shipped" && d.archived !== true);
        const clean = shipped.filter((d) => !d.lie_gap);
        const lieGap = shipped.filter((d) => d.lie_gap);
        if (clean.length === 0) {
          vscode.window.showInformationMessage("Work Plan: no clean shipped plans to archive.");
          return;
        }
        const names = clean.slice(0, 3).map((d) => d.rel.split("/").pop());
        const more = clean.length > 3 ? `, … and ${clean.length - 3} more` : "";
        const lieNote = lieGap.length
          ? `\n\n(${lieGap.length} unverified lie-gap shipped excluded — use the per-plan action.)`
          : "";
        const ok = await vscode.window.showWarningMessage(
          `Archive ${clean.length} shipped plan(s)?`,
          { modal: true, detail: `${names.join(", ")}${more}${lieNote}` },
          "Archive");
        if (ok !== "Archive") return;
        try {
          const outcome = await withWriteProgress(
            "Work Plan: archiving shipped plans…",
            () => executeWrite(runner, { kind: "planArchiveAllShipped", repoKey }, confirmPublicWrite),
          );
          if (outcome.status !== "written") return;
          let parsed: { archived?: unknown[] } = {};
          try { parsed = JSON.parse(outcome.stdout); } catch { /* non-JSON */ }
          const count = Array.isArray(parsed.archived) ? parsed.archived.length : clean.length;
          plansProvider.refresh(repoKey);
          vscode.window.showInformationMessage(`Work Plan: archived ${count} plan(s).`);
        } catch (err: unknown) {
          const msg = err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: archive failed — ${String(err)}`;
          vscode.window.showErrorMessage(msg);
        }
      },
    ),
  );

  const plansView = vscode.window.createTreeView("workPlan.plans", {
    treeDataProvider: plansProvider,
    canSelectMany: true,   // multi-select batch archive (#393)
  });
  context.subscriptions.push(plansView);

  // Time-relative staleness re-evaluation (#287): a plan crosses the stall
  // threshold purely as days pass, with no git event to trigger a re-scan. The
  // cached docs carry `manifest_last_touched`; the render path re-derives
  // staleness against `Date.now()` each time, so a cheap rerender() (no scan) on
  // view-focus / window-focus keeps the verdict honest without thrashing.
  context.subscriptions.push(
    plansView.onDidChangeVisibility((e) => {
      if (e.visible) {
        plansProvider.rerender();
      }
    }),
    vscode.window.onDidChangeWindowState((s) => {
      if (s.focused && plansView.visible) {
        plansProvider.rerender();
      }
    }),
  );

  // The Plans roots derive from provider.rawExport, which is null until the main
  // provider's async refresh resolves — and the provider is constructed after
  // that refresh is kicked off. Re-render the Plans tree whenever the export
  // changes so the view fills in once data arrives (instead of staying blank
  // until a manual Plans refresh). rerender() (not refresh()) keeps the per-repo
  // scan cache: getChildren re-reads reposForPlans() on every render, so a new
  // repo list is picked up while already-scanned repos (and a completed Scan All
  // roll-up) survive a track sort/filter/auto-refresh.
  context.subscriptions.push(
    provider.onDidChangeTreeData(() => plansProvider.rerender()),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.plans.refresh", () => {
      plansProvider.refresh();
    }),
  );

  // Legend (#348) — an informational QuickPick decoding the verdict icons. Each
  // row renders its real codicon via `$(icon)` in the label, so the picker is
  // self-demonstrating; selecting a row does nothing (it's a reference, not an
  // action). Built from the shared LEGEND so it can never drift from the tree.
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.plans.showLegend", () => {
      const items: vscode.QuickPickItem[] = LEGEND.map((row) => ({
        label: `$(${row.icon}) ${row.label}`,
        detail: row.blurb,
      }));
      void vscode.window.showQuickPick(items, {
        title: "Work Plan — plan verdict legend",
        placeHolder: "What each plan icon means (reference only)",
        matchOnDetail: true,
      });
    }),
  );

  // Scan-all — bounded-concurrent cross-repo scan that streams results into the
  // stalled roll-up. View-scoped progress spins the Plans view title while it runs.
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.plans.scanAll", () =>
      vscode.window.withProgress(
        { location: { viewId: "workPlan.plans" }, title: "Work Plan: scanning plans…" },
        () => plansProvider.scanAll(),
      ),
    ),
  );

  // Re-render the Plans view when the stall-days threshold changes (it shifts
  // which partials read as stalled). The Tracks view ignores this setting.
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("workPlan.stallDays")) {
        plansProvider.rerender();
      }
      // Toggling auto-refresh either way clears the cache via refresh(): OFF
      // disposes the live watchers; ON forces a re-scan on next expand that
      // re-attaches them — including the already-expanded repo the user is
      // looking at, which an ON branch that only relied on lazy expand would
      // miss (it stays cached, so getChildren never re-runs).
      if (e.affectsConfiguration("workPlan.plansAutoRefresh")) {
        plansProvider.refresh();
      }
    }),
  );

  // -------------------------------------------------------------------------
  // Auto-refresh — polls export --json on the configured interval.
  // Silent: errors go to console only (no toast on background failures).
  // -------------------------------------------------------------------------

  let autoRefreshDisposable: vscode.Disposable | undefined;

  const restartAutoRefresh = (): void => {
    autoRefreshDisposable?.dispose();
    autoRefreshDisposable = undefined;
    const intervalSecs = vscode.workspace
      .getConfiguration("workPlan")
      .get<number>("autoRefreshInterval", 0);
    if (intervalSecs > 0) {
      const handle = setInterval(() => {
        refreshAndRerender().catch((err: unknown) => {
          console.error("Work Plan: auto-refresh failed:", err);
        });
      }, intervalSecs * 1000);
      autoRefreshDisposable = new vscode.Disposable(() => clearInterval(handle));
      context.subscriptions.push(autoRefreshDisposable);
    }
  };

  restartAutoRefresh();

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("workPlan.autoRefreshInterval")) {
        restartAutoRefresh();
      }
    }),
  );

  // -------------------------------------------------------------------------
  // On activation: kick off initial data load + version check.
  // NEVER throw out of activate — all async work has its own catch.
  // -------------------------------------------------------------------------

  // Defence-in-depth: never spawn the CLI in an untrusted (Restricted Mode)
  // workspace. The package.json `capabilities.untrustedWorkspaces.supported:false`
  // already gates activation, so in practice this is belt-and-suspenders — but it
  // also protects the spawn paths if that manifest flag is ever relaxed.
  if (!vscode.workspace.isTrusted) {
    return;
  }

  // Seed the notes-vcs state so the FIRST write of the session compares its
  // commit against the real prior HEAD (not null), avoiding a false Undo offer
  // on a no-op write. Best-effort; never blocks activation.
  notesVcsStatus(runner).then((st) => { notesState = st; }, () => { /* ignore */ });

  // Config-drift check (#439: doctor). Deliberately independent of the main
  // data load below — a failed initial CLI load must never suppress this
  // signal for an unrelated reason. Silently does nothing on any CLI failure
  // (missing binary, non-zero exit, unparseable output — doctorScan already
  // returns null for all of those), exactly like the notesVcsStatus seed and
  // autoFocusRepo elsewhere in this file.
  doctorScan(runner).then((findings) => {
    lastDoctorFindings = findings ?? [];
    const status = buildDoctorStatus(lastDoctorFindings);
    if (status) {
      doctorStatusItem.text = status.text;
      doctorStatusItem.tooltip = status.tooltip;
      doctorStatusItem.show();
    } else {
      doctorStatusItem.hide();
    }
  }, () => { /* ignore — convenience signal only */ });

  // Initial data load. On success, surface the one-time GitHub-auth nudge off
  // the SAME refresh (which already probed auth + set the context key driving
  // the Tracks welcome banner) — no second `gh` call.
  provider.refresh().then(() => {
    maybeShowAuthToast(provider.lastAuth);
    // Auto-focus AFTER the first load so the repo lens filters against populated
    // data immediately (setLens works off the cached export).
    void autoFocusRepo();
  }, (err: unknown) => {
    if (err instanceof CliError) {
      vscode.window.showErrorMessage(
        `Work Plan: CLI not found or failed to run (${err.message}). ` +
        `Install from ${TOOLKIT_URL} or set workPlan.cliPath in settings.`,
      );
    } else {
      vscode.window.showErrorMessage(
        `Work Plan: Initial load failed — ${String(err)}`,
      );
    }
  });

  // Version compatibility check.
  checkVersion(runner).then(({ ok, version }) => {
    if (!ok) {
      vscode.window
        .showWarningMessage(
          `Work Plan: CLI version "${version ?? "unknown"}" may be incompatible with this extension. ` +
          `Update the work-plan toolkit to the latest version.`,
          "Update",
        )
        .then((choice) => {
          if (choice === "Update") {
            vscode.env.openExternal(vscode.Uri.parse(TOOLKIT_URL)).then(
              undefined,
              () => { /* ignore */ },
            );
          }
        }, () => { /* ignore */ });
    }
  }).catch((err: unknown) => {
    if (err instanceof CliError) {
      // CLI not available — already reported by the refresh above.
      // Don't double-report; a single clear message is enough.
    } else {
      // Unexpected error in version check — log silently (non-fatal).
      console.error("Work Plan: version check failed:", err);
    }
  });

}

// One-time guard for the activation auth toast (#auth) — the persistent
// viewsWelcome banner is the durable surface; the toast nudges only once.
let authToastShown = false;

/**
 * The one-time GitHub-auth nudge (#auth): a single toast (mirrors the
 * version-check toast) shown when the activation probe found we're not signed
 * in, so the user notices even with the Tracks view unfocused. Authenticated →
 * nothing. gh-missing and not-signed-in get distinct copy + actions. Shown at
 * most once per window session; the viewsWelcome banner is the durable surface.
 */
function maybeShowAuthToast(auth: AuthState | null): void {
  if (authToastShown || !auth || auth.authenticated) return;
  authToastShown = true;
  if (!auth.cliPresent) {
    // #402: the work-plan CLI itself wasn't found on the extension host's PATH
    // (commonly Remote-WSL, where the host runs in WSL but the CLI was installed
    // on Windows). This is NOT a GitHub-auth problem — point at the CLI install.
    vscode.window
      .showWarningMessage(
        "Work Plan: the work-plan CLI wasn't found on this machine's PATH — install it (in the same environment VS Code runs in, e.g. inside WSL) with: npm install -g @stylusnexus/work-plan",
        "Install instructions",
      )
      .then((c) => {
        if (c === "Install instructions") {
          void vscode.env.openExternal(vscode.Uri.parse(TOOLKIT_URL));
        }
      }, () => { /* ignore */ });
  } else if (!auth.ghPresent) {
    vscode.window
      .showWarningMessage(
        "Work Plan: GitHub CLI (gh) not found — issue data is unavailable.",
        "Install gh",
      )
      .then((c) => {
        if (c === "Install gh") void vscode.commands.executeCommand("workPlan.openGhInstallDocs");
      }, () => { /* ignore */ });
  } else if (!auth.probeOk) {
    // The probe ran but returned no trustworthy answer — a CLI runtime /
    // dependency problem (e.g. an older launcher gating the probe behind a
    // missing yq), NOT a sign-in state. Surface the launcher's own reason and
    // offer Retry instead of sending the user into a futile sign-in loop.
    const detail = auth.error ? ` (${auth.error})` : "";
    vscode.window
      .showWarningMessage(
        `Work Plan: couldn't verify GitHub sign-in — the work-plan CLI didn't return a result${detail}. Check its dependencies (gh, git, yq), then Retry.`,
        "Retry",
      )
      .then((c) => {
        if (c === "Retry") void vscode.commands.executeCommand("workPlan.checkGitHubAuth");
      }, () => { /* ignore */ });
  } else {
    vscode.window
      .showWarningMessage(
        "Work Plan: Not signed in to GitHub — issue data is unavailable. Sign in to load tracks.",
        "Sign in",
      )
      .then((c) => {
        if (c === "Sign in") void vscode.commands.executeCommand("workPlan.signInToGitHub");
      }, () => { /* ignore */ });
  }
}

export function deactivate(): void {
  // Subscriptions are disposed automatically by VS Code via context.subscriptions.
}
