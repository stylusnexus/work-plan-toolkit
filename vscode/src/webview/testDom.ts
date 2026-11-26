/**
 * A very small DOM for running the issue-table page code in tests (#598).
 * Parses the well-formed markup `renderDetail` emits; supports only the
 * selectors and members that code uses.
 */

export class El {
  tagName: string;
  attrs: Record<string, string> = {};
  childNodes: (El | string)[] = [];
  parentNode: El | null = null;
  listeners: Record<string, ((e: any) => void)[]> = {};
  style: Record<string, string> = {};
  doc: Doc;
  constructor(tag: string, doc: Doc) { this.tagName = tag.toUpperCase(); this.doc = doc; }

  get children(): El[] { return this.childNodes.filter((c): c is El => c instanceof El); }
  get id(): string { return this.attrs.id ?? ""; }
  set id(v: string) { this.attrs.id = v; }
  get className(): string { return this.attrs.class ?? ""; }
  set className(v: string) { this.attrs.class = v; }
  get hidden(): boolean { return "hidden" in this.attrs; }
  set hidden(v: boolean) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get type(): string { return this.attrs.type ?? ""; }
  set type(v: string) { this.attrs.type = v; }
  _checked: boolean | null = null;
  get checked(): boolean { return this._checked ?? "checked" in this.attrs; }
  set checked(v: boolean) { this._checked = v; }
  _value: string | null = null;
  get value(): string { return this._value ?? this.attrs.value ?? ""; }
  set value(v: string) { this._value = v; }
  get textContent(): string { return this.childNodes.map(c => (c instanceof El ? c.textContent : c)).join(""); }
  set textContent(v: string) { this.childNodes = [v]; }
  get nextElementSibling(): El | null {
    const sib = this.parentNode?.children ?? [];
    return sib[sib.indexOf(this) + 1] ?? null;
  }
  classList = {
    contains: (c: string): boolean => this.className.split(/\s+/).includes(c),
    toggle: (c: string, force?: boolean): boolean => {
      const set = new Set(this.className.split(/\s+/).filter(Boolean));
      const on = force ?? !set.has(c);
      if (on) set.add(c); else set.delete(c);
      this.className = [...set].join(" ");
      return on;
    },
  };
  setAttribute(k: string, v: unknown): void { this.attrs[k] = String(v); }
  getAttribute(k: string): string | null { return this.attrs[k] ?? null; }
  removeAttribute(k: string): void { delete this.attrs[k]; }
  remove(): void {
    if (!this.parentNode) return;
    this.parentNode.childNodes = this.parentNode.childNodes.filter(c => c !== this);
    this.parentNode = null;
  }
  appendChild<T extends El | string>(c: T): T {
    if (c instanceof El) { c.remove(); c.parentNode = this; }
    this.childNodes.push(c);
    return c;
  }
  contains(other: El | null): boolean {
    for (let n = other; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
  addEventListener(type: string, fn: (e: any) => void): void { (this.listeners[type] ??= []).push(fn); }
  /** Bubbles from this element up through the document. */
  fire(type: string, extra: Record<string, unknown> = {}): { defaultPrevented: boolean } {
    const e = {
      type, target: this as El, defaultPrevented: false, stopped: false, ...extra,
      preventDefault() { this.defaultPrevented = true; },
      stopPropagation() { this.stopped = true; },
    };
    for (let n: El | null = this; n && !e.stopped; n = n.parentNode) for (const fn of n.listeners[type] ?? []) fn(e);
    if (!e.stopped) for (const fn of this.doc.listeners[type] ?? []) fn(e);
    return e;
  }
  click(): void {
    if (this.type === "checkbox") { this.checked = !this.checked; this.fire("click"); this.fire("change"); return; }
    this.fire("click");
  }
  focus(): void { this.doc.activeElement = this; this.fire("focusin"); }
  getBoundingClientRect() { return { left: 10, top: 10, bottom: 30, right: 40 }; }
  private matchesSimple(sel: string): boolean {
    const parts = sel.match(/^[a-z0-9]+|#[\w-]+|\.[\w-]+|\[[^\]]+\]/gi) ?? [];
    return parts.every(p => {
      if (p[0] === "#") return this.id === p.slice(1);
      if (p[0] === ".") return this.classList.contains(p.slice(1));
      if (p[0] === "[") {
        const m = /^\[([\w-]+)(?:=['"]?([^'"]*)['"]?)?\]$/.exec(p)!;
        return m[2] === undefined ? m[1] in this.attrs : this.attrs[m[1]] === m[2];
      }
      return this.tagName === p.toUpperCase();
    });
  }
  matches(selector: string): boolean {
    return selector.split(",").some(group => {
      const chain = group.trim().split(/\s+/);
      if (!this.matchesSimple(chain[chain.length - 1])) return false;
      let node = this.parentNode;
      for (let i = chain.length - 2; i >= 0; i--) {
        while (node && !node.matchesSimple(chain[i])) node = node.parentNode;
        if (!node) return false;
        node = node.parentNode;
      }
      return true;
    });
  }
  closest(selector: string): El | null {
    for (let n: El | null = this; n; n = n.parentNode) if (n.matches(selector)) return n;
    return null;
  }
  querySelectorAll(selector: string): El[] {
    const out: El[] = [];
    const walk = (el: El): void => { for (const c of el.children) { if (c.matches(selector)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  querySelector(selector: string): El | null { return this.querySelectorAll(selector)[0] ?? null; }
}

export class Doc {
  listeners: Record<string, ((e: any) => void)[]> = {};
  body: El = new El("body", this);
  activeElement: El | null = null;
  addEventListener(type: string, fn: (e: any) => void): void { (this.listeners[type] ??= []).push(fn); }
  createElement(tag: string): El { return new El(tag, this); }
  getElementById(id: string): El | null { return this.body.querySelector(`#${id}`); }
  querySelector(sel: string): El | null { return this.body.querySelector(sel); }
  querySelectorAll(sel: string): El[] { return this.body.querySelectorAll(sel); }
}

const unescapeHtml = (s: string): string => s
  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");

export function parseHtml(html: string): Doc {
  const doc = new Doc();
  let cur = doc.body;
  const voids = new Set(["input", "br", "img"]);
  for (const m of html.matchAll(/<\/([a-z0-9]+)>|<([a-z0-9]+)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/gi)) {
    if (m[1]) { cur = cur.parentNode ?? doc.body; continue; }
    if (m[4] !== undefined) { cur.childNodes.push(unescapeHtml(m[4])); continue; }
    const el = new El(m[2], doc);
    for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) el.attrs[a[1]] = unescapeHtml(a[2] ?? "");
    cur.appendChild(el);
    if (!voids.has(m[2].toLowerCase())) cur = el;
  }
  return doc;
}
