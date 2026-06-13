import * as vscode from "vscode";
import {
  exportJson, listRepoOpenIssues, makeSpawnRunner, checkVersion, checkAuth, CliError,
  isAlreadyExistsError,
  notesVcsStatus, notesVcsRun, notesVcsUndo,
} from "./cli.ts";
import type { NotesVcsStatus, AuthState } from "./cli.ts";
import { WorkPlanTreeProvider } from "./tree.ts";
import { PlansProvider } from "./plansTree.ts";
import { ackKey, unregisteredTrackRepos } from "./planModel.ts";
import type { Lens, TrackNode, UntrackedIssueNode, UntrackedGroupNode, RepoNode } from "./tree.ts";
import type { Track, Issue } from "./model.ts";
import { trackedIssueNumbers } from "./model.ts";
import { buildIssuePickItems } from "./issuePick.ts";
import { WorkPlanPanel } from "./webview/panel.ts";
import { availableLenses, describeView } from "./webview/lenses.ts";
import { searchIssues } from "./webview/search.ts";
import { SearchPanel } from "./webview/searchPanel.ts";
import type { TrackSort } from "./tree.ts";
import { executeWrite } from "./write.ts";
import type { ConfirmPrompt, WriteOutcome } from "./write.ts";

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

  const provider = new WorkPlanTreeProvider(
    () => exportJson(runner),
    () => checkAuth(runner),
  );

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

  // -------------------------------------------------------------------------
  // refreshAndRerender — shared helper: reload CLI data + re-render panel.
  // Defined here so workPlan.refresh and all write commands share one copy.
  // -------------------------------------------------------------------------

  const refreshAndRerender = async (): Promise<void> => {
    await provider.refresh();
    const panel = WorkPlanPanel.getCurrent();
    const exp = provider.currentExport;
    if (panel && exp && exp.tracks.length > 0) {
      panel.render(exp, panel.currentTrackName ?? exp.tracks[0].name);
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

      const pick = await vscode.window.showQuickPick(items, {
        placeHolder: "Filter the Work Plan view",
      });

      if (!pick) {
        return;
      }

      provider.setLens(pick.lens);

      // If the panel is open, re-render it from the (now-filtered) export.
      const panel = WorkPlanPanel.getCurrent();
      const filteredExp = provider.currentExport;
      if (panel && filteredExp) {
        const currentTrack = panel.currentTrackName;
        // If the current track was filtered out, fall back to the first visible one.
        const trackStillVisible =
          currentTrack !== null &&
          filteredExp.tracks.some(t => t.name === currentTrack);
        const trackToRender = trackStillVisible
          ? currentTrack!
          : filteredExp.tracks[0]?.name ?? null;
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
            const trackName = track?.name ?? (freshExp.tracks[0]?.name ?? "");
            if (trackName) {
              panel.render(freshExp, trackName);
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
        const trackName = track?.name ?? (exp.tracks[0]?.name ?? "");
        if (trackName) {
          panel.render(exp, trackName);
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
        const uri = vscode.Uri.joinPath(vscode.Uri.file(arg.local), arg.rel);
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
          vscode.window.showInformationMessage(
            res.issues.length > 0
              ? `Work Plan: ${res.issues.length} open issue(s) in ${repo}.`
              : `Work Plan: no open issues in ${repo}.`,
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
      } else if (auth && !auth.ghPresent) {
        vscode.window.showWarningMessage(
          "Work Plan: GitHub CLI (gh) not found — install it, then Retry.",
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
    // workPlan.closeIssue (#305) — the only GitHub-mutating action. Accepts an
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
  WorkPlanPanel.setMoveHandler(async (issue, fromTrack, toTrack) => {
    try {
      const outcome: WriteOutcome = await withWriteProgress(
        `Work Plan: moving #${issue} to ${toTrack}…`,
        () => executeWrite(
          runner,
          { kind: "move", fromTrack, toTrack, issue },
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
    const currentTrack = panel.currentTrackName;
    const trackStillVisible =
      currentTrack !== null && exp.tracks.some(t => t.name === currentTrack);
    const trackToRender = trackStillVisible ? currentTrack! : exp.tracks[0]?.name ?? null;
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

  // Resolve a track name: use the node (context-menu) or fall back to a QuickPick.
  const resolveTrackName = async (node?: TrackNode): Promise<string | undefined> => {
    if (node?.name) {
      return node.name;
    }
    const exp = provider.currentExport;
    if (!exp || exp.tracks.length === 0) {
      vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
      return undefined;
    }
    return vscode.window.showQuickPick(
      exp.tracks.map(t => t.name),
      { placeHolder: "Select a track" },
    );
  };

  // -------------------------------------------------------------------------
  // workPlan.editFields — edit a named field on a track (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.editFields", async (node?: TrackNode) => {
      try {
        const track = await resolveTrackName(node);
        if (!track) return;

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
        } else {
          value = await vscode.window.showInputBox({ prompt: `New value for ${field}` });
        }

        if (value === undefined) return; // cancelled

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: setting ${field} on ${track}…`,
          () => executeWrite(
            runner,
            { kind: "editFields", track, fields: { [field]: value } },
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
        const track = await resolveTrackName(node);
        if (!track) return;

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
        const trackObj = exp.tracks.find(t => t.name === track);
        if (!trackObj) {
          vscode.window.showErrorMessage(`Work Plan: Track "${track}" not found.`);
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
            { kind: "setNext", track, issues },
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
  // workPlan.refreshMd — refresh a track's body markdown (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.refreshMd", async (node?: TrackNode) => {
      try {
        const track = await resolveTrackName(node);
        if (!track) return;

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Work Plan: refreshing ${track}…`,
            cancellable: false,
          },
          async () => {
            const outcome: WriteOutcome = await executeWrite(
              runner,
              { kind: "refresh", track },
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
        const track = await resolveTrackName(node);
        if (!track) return;

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Work Plan: reconciling ${track} (draft)…`,
            cancellable: false,
          },
          async () => {
            const outcome: WriteOutcome = await executeWrite(
              runner,
              { kind: "reconcileDraft", track },
              confirmPublicWrite,
            );

            if (outcome.status === "written") {
              outputChannel.clear();
              outputChannel.append(outcome.stdout);
              outputChannel.show(true);
              vscode.window.showInformationMessage(
                "Work Plan: label-drift preview (draft) — see the Work Plan output channel.",
              );
            } else {
              vscode.window.showInformationMessage("Work Plan: kept private — no change written.");
            }
          },
        );
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
        const track = await resolveTrackName(node);
        if (!track) return;

        // Resolve the track's repo + current issues so we can offer the repo's
        // OPEN issues as a pick-list, excluding ones already in the track (#282).
        const exp = provider.rawExport ?? provider.currentExport;
        const trackObj = exp?.tracks.find(t => t.name === track);
        const repo = trackObj?.repo;

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
            { kind: "slot", track, issue },
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
        const fromTrack = await resolveTrackName(node);
        if (!fromTrack) return;

        // Load the export FIRST so we can offer the source track's issues as a
        // pick-list instead of asking the user to retype a number (#212).
        const exp = provider.rawExport ?? provider.currentExport;
        if (!exp || exp.tracks.length === 0) {
          vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
          return;
        }

        // Find the source track object — for its issues and its repo.
        const srcTrack = exp.tracks.find(t => t.name === fromTrack);
        if (!srcTrack) {
          vscode.window.showErrorMessage(`Work Plan: Track "${fromTrack}" not found.`);
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
            { kind: "move", fromTrack, toTrack, issue },
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

        const track = await vscode.window.showQuickPick(
          candidateTracks.map(t => t.name),
          { placeHolder: `Slot #${issue} into a track` },
        );
        if (!track) return; // cancelled

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: adding #${issue} to ${track}…`,
          () => executeWrite(
            runner,
            { kind: "slot", track, issue },
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

        const track = await vscode.window.showQuickPick(
          candidateTracks.map(t => t.name),
          { placeHolder: `Slot ${issueNumbers.length} issue(s) into a track` },
        );
        if (!track) return; // cancelled

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: adding ${issueNumbers.length} issue(s) to ${track}…`,
          () => executeWrite(
            runner,
            { kind: "batchSlot", track, issues: issueNumbers },
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
  // workPlan.close — close a track with a state (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.close", async (node?: TrackNode) => {
      try {
        const track = await resolveTrackName(node);
        if (!track) return;

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
            { kind: "close", track, state: state as "shipped" | "parked" | "abandoned", ...(note ? { note } : {}) },
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
        const track = await resolveTrackName(node);
        if (!track) return;

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
            { kind: "renameTrack", track, newSlug },
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
            { kind: "pushTrack", track: track.name, repoKey: track.folder ?? undefined },
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
        const track = await resolveTrackName(node);
        if (!track) return;
        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Work Plan: re-orienting on ${track}…`,
            cancellable: false,
          },
          () => runRelay(["where-was-i", "--", track], "where-was-i"),
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
        const track = await resolveTrackName(node);
        if (!track) return;

        const outcome: WriteOutcome = await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Work Plan: wrapping up ${track}…`,
            cancellable: false,
          },
          () => executeWrite(runner, { kind: "handoff", track }, confirmPublicWrite),
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
  );

  const setAck = async (repoKey: string, rel: string, on: boolean): Promise<void> => {
    const k = ackKey(repoKey, rel);
    if (on) ackedPlans.add(k); else ackedPlans.delete(k);
    await context.workspaceState.update(ACK_KEY, [...ackedPlans]);
    plansProvider.rerender();
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.plans.acknowledge",
      (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) =>
        n?.kind === "doc" && n.repoKey && n.doc?.rel
          ? setAck(n.repoKey, n.doc.rel, true)
          : undefined,
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
      async (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) => {
        if (n?.kind !== "doc" || !n.repoKey || !n.doc?.rel) return;
        const { repoKey } = n;
        const rel = n.doc.rel;
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
      async (n?: { kind?: string; repoKey?: string; doc?: { rel?: string } }) => {
        if (n?.kind !== "doc" || !n.repoKey || !n.doc?.rel) return;
        const { repoKey } = n;
        const rel = n.doc.rel;
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
  );

  const plansView = vscode.window.createTreeView("workPlan.plans", {
    treeDataProvider: plansProvider,
  });
  context.subscriptions.push(plansView);

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

  // Initial data load. On success, surface the one-time GitHub-auth nudge off
  // the SAME refresh (which already probed auth + set the context key driving
  // the Tracks welcome banner) — no second `gh` call.
  provider.refresh().then(() => {
    maybeShowAuthToast(provider.lastAuth);
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
  if (!auth.ghPresent) {
    vscode.window
      .showWarningMessage(
        "Work Plan: GitHub CLI (gh) not found — issue data is unavailable.",
        "Install gh",
      )
      .then((c) => {
        if (c === "Install gh") void vscode.commands.executeCommand("workPlan.openGhInstallDocs");
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
