/**
 * Plain-text copy of a traced issue flow (#445).
 *
 * `buildFlowText` is inlined into the webview script via `Function#toString`,
 * so it must stay self-contained: ES5 constructs only, no outer references, no
 * backslashes or double quotes (the script is a template literal).
 */

export type FlowFormat = "paths" | "tasks" | "order";

/**
 * @param links   drawn links as [from, to] Mermaid node ids
 * @param titles  node id -> hover text; line 1 is "#N title", a later line "State: ..."
 * @param focus   the picked node id
 * @param format  paths: one "#1 → #2" line per path plus an Order line;
 *                tasks: markdown task list; order: numbered list. Both with titles.
 */
export function buildFlowText(
  links: [string, string][],
  titles: Record<string, string>,
  focus: string,
  format: FlowFormat,
): string {
  // Above this many root-to-leaf paths the paths format falls back to the work-order list.
  var cap = 30;
  function text(id: string): string { return titles && titles[id] ? String(titles[id]) : id; }
  function first(id: string): string { return text(id).split(String.fromCharCode(10))[0]; }
  function num(id: string): string {
    var f = first(id);
    var sp = f.indexOf(' ');
    return sp > 0 ? f.slice(0, sp) : f;
  }
  function title(id: string): string {
    var f = first(id);
    var sp = f.indexOf(' ');
    return sp > 0 ? f.slice(sp + 1) : '';
  }
  function n(id: string): number {
    var v = parseInt(num(id).replace('#', ''), 10);
    return isNaN(v) ? 0 : v;
  }
  function closed(id: string): boolean { return text(id).indexOf('State: closed') >= 0; }
  function inProgress(id: string): boolean { return text(id).indexOf('in progress') >= 0; }
  function reach(start: string, dir: boolean): Record<string, boolean> {
    var seen: Record<string, boolean> = {};
    seen[start] = true;
    var queue = [start];
    while (queue.length) {
      var cur = queue.pop() as string;
      for (var i = 0; i < links.length; i++) {
        var a = dir ? links[i][0] : links[i][1];
        var b = dir ? links[i][1] : links[i][0];
        if (a === cur && !seen[b] && !closed(b)) { seen[b] = true; queue.push(b); }
      }
    }
    return seen;
  }
  var up = reach(focus, false);
  var down = reach(focus, true);
  // Links on the lineage only: both ends upstream of the pick, or both downstream.
  var edges: [string, string][] = [];
  for (var i = 0; i < links.length; i++) {
    var l = links[i];
    if ((up[l[0]] && up[l[1]]) || (down[l[0]] && down[l[1]])) { edges.push(l); }
  }
  function chains(start: string, dir: boolean): string[][] {
    var out: string[][] = [];
    function walk(cur: string, path: string[]): void {
      if (out.length > cap) { return; }
      var next: string[] = [];
      for (var k = 0; k < edges.length; k++) {
        var a = dir ? edges[k][0] : edges[k][1];
        var b = dir ? edges[k][1] : edges[k][0];
        if (a === cur && path.indexOf(b) < 0 && next.indexOf(b) < 0) { next.push(b); }
      }
      next.sort(function (x, y) { return n(x) - n(y); });
      if (!next.length) { out.push(path); return; }
      for (var m = 0; m < next.length; m++) { walk(next[m], path.concat([next[m]])); }
    }
    walk(start, [start]);
    return out;
  }
  // Paths read in issue-number order, so repeated copies of the same flow are identical.
  function byNumber(x: string[], y: string[]): number {
    for (var k = 0; k < x.length && k < y.length; k++) {
      if (n(x[k]) !== n(y[k])) { return n(x[k]) - n(y[k]); }
    }
    return x.length - y.length;
  }
  var ups = chains(focus, false).map(function (p) { return p.slice().reverse(); }).sort(byNumber);
  var downs = chains(focus, true).sort(byNumber);
  // Work order: Kahn's algorithm over the lineage, ties by issue number.
  var nodes: string[] = [];
  Object.keys(up).concat(Object.keys(down)).forEach(function (id) { if (nodes.indexOf(id) < 0) { nodes.push(id); } });
  var indeg: Record<string, number> = {};
  nodes.forEach(function (id) { indeg[id] = 0; });
  edges.forEach(function (e) { indeg[e[1]]++; });
  var order: string[] = [];
  var done: Record<string, boolean> = {};
  var ready = nodes.filter(function (id) { return indeg[id] === 0; });
  while (ready.length) {
    ready.sort(function (x, y) { return n(x) - n(y); });
    var cur = ready.shift() as string;
    order.push(cur);
    done[cur] = true;
    edges.forEach(function (e) {
      if (e[0] === cur && --indeg[e[1]] === 0) { ready.push(e[1]); }
    });
  }
  nodes.filter(function (id) { return !done[id]; })
    .sort(function (x, y) { return n(x) - n(y); })
    .forEach(function (id) { order.push(id); });
  var arrow = ' ' + String.fromCharCode(8594) + ' ';
  var nl = String.fromCharCode(10);
  function titled(id: string): string {
    var t = num(id) + ' ' + title(id);
    if (id === focus) { t += ' (this)'; }
    if (inProgress(id)) { t += ' (in progress)'; }
    return t;
  }
  var pathCount = ups.length * downs.length;
  if (format === 'paths' && pathCount <= cap) {
    var lines: string[] = [];
    ups.forEach(function (u) {
      downs.forEach(function (d) {
        lines.push(u.concat(d.slice(1)).map(num).join(arrow));
      });
    });
    if (lines.length > 1) { lines.push('Order: ' + order.map(num).join(', ')); }
    return lines.join(nl);
  }
  if (format === 'tasks') {
    return order.map(function (id) { return '- [ ] ' + titled(id); }).join(nl);
  }
  return order.map(function (id, k) { return (k + 1) + '. ' + titled(id); }).join(nl);
}
