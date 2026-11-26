/**
 * Page behaviour for the issue tables: sort and filter menus, row limit,
 * milestone groups, saved choices and focus (#598).
 *
 * `setupIssueTable` is inlined into the webview script via `Function#toString`,
 * so it must stay self-contained: no outer references, no backslashes or double
 * quotes. The filtering itself is `computeTableView`, passed in.
 */

import type { computeTableView, TableQuery, TableRow, SortCol } from "./tableView.ts";
import type { IssueStates } from "./stateFilter.ts";

export interface TableEnv {
  // Loosely typed: the extension compiles without the DOM library.
  document: any;
  vscode: { getState?: () => any; setState: (s: unknown) => void } | null;
  post: (message: unknown) => void;
  states: IssueStates;
  trackKey: string;
  cap: number;
  window: any;
}

export function setupIssueTable(env: TableEnv, compute: typeof computeTableView): void {
  var doc = env.document;
  var table = doc.getElementById('work-plan-issues') as any;
  if (!table) { return; }
  var NONE = '__unassigned__';
  var states = env.states;
  var labels = { num: 'Num', title: 'Title', state: 'State', assignee: 'Assignee' } as Record<string, string>;

  function list(root: any, selector: string): any[] { return Array.prototype.slice.call(root.querySelectorAll(selector)); }
  function byId(id: string): any { return doc.getElementById(id); }

  function readRows(root: any): { rows: TableRow[]; els: any[]; deps: any[] } {
    var rows = [] as TableRow[];
    var els = [] as any[];
    var deps = [] as any[];
    list(root, '.issue-row').forEach(function (el) {
      var next = el.nextElementSibling;
      els.push(el);
      deps.push(next && next.classList.contains('dep-detail-row') ? next : null);
      rows.push({
        num: Number(el.getAttribute('data-num')),
        title: el.getAttribute('data-title') || '',
        state: el.getAttribute('data-state') === 'closed' ? 'closed' : 'open',
        inProgress: el.getAttribute('data-wip') === '1',
        assignees: (el.getAttribute('data-assignees') || '').split(' ').filter(Boolean),
        group: Number(el.closest('tbody').getAttribute('data-group')) || 0,
      });
    });
    return { rows: rows, els: els, deps: deps };
  }

  var owned = readRows(table);
  var refsTable = byId('work-plan-refs');
  var refs = refsTable ? readRows(refsTable) : null;
  var bodies = list(table, 'tbody').filter(function (b) { return b.getAttribute('data-group') !== null; });
  var banded = bodies.some(function (b) { return b.classList.contains('milestone-band'); });

  // Saved choices. Anything missing or the wrong type falls back to the default.
  var saved = (env.vscode && env.vscode.getState ? env.vscode.getState() : null) as any;
  var raw = saved && typeof saved.table === 'object' && saved.table ? saved.table : {};
  var sameTrack = raw.trackKey === env.trackKey;
  function strings(v: unknown): string[] | null {
    return Array.isArray(v) ? v.filter(function (x) { return typeof x === 'string'; }) : null;
  }
  function numbers(v: unknown): number[] | null {
    return Array.isArray(v) ? v.filter(function (x) { return typeof x === 'number'; }) : null;
  }
  var sort = raw.sort && labels[raw.sort.col] && (raw.sort.dir === 'asc' || raw.sort.dir === 'desc')
    ? { col: raw.sort.col as SortCol, dir: raw.sort.dir as 'asc' | 'desc' } : null;
  var titleText = sameTrack && typeof raw.titleText === 'string' ? raw.titleText as string : '';
  var assignees = sameTrack ? strings(raw.assignees) : null;
  var openGroups = sameTrack ? numbers(raw.openGroups) : null;
  var closedWhileFiltering = (sameTrack ? numbers(raw.closedWhileFiltering) : null) || [];
  var showAll = sameTrack && raw.showAll === true;
  var refsShowAll = sameTrack && raw.refsShowAll === true;
  var openDeps = (sameTrack ? strings(raw.openDeps) : null) || [];
  var focusId = sameTrack && typeof raw.focusId === 'string' ? raw.focusId as string : null;
  var focused = raw.focused === true;
  // The open pop-up and the control in it, so a redraw can bring both back.
  var popCol = sameTrack && (raw.popCol === 'title' || raw.popCol === 'state' || raw.popCol === 'assignee') ? raw.popCol as string : null;
  var popItem = typeof raw.popItem === 'number' ? raw.popItem as number : 0;

  function present(): string[] {
    var names = [] as string[];
    var unassigned = false;
    owned.rows.forEach(function (r) {
      if (r.assignees.length === 0) { unassigned = true; }
      r.assignees.forEach(function (a) { if (names.indexOf(a) < 0) { names.push(a); } });
    });
    names.sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; });
    if (unassigned) { names.push(NONE); }
    return names;
  }
  if (assignees !== null && assignees.length > 0) {
    var kept = assignees.filter(function (a) { return present().indexOf(a) >= 0; });
    assignees = kept.length > 0 ? kept : null;
  }

  function save(): void {
    if (!env.vscode) { return; }
    var all = Object.assign({}, env.vscode.getState ? env.vscode.getState() : null);
    all.table = {
      sort: sort, trackKey: env.trackKey, titleText: titleText, assignees: assignees, openGroups: openGroups,
      closedWhileFiltering: closedWhileFiltering, showAll: showAll, refsShowAll: refsShowAll,
      openDeps: openDeps, focusId: focusId, focused: focused, popCol: popCol, popItem: popItem,
    };
    env.vscode.setState(all);
  }

  function filtering(): boolean {
    return titleText !== '' || assignees !== null || !states.open || states.closed;
  }
  function query(): TableQuery {
    return { states: states, titleText: titleText, assignees: assignees, sort: sort, showAll: showAll };
  }
  function setAttr(el: any, name: string, value: boolean): void { el.setAttribute(name, value ? 'true' : 'false'); }

  function applyRows(set: { els: any[]; deps: any[] }, order: number[], shown: boolean[]): void {
    order.forEach(function (i) {
      var row = set.els[i];
      var dep = set.deps[i];
      var parent = row.parentNode;
      parent.appendChild(row);
      row.hidden = !shown[i];
      if (!dep) { return; }
      parent.appendChild(dep);
      var expanded = openDeps.indexOf(row.getAttribute('data-num')) >= 0;
      var toggle = row.querySelector('.dep-toggle-btn');
      if (toggle) { setAttr(toggle, 'aria-expanded', expanded); }
      dep.hidden = !shown[i] || !expanded;
    });
  }

  function applyCap(root: any, matched: number, all: boolean): void {
    var band = root.querySelector('.issue-cap-band');
    if (!band) { return; }
    var over = matched - env.cap;
    band.hidden = over <= 0;
    if (over <= 0) { return; }
    band.classList.toggle('collapsed', !all);
    setAttr(band.querySelector('.issue-cap-toggle'), 'aria-expanded', all);
    band.querySelector('.issue-cap-label').textContent = 'Show all ' + matched + ' issues (' + over + ' more)';
  }

  function assigneeName(a: string): string { return a === NONE ? 'Unassigned' : a; }

  function render(typing?: boolean): void {
    var view = compute(owned.rows, query(), env.cap);
    applyRows(owned, view.order, view.shown);
    applyCap(table, view.matched, showAll);

    var firstMatch = -1;
    bodies.forEach(function (body) {
      var g = Number(body.getAttribute('data-group'));
      var counts = view.groups[g] || { total: 0, matched: 0 };
      if (firstMatch < 0 && counts.matched > 0) { firstMatch = g; }
      if (!banded) { return; }
      body.hidden = counts.matched === 0;
      var open = filtering() ? closedWhileFiltering.indexOf(g) < 0
        : (openGroups === null ? g === firstMatch : openGroups.indexOf(g) >= 0);
      body.classList.toggle('collapsed', !open);
      setAttr(body.querySelector('.milestone-toggle-btn'), 'aria-expanded', open);
      body.querySelector('.milestone-count').textContent = counts.matched < counts.total
        ? '(' + counts.matched + ' of ' + counts.total + ')' : '(' + counts.total + ')';
    });

    list(table, '.th-sort').forEach(function (button) {
      var col = button.getAttribute('data-col');
      var on = sort !== null && sort.col === col;
      var th = button.closest('th');
      if (on) { th.setAttribute('aria-sort', sort!.dir === 'asc' ? 'ascending' : 'descending'); }
      else { th.removeAttribute('aria-sort'); }
      button.querySelector('.th-arrow').textContent = on ? (sort!.dir === 'asc' ? '↑' : '↓') : '↕';
    });
    list(table, '.th-filter').forEach(function (button) {
      var col = button.getAttribute('data-col');
      var active = (col === 'title' && titleText !== '') || (col === 'assignee' && assignees !== null)
        || (col === 'state' && (!states.open || !states.closed));
      button.setAttribute('aria-label', 'Filter by ' + labels[col] + (active ? ', active' : ''));
      button.querySelector('.th-glyph').textContent = active ? '▼' : '▾';
      button.classList.toggle('active', active);
    });

    var parts = ['Showing ' + view.matched + ' of ' + view.total + ' issues'];
    if (!states.open || !states.closed) {
      parts.push('State: ' + (states.open ? 'Open' : (states.closed ? 'Closed' : 'none')));
    }
    if (titleText !== '') { parts.push('Title: ' + titleText); }
    if (assignees !== null) { parts.push('Assignee: ' + (assignees.map(assigneeName).join(', ') || 'none')); }
    if (sort !== null && banded) { parts.push('sorted within milestones'); }
    byId('work-plan-summary-text').textContent = view.total === 0 ? '' : parts.join(' · ');
    byId('work-plan-clear-filters').hidden = titleText === '' && assignees === null;

    var stateMatches = owned.rows.filter(function (r) { return states[r.state]; }).length;
    var message = '';
    var offerBoth = false;
    if (view.total === 0) { message = 'No owned issues'; }
    else if (!states.open && !states.closed) { message = 'No states are checked.'; offerBoth = true; }
    else if (stateMatches === 0) {
      message = 'No ' + (states.open ? 'open' : 'closed') + ' owned issues. ' + view.total + ' '
        + (states.open ? 'closed' : 'open') + ' are hidden.';
      offerBoth = true;
    } else if (view.matched === 0) { message = 'No issues match these filters.'; }
    byId('work-plan-table-empty').hidden = message === '';
    byId('work-plan-empty-text').textContent = message;
    byId('work-plan-both-states').hidden = !offerBoth;

    if (refs) {
      var refView = compute(refs.rows, { states: states, titleText: '', assignees: null, sort: null, showAll: refsShowAll }, env.cap);
      applyRows(refs, refView.order, refView.shown);
      applyCap(refsTable, refView.matched, refsShowAll);
      var hidden = refView.total - refView.matched;
      var note = byId('work-plan-refs-note');
      note.hidden = hidden === 0;
      note.textContent = hidden + ' referenced ' + (hidden === 1 ? 'issue' : 'issues') + ' hidden by Issue state.';
    }

    var announce = function () {
      byId('work-plan-table-status').textContent = 'Showing ' + view.matched + ' of ' + view.total + ' owned issues';
    };
    if (timer !== null) { env.window.clearTimeout(timer); timer = null; }
    if (typing) { timer = env.window.setTimeout(announce, 500); } else { announce(); }
  }
  var timer = null as any;

  // Filter pop-up: a non-modal dialog with native inputs.
  var pop = null as any;
  var popButton = null as any;
  function closePop(returnFocus: boolean): void {
    if (!pop) { return; }
    pop.remove();
    popButton.setAttribute('aria-expanded', 'false');
    var button = popButton;
    pop = null;
    popButton = null;
    popCol = null;
    save();
    if (returnFocus) { button.focus(); }
  }
  function make(tag: string, parent: any): any { var el = doc.createElement(tag) as any; parent.appendChild(el); return el; }
  function checkbox(parent: any, text: string, checked: boolean, onChange: () => void): any {
    var label = make('label', parent);
    var box = make('input', label);
    box.type = 'checkbox';
    box.checked = checked;
    make('span', label).textContent = ' ' + text;
    box.addEventListener('change', onChange);
    return box;
  }
  function openPop(button: any): void {
    var col = button.getAttribute('data-col');
    var wasOpen = popButton === button;
    closePop(false);
    if (wasOpen) { button.focus(); return; }
    popButton = button;
    popCol = col;
    popItem = 0;
    pop = make('div', doc.body);
    pop.id = 'work-plan-filter-pop';
    pop.className = 'filter-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Filter by ' + labels[col]);
    button.setAttribute('aria-expanded', 'true');
    var first = null as any;
    if (col === 'title') {
      var label = make('label', pop);
      make('span', label).textContent = 'Title contains';
      first = make('input', label);
      first.type = 'text';
      first.value = titleText;
      first.addEventListener('input', function () {
        titleText = first.value;
        closedWhileFiltering = [];
        render(true);
        save();
      });
    } else if (col === 'state') {
      var boxes = [] as any[];
      var change = function () {
        focusId = 'filter:state';
        save();
        env.post({ type: 'setIssueStates', open: boxes[0].checked, closed: boxes[1].checked });
      };
      boxes.push(checkbox(pop, 'Open', states.open, change));
      boxes.push(checkbox(pop, 'Closed', states.closed, change));
      first = boxes[0];
    } else {
      var names = present();
      var checks = [] as any[];
      var pick = function () {
        var on = names.filter(function (_n, i) { return checks[i].checked; });
        assignees = on.length === names.length ? null : on;
        closedWhileFiltering = [];
        render();
        save();
      };
      names.forEach(function (name) {
        checks.push(checkbox(pop, assigneeName(name), assignees === null || assignees.indexOf(name) >= 0, pick));
      });
      first = checks[0] || null;
    }
    var close = make('button', pop);
    close.type = 'button';
    close.className = 'open-file-btn';
    close.textContent = 'Close';
    close.addEventListener('click', function () { closePop(true); });
    // The pop-up sits on the page body, outside the table scroller, so it is not clipped.
    var rect = button.getBoundingClientRect();
    var scrollY = env.window.scrollY || 0;
    var width = env.window.innerWidth || 0;
    pop.style.top = (rect.bottom + scrollY + 2) + 'px';
    pop.style.left = Math.max(4, width ? Math.min(rect.left, width - 240) : rect.left) + 'px';
    pop.addEventListener('keydown', function (e: any) {
      if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); closePop(true); return; }
      if (e.key !== 'Tab') { return; }
      var items = list(pop, 'input, button');
      var edge = e.shiftKey ? items[0] : items[items.length - 1];
      if (e.target === edge) { e.preventDefault(); closePop(true); }
    });
    (first || close).focus();
    save();
  }

  doc.addEventListener('click', function (e: any) {
    var t = e.target;
    if (!t || !t.closest) { return; }
    if (pop && !pop.contains(t) && !t.closest('.th-filter')) { closePop(false); }
    var sorter = t.closest('.th-sort');
    if (sorter) {
      var col = sorter.getAttribute('data-col') as SortCol;
      sort = sort === null || sort.col !== col ? { col: col, dir: 'asc' }
        : (sort.dir === 'asc' ? { col: col, dir: 'desc' } : null);
      render();
      save();
      sorter.focus();
      return;
    }
    var filterButton = t.closest('.th-filter');
    if (filterButton) { openPop(filterButton); return; }
    if (t.closest('#work-plan-clear-filters')) {
      closePop(false);
      titleText = '';
      assignees = null;
      closedWhileFiltering = [];
      render();
      save();
      var firstFilter = table.querySelector('.th-filter');
      if (firstFilter) { firstFilter.focus(); }
      return;
    }
    if (t.closest('#work-plan-both-states')) {
      focusId = 'id:work-plan-state-open';
      save();
      env.post({ type: 'setIssueStates', open: true, closed: true });
      return;
    }
    var bandToggle = t.closest('.milestone-toggle-btn');
    if (bandToggle) {
      var band = bandToggle.closest('.milestone-band');
      var g = Number(band.getAttribute('data-group'));
      var opening = band.classList.contains('collapsed');
      if (filtering()) {
        closedWhileFiltering = closedWhileFiltering.filter(function (x) { return x !== g; });
        if (!opening) { closedWhileFiltering.push(g); }
      } else {
        var current = bodies.filter(function (b) { return !b.classList.contains('collapsed') && !b.hidden; })
          .map(function (b) { return Number(b.getAttribute('data-group')); });
        openGroups = current.filter(function (x) { return x !== g; });
        if (opening) { openGroups.push(g); }
      }
      render();
      save();
      return;
    }
    var capToggle = t.closest('.issue-cap-toggle');
    if (capToggle) {
      if (refsTable && capToggle.closest('#work-plan-refs')) { refsShowAll = !refsShowAll; } else { showAll = !showAll; }
      render();
      save();
      return;
    }
    // The page's own handler has already opened or closed the dependency row.
    var depToggle = t.closest('.dep-toggle-btn');
    if (depToggle) {
      var num = depToggle.getAttribute('data-depissue');
      openDeps = openDeps.filter(function (x) { return x !== num; });
      if (depToggle.getAttribute('aria-expanded') === 'true') { openDeps.push(num); }
      save();
    }
  });

  // A name for a control that survives the page being rebuilt.
  function nameOf(el: any): string | null {
    if (!el || !el.closest) { return null; }
    if (pop && pop.contains(el)) { return 'filter:' + popButton.getAttribute('data-col'); }
    if (el.id) { return 'id:' + el.id; }
    if (el.classList.contains('th-sort')) { return 'sort:' + el.getAttribute('data-col'); }
    if (el.classList.contains('th-filter')) { return 'filter:' + el.getAttribute('data-col'); }
    if (el.classList.contains('milestone-toggle-btn')) { return 'band:' + el.closest('.milestone-band').getAttribute('data-group'); }
    if (el.classList.contains('issue-cap-toggle')) { return el.closest('#work-plan-refs') ? 'cap:refs' : 'cap:owned'; }
    var row = el.closest('.issue-row');
    if (row) {
      var kind = el.closest('#work-plan-refs') ? 'refrow:' : 'row:';
      return kind + row.getAttribute('data-num') + ':' + (el.className.split(' ')[0] || el.tagName.toLowerCase());
    }
    return null;
  }
  function findNamed(name: string): any {
    var bits = name.split(':');
    // Saved text goes into a selector, so only plain names are let through.
    var plain = /^[A-Za-z0-9_-]+$/;
    if (bits.length < 2 || !bits.slice(1).every(function (b) { return plain.test(b); })) { return null; }
    if (bits[0] === 'id') { return byId(bits[1]); }
    if (bits[0] === 'sort') { return table.querySelector('.th-sort[data-col=' + bits[1] + ']'); }
    if (bits[0] === 'filter') { return table.querySelector('.th-filter[data-col=' + bits[1] + ']'); }
    if (bits[0] === 'band') {
      var band = bodies.filter(function (b) { return b.getAttribute('data-group') === bits[1]; })[0];
      return band ? band.querySelector('.milestone-toggle-btn') : null;
    }
    if (bits[0] === 'cap') {
      var root = bits[1] === 'refs' ? refsTable : table;
      return root ? root.querySelector('.issue-cap-toggle') : null;
    }
    var home = bits[0] === 'refrow' ? refsTable : table;
    if (!home) { return null; }
    var row = list(home, '.issue-row').filter(function (r) { return r.getAttribute('data-num') === bits[1]; })[0];
    if (!row || !bits[2]) { return null; }
    return bits[2] === 'a' ? row.querySelector('a') : row.querySelector('.' + bits[2]);
  }
  function unreachable(el: any): boolean {
    if (el.closest('[hidden]')) { return true; }
    var row = el.closest('tr');
    var band = el.closest('.milestone-band.collapsed');
    return !!(band && row && !row.classList.contains('milestone-band-header'));
  }

  doc.addEventListener('focusin', function (e: any) {
    var name = nameOf(e.target);
    if (pop && pop.contains(e.target)) { popItem = Math.max(0, list(pop, 'input, button').indexOf(e.target)); }
    focused = true;
    focusId = name;
    save();
  });
  // Leaving the page: do not take focus back on the next redraw.
  env.window.addEventListener('blur', function () { focused = false; save(); });

  render();

  var reopen = popCol !== null ? table.querySelector('.th-filter[data-col=' + popCol + ']') : null;
  if (focused && reopen) {
    var item = popItem;
    openPop(reopen);
    var control = list(pop, 'input, button')[item];
    if (control) {
      control.focus();
      if (control.setSelectionRange && control.type === 'text') { control.setSelectionRange(control.value.length, control.value.length); }
    }
  } else if (focused && focusId !== null) {
    var target = findNamed(focusId);
    if (!target || unreachable(target)) { target = table.querySelector('.th-filter[data-col=title]'); }
    if (target) { target.focus({ preventScroll: true }); }
  }
}
