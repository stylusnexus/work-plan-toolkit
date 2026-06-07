import * as vscode from "vscode";

export function activate(context: vscode.ExtensionContext): void {
  // workPlan.refresh — will be wired to the tree provider in Task 6.
  context.subscriptions.push(
    vscode.commands.registerCommand("workPlan.refresh", () => {
      vscode.window.showInformationMessage("Work Plan: Refresh triggered.");
    })
  );

  // workPlan.openTrack — will open a track detail webview in Task 7.
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "workPlan.openTrack",
      (trackName?: string) => {
        vscode.window.showInformationMessage(
          `Work Plan: Open track "${trackName ?? "(none)"}" — coming in Phase 2.`
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
          `Work Plan: Open issue #${issueNumber ?? "?"} — coming in Phase 2.`
        );
      }
    )
  );
}

export function deactivate(): void {
  // Nothing to clean up in the scaffold — subscriptions are disposed automatically.
}
