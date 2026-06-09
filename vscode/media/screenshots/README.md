# Screenshots — drop your PNGs here with these EXACT names

These power the README / Marketplace / Open VSX listing. Save each as a PNG with
the exact filename below (case-sensitive). Recommended: **~1200–1600 px wide**,
your dark theme is great, crop tight to the relevant UI.

| Filename | What to capture |
|---|---|
| `sidebar-tree.png` | The **Work Plan sidebar** — repos → tracks, status dots, open counts, the ⚠ badge on the public repo. (You basically already have this.) |
| `dependency-graph.png` | The **Mermaid dependency/flow graph + detail panel** — click a track so it's highlighted, with the issue table/blockers/next-up visible. |
| `write-confirm-modal.png` | The **public-repo confirm modal** — right-click `work-plan-viewer` → Edit Track Fields → change status, capture the "Write anyway / Keep private" dialog. |
| `untracked-bucket.png` | A repo's **⊘ Untracked (N)** node expanded, showing open issues in no track (right-click → Slot into a track). |
| `onboarding.png` | The **empty-state welcome** — "No work-plan repos yet" with the **Add a repo** / **Set notes location** buttons. (Point `cliPath` at a fresh config to reproduce, or you already have it.) |
| `command-menu.png` | The view-title **`⋯` overflow menu** open — New Track / Add Repo / Set Notes Location / Run Hygiene. |

After dropping them in:
1. Bump `vscode/package.json` `version` to `0.1.1`.
2. Re-run the **Publish VS Code Extension** workflow (or cut a Release) — the listing updates with the images.

The README references these by absolute `raw.githubusercontent.com/.../main/...`
URLs (the Marketplace doesn't resolve relative image paths), so they render on
the listing once committed to `main`. Delete any README reference you don't have
a shot for, so there are no broken images.
