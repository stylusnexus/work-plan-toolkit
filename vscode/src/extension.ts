import * as vscode from "vscode";
import { exportJson, makeSpawnRunner, checkVersion, CliError } from "./cli.ts";
import { WorkPlanTreeProvider } from "./tree.ts";
import type { Track } from "./model.ts";
import { WorkPlanPanel } from "./webview/panel.ts";

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
  // workPlan.refresh — reload CLI data, refresh tree, re-render panel if open.
  // -------------------------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.refresh", () => {
      provider.refresh().then(() => {
        // If the panel is open, re-render it with the fresh data.
        const panel = WorkPlanPanel.getCurrent();
        const exp = provider.currentExport;
        if (panel && exp && exp.tracks.length > 0) {
          // Re-render preserving the user's selection (first track as fallback).
          panel.render(exp, panel.currentTrackName ?? exp.tracks[0].name);
        }
      }).catch((err: unknown) => {
        const msg =
          err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: refresh failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      });
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
  // On activation: kick off initial data load + version check.
  // NEVER throw out of activate — all async work has its own catch.
  // -------------------------------------------------------------------------

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
