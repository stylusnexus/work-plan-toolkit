---
track: cli-viewer-cross
status: active
launch_priority: P0
milestone_alignment: v1.0.0
github:
  repo: stylusnexus/work-plan-toolkit
  issues:
    - 271
    - 280
    - 285
    - 324
    - 328
    - 329
    - 330
    - 349
  branches: []
depends_on: []
last_touched: 2026-06-15T21:09
last_handoff: 2026-06-15T21:09
next_up:
  - 330
  - 329
  - 328
blockers: []
tier: shared
---
# cli-viewer-cross

## Session log

### Session — 2026-06-15 21:09

- Touched: chore(cli-viewer-cross): slot #330 + #349 into the track (8738ff5)
- Touched: feat(vscode): graph zoom/pan/fit + SVG/PNG export (#216) (#353) (211d8aa)
- Touched: feat(vscode): graph zoom/pan/fit + SVG/PNG export (#216) (9b7dbc7)
- Touched: chore(npm): drop redundant postinstall script for npm 12 default-deny compatibility (#344) (8dec257)
- Touched: chore(npm): drop redundant postinstall script for npm 12 default-deny (6f74481)
- Touched: fix(vscode): real GitHub href on issue links — clicking scrolled instead of opening (#324 follow-up) (e06c4f1)
- Touched: Merge pull request #323 from stylusnexus/dev (6579bf7)
- Touched: Merge pull request #322 from stylusnexus/fix/271-hot-branch-perf (5e55e68)
- Touched: fix(git_state): batch hot-branch detection — was O(branches) git calls per track (#271) (79164e8)
- Touched: Merge pull request #319 from stylusnexus/dev (ef58902)
- Touched: feat: issue-level in-progress (#271) (#317) (89843cf)
- Touched: docs(vscode): correct v0.8.0 CLI requirement to 2026.06.14 (#271 review) (3857898)
- Touched: fix(in-progress): toggle reflects label state, not the union signal (#271 review) (dab0ee8)
- Touched: fix(export): key issues_by_track by (repo,name) so same-named cross-repo tracks don't bleed (#271 review) (11932ef)
- Touched: fix(in-progress): reject --repo that doesn't track the issue (#271 review) (d290042)
- Touched: docs: document in-progress command + correct GitHub-mutation inventory (#271) (e8e1673)
- Touched: chore(vscode): require CLI 2026.06.14 + bump extension to 0.8.0 (#271) (8f377e7)
- Touched: fix(vscode): extract + test webview message guard so dropped messages can't recur (#305, #285) (c5d58ec)
- Touched: feat(vscode): detail-webview in-progress toggle via postMessage (#271) (423cdf5)
- Touched: feat(work_plan): register in-progress subcommand (#271) (149da7e)
- Touched: feat(in-progress): repo-qualified command behind confirm gate (#271) (4ca9f48)
- Touched: feat(github_state): set_issue_in_progress label writer (#271) (bf34ca6)
- Touched: feat(vscode): in-progress badge on tracked issue rows (#271) (9fe9f85)
- Touched: feat(orient): mark in-progress on next pick + behind-it rows (#271) (117564a)
- Touched: test(list-open-issues): expect in_progress field on shared issue surface (#271) (10d0a95)
- Touched: feat(brief): mark in-progress issues in the next-up list (#271) (78f8712)
- Touched: feat(export): compute per-track branch heat for in_progress (#271) (c602ddd)
- Touched: feat(export_model): thread per-issue in_progress keyed by (repo,name) (#271) (f8262a5)
- Touched: feat(github_state): fetch labels in lean GQL set for in-progress signal (#271) (b6281ea)
- Touched: feat(in_progress): union-merge issue in-progress signal (#271) (1ab0c52)
- Touched: feat(git_state): map hot feat/fix branches to issue numbers (#271) (a37825a)
- Touched: feat: declared track↔plan link + viewer navigation (#285) (#302) (20e085d)
- Next: (open)

### Session — 2026-06-15 21:09

- Touched: (no git activity attributed; 5 open from GitHub)
- Next: #330 design: track cleanup/deletion flow + clear deletion confirmation in VS Code
- Next: #329 feat: Mark a track for cleanup/deletion — CLI + VS Code menu
- Next: #328 feat: Archive a track — CLI command + VS Code track menu
