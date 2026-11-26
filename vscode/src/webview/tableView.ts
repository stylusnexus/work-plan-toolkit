/**
 * Filter, sort and row limit for the viewer's issue tables (#598).
 *
 * `computeTableView` is inlined into the webview script via `Function#toString`,
 * so it must stay self-contained: ES5 constructs only, no outer references, no
 * backslashes or double quotes (the script is a template literal).
 */

import type { IssueStates } from "./stateFilter.ts";

export interface TableRow {
  num: number; title: string; state: "open" | "closed";
  inProgress: boolean; assignees: string[]; group: number;
}
export type SortCol = "num" | "title" | "state" | "assignee";
export interface TableQuery {
  states: IssueStates;
  titleText: string;
  /** null = no filter; [] = none checked; "__unassigned__" = no assignee. */
  assignees: string[] | null;
  sort: { col: SortCol; dir: "asc" | "desc" } | null;
  showAll: boolean;
}
export interface TableViewResult {
  /** Every row index: by group, then sort. */
  order: number[];
  /** By row index: matches and is within the limit. */
  shown: boolean[];
  total: number;
  matched: number;
  overLimit: number;
  groups: { total: number; matched: number }[];
}

export function computeTableView(rows: TableRow[], q: TableQuery, cap: number): TableViewResult {
  var none = '__unassigned__';
  var i;
  var present = {} as Record<string, boolean>;
  for (i = 0; i < rows.length; i++) {
    if (rows[i].assignees.length === 0) { present[' ' + none] = true; }
    for (var a = 0; a < rows[i].assignees.length; a++) { present[' ' + rows[i].assignees[a]] = true; }
  }
  // A saved name with no rows left is dropped; if that empties the filter, it is off.
  var picked = q.assignees;
  if (picked !== null && picked.length > 0) {
    var kept = picked.filter(function (n) { return present[' ' + n] === true; });
    picked = kept.length > 0 ? kept : null;
  }
  var text = q.titleText.toLowerCase();
  function matches(r: TableRow): boolean {
    if (!q.states[r.state]) { return false; }
    if (text !== '' && r.title.toLowerCase().indexOf(text) < 0) { return false; }
    if (picked === null) { return true; }
    var mine = r.assignees.length > 0 ? r.assignees : [none];
    return mine.some(function (n) { return (picked as string[]).indexOf(n) >= 0; });
  }
  function compare(x: string | number, y: string | number): number { return x < y ? -1 : (x > y ? 1 : 0); }
  function key(r: TableRow, col: SortCol): string | number {
    if (col === 'title') { return r.title.toLowerCase(); }
    if (col === 'state') { return r.state === 'closed' ? 2 : (r.inProgress ? 0 : 1); }
    if (col === 'assignee') { return (r.assignees[0] || '').toLowerCase(); }
    return r.num;
  }
  var order = rows.map(function (_r, n) { return n; });
  order.sort(function (x, y) {
    var l = rows[x];
    var r = rows[y];
    if (l.group !== r.group) { return l.group - r.group; }
    if (q.sort === null) { return x - y; }
    if (q.sort.col === 'assignee') {
      var lNone = l.assignees.length === 0;
      var rNone = r.assignees.length === 0;
      if (lNone !== rNone) { return lNone ? 1 : -1; }
    }
    var c = compare(key(l, q.sort.col), key(r, q.sort.col));
    if (c !== 0) { return q.sort.dir === 'desc' ? -c : c; }
    return l.num - r.num;
  });
  var shown = rows.map(function () { return false; });
  var groups = [] as { total: number; matched: number }[];
  var matched = 0;
  var overLimit = 0;
  for (i = 0; i < order.length; i++) {
    var row = rows[order[i]];
    while (groups.length <= row.group) { groups.push({ total: 0, matched: 0 }); }
    groups[row.group].total++;
    if (!matches(row)) { continue; }
    groups[row.group].matched++;
    matched++;
    if (q.showAll || matched <= cap) { shown[order[i]] = true; } else { overLimit++; }
  }
  return { order: order, shown: shown, total: rows.length, matched: matched, overLimit: overLimit, groups: groups };
}
