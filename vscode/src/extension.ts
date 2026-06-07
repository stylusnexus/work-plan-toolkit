import * as vscode from "vscode";
import { exportJson, makeSpawnRunner, CliError } from "./cli.ts";
import { WorkPlanTreeProvider } from "./tree.ts";
import type { Track } from "./model.ts";

export function activate(context: vscode.ExtensionContext): void {
  // Build the production runner from the configured CLI path.
  const cliPath = vscode.workspace
    .getConfiguration("workPlan")
    .get<string>("cliPath", "work-plan");
  const run = makeSpawnRunner(cliPath);

  // Wire up the tree provider.
  const provider = new WorkPlanTreeProvider(() => exportJson(run));

  context.subscriptions.push(
    vscode.window.createTreeView("workPlan.tree", {
      treeDataProvider: provider,
    })
  );

  // workPlan.refresh — loads data from CLI and refreshes the tree.
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.refresh", () => {
      provider.refresh().catch((err: unknown) => {
        const msg =
          err instanceof CliError
            ? `Work Plan: ${err.message}`
            : `Work Plan: refresh failed — ${String(err)}`;
        vscode.window.showErrorMessage(msg);
      });
    })
  );

  // workPlan.openTrack — will open a track detail webview in Task 8.
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.openTrack",
      (_track?: Track) => {
        // Full webview implementation in Task 8.
        vscode.window.showInformationMessage(
          `Work Plan: Open track — coming in Task 8.`
        );
      }
    )
  );

  // workPlan.openIssue — will open the GitHub issue URL in Task 8.
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.openIssue",
      (issueNumber?: number) => {
        vscode.window.showInformationMessage(
          `Work Plan: Open issue #${issueNumber ?? "?"} — coming in Task 8.`
        );
      }
    )
  );
}

export function deactivate(): void {
  // Nothing to clean up in the scaffold — subscriptions are disposed automatically.
}
