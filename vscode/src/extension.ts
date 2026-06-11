import * as vscode from "vscode";
import {
  exportJson, makeSpawnRunner, checkVersion, CliError,
  notesVcsStatus, notesVcsRun, notesVcsUndo,
} from "./cli.ts";
import type { NotesVcsStatus } from "./cli.ts";
import { WorkPlanTreeProvider } from "./tree.ts";
import type { Lens, TrackNode, UntrackedIssueNode, UntrackedGroupNode } from "./tree.ts";
import type { Track } from "./model.ts";
import { WorkPlanPanel } from "./webview/panel.ts";
import { availableLenses } from "./webview/lenses.ts";
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

  const provider = new WorkPlanTreeProvider(() => exportJson(runner));

  context.subscriptions.push(
    vscode.window.createTreeView("workPlan.tree", {
      treeDataProvider: provider,
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
    const before = notesState?.last_commit_sha ?? null;
    await refreshAndRerender();
    // Skip the extra status spawn when we positively know notes_root isn't a
    // repo (the common feature-off case). A null cache means "unknown" — still
    // check, since the user may have enabled history out-of-band.
    if (notesState && !notesState.is_root) return;
    const after = await notesVcsStatus(runner);
    notesState = after;
    if (
      after &&
      after.auto_commit &&
      after.is_root &&
      after.last_commit_sha &&
      after.last_commit_sha !== before
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
  // workPlan.setNext — set the next-up issue list on a track (context menu + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.setNext", async (node?: TrackNode) => {
      try {
        const track = await resolveTrackName(node);
        if (!track) return;

        const raw = await vscode.window.showInputBox({
          prompt: "Next-up issue numbers (comma-separated)",
          validateInput: (v) => {
            if (/^\s*\d+(\s*,\s*\d+)*\s*$/.test(v)) return null;
            return "Enter at least one issue number, comma-separated (e.g. 42,87). To clear next-up, use Edit Track Fields → next_up.";
          },
        });
        if (raw === undefined) return; // cancelled

        if (raw.trim() === "") return;
        const issues = raw.split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n));
        if (issues.length === 0) return;

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
          vscode.window.showInformationMessage(`Work Plan: set next-up on ${track}`);
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
  // workPlan.reconcile — draft reconcile preview (context menu + palette)
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
                "Work Plan: reconcile preview (draft) — see the Work Plan output channel.",
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

        const raw = await vscode.window.showInputBox({
          prompt: `Issue number to slot into ${track}`,
          validateInput: (v) => {
            if (/^\d+$/.test(v) && parseInt(v, 10) > 0) return null;
            return "Enter a positive integer issue number (e.g. 42)";
          },
        });
        if (raw === undefined) return; // cancelled

        const issue = parseInt(raw, 10);

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: slotting #${issue} into ${track}…`,
          () => executeWrite(
            runner,
            { kind: "slot", track, issue },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: slotted #${issue} into ${track}`);
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

        const raw = await vscode.window.showInputBox({
          prompt: `Issue number to move from ${fromTrack}`,
          validateInput: (v) => {
            if (/^\d+$/.test(v) && parseInt(v, 10) > 0) return null;
            return "Enter a positive integer issue number (e.g. 42)";
          },
        });
        if (raw === undefined) return; // cancelled

        const issue = parseInt(raw, 10);

        // Build the destination track list from the RAW export.
        const exp = provider.rawExport ?? provider.currentExport;
        if (!exp || exp.tracks.length === 0) {
          vscode.window.showErrorMessage("Work Plan: No tracks loaded — run Refresh first.");
          return;
        }

        // Find the source track object to determine its repo.
        const srcTrack = exp.tracks.find(t => t.name === fromTrack);
        if (!srcTrack) {
          vscode.window.showErrorMessage(`Work Plan: Track "${fromTrack}" not found.`);
          return;
        }

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
          { placeHolder: `Move #${issue} from ${fromTrack} to...` },
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
          `Work Plan: slotting #${issue} into ${track}…`,
          () => executeWrite(
            runner,
            { kind: "slot", track, issue },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: slotted #${issue} into ${track}`);
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
          `Work Plan: slotting ${issueNumbers.length} issue(s) into ${track}…`,
          () => executeWrite(
            runner,
            { kind: "batchSlot", track, issues: issueNumbers },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: slotted ${issueNumbers.length} issue(s) into ${track}`);
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
  );

  // -------------------------------------------------------------------------
  // workPlan.newTrack — create a new track (view/title overflow + palette)
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.newTrack", async () => {
      try {
        // --- Repo selection ---
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

        let repo: string | undefined;

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
    vscode.commands.registerCommand("workPlan.addRepo", async () => {
      try {
        const key = await vscode.window.showInputBox({
          prompt: "Short repo key (lowercase, e.g. my-project)",
          validateInput: (v) =>
            /^[a-z][a-z0-9-]*$/.test(v) ? null : "Key must be lowercase, start with a letter, e.g. my-project",
        });
        if (key === undefined) return; // cancelled

        const github = await vscode.window.showInputBox({
          prompt: "GitHub repo (org/repo)",
          validateInput: (v) =>
            /^[\w.-]+\/[\w.-]+$/.test(v) ? null : "Enter an org/repo slug, e.g. your-org/myproject",
        });
        if (github === undefined) return; // cancelled

        const localRaw = await vscode.window.showInputBox({
          prompt: "Local checkout path (optional — press Enter or Escape to skip)",
        });
        // undefined (Esc) or empty → omit local
        const local = localRaw && localRaw.trim() !== "" ? localRaw.trim() : undefined;

        const outcome: WriteOutcome = await withWriteProgress(
          `Work Plan: adding repo ${github}…`,
          () => executeWrite(
            runner,
            { kind: "addRepo", key, github, ...(local ? { local } : {}) },
            confirmPublicWrite,
          ),
        );

        if (outcome.status === "written") {
          await refreshAfterWrite();
          vscode.window.showInformationMessage(`Work Plan: added repo ${github} (${key})`);
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
          placeHolder: "Work Plan: local history (private notes_root tier)",
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

  // Initial data load.
  provider.refresh().catch((err: unknown) => {
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

export function deactivate(): void {
  // Subscriptions are disposed automatically by VS Code via context.subscriptions.
}
