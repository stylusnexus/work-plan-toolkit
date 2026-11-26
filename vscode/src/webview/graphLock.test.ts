import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { buildHtml } from "./html.ts";
import type { WebviewHtmlOptions } from "./html.ts";

const BASE: WebviewHtmlOptions = {
  cspSource: "x:", nonce: "n".repeat(32), mermaidUri: "x:/m.js", graphDef: "graph LR\n a --> b", detailHtml: "",
  trackName: "t", isModule: false, mode: "focus", isDark: true, hasTrackFile: false,
  issueStates: { open: true, closed: false }, graphNote: null, trackKey: "k",
};

/** Runs the page script over just enough of a page to drive the graph controls. */
function run(saved?: unknown) {
  const el = () => {
    const listeners: Record<string, ((e: any) => void)[]> = {};
    const classes = new Set<string>();
    const attrs: Record<string, string> = {};
    return {
      listeners, classes, attrs, style: {} as Record<string, string>, title: "", isConnected: true,
      viewBox: { baseVal: { width: 2000, height: 1000 } },
      addEventListener: (t: string, f: (e: any) => void) => { (listeners[t] ??= []).push(f); },
      setAttribute: (k: string, v: unknown) => { attrs[k] = String(v); },
      getAttribute: (k: string) => attrs[k] ?? null,
      classList: {
        add: (c: string) => { classes.add(c); }, remove: (c: string) => { classes.delete(c); },
        toggle: (c: string, on: boolean) => { if (on) classes.add(c); else classes.delete(c); return on; },
      },
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 540 }),
      setPointerCapture() {}, querySelectorAll: () => [], querySelector: () => null,
    };
  };
  const figure = el(), svg = el(), lock = el(), zoomIn = el();
  const byId: Record<string, ReturnType<typeof el>> = { "graph-lock": lock, "graph-zoom-in": zoomIn };
  const doc = {
    addEventListener() {}, querySelectorAll: () => [], getElementById: (id: string) => byId[id] ?? null,
    querySelector: (s: string) => (s === ".graph-figure" ? figure : null),
  };
  (figure as any).querySelector = () => svg;
  let state: any = saved;
  const api = { postMessage() {}, getState: () => state, setState: (v: unknown) => { state = v; } };
  const script = [...buildHtml(BASE).matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1])
    .find(b => b.includes("setupGraphControls"))!;
  new Function("document", "window", "acquireVsCodeApi", "console", script)(
    doc, { __workplanGraphRendered: true, addEventListener() {}, setTimeout: () => 0, clearTimeout() {} }, () => api, { error() {}, log() {} });
  const fire = (target: ReturnType<typeof el>, type: string, e: Record<string, unknown> = {}) => {
    let prevented = false;
    for (const f of target.listeners[type] ?? []) f({ preventDefault: () => { prevented = true; }, deltaY: -1, clientX: 500, clientY: 270, pointerId: 1, ...e });
    return prevented;
  };
  const wheel = () => fire(figure, "wheel");
  const drag = () => {
    fire(figure, "pointerdown", { clientX: 100, clientY: 100 });
    fire(figure, "pointermove", { clientX: 160, clientY: 140 });
    fire(figure, "pointerup", { clientX: 160, clientY: 140 });
  };
  return { figure, svg, lock, zoomIn, wheel, drag, click: () => fire(lock, "click"), zoom: () => fire(zoomIn, "click"), state: () => state };
}

describe("graph lock (#597)", () => {
  it("renders a lock button in every mode with a stable name and state", () => {
    for (const mode of ["focus", "full", "critical"] as const) {
      const tag = buildHtml({ ...BASE, mode }).match(/<button[^>]*id="graph-lock"[^>]*>/)?.[0] ?? "";
      assert.ok(tag.includes('aria-label="Lock graph"') && tag.includes('aria-pressed="false"'), mode);
    }
    assert.match(buildHtml({ ...BASE, graphDef: "" }), /<button[^>]*id="graph-lock"[^>]*disabled/);
  });

  it("starts unlocked: the wheel zooms and dragging pans", () => {
    const p = run();
    const start = p.svg.style.transform;
    assert.equal(p.wheel(), true);
    const zoomed = p.svg.style.transform;
    assert.notEqual(zoomed, start);
    p.drag();
    assert.notEqual(p.svg.style.transform, zoomed);
    assert.equal(p.lock.attrs["aria-pressed"], "false");
  });

  it("locked: wheel and drag leave the graph alone and the page can scroll", () => {
    const p = run();
    p.click();
    const before = p.svg.style.transform;
    assert.equal(p.wheel(), false, "the wheel must not be captured");
    p.drag();
    assert.equal(p.svg.style.transform, before);
    assert.equal(p.lock.attrs["aria-pressed"], "true");
    assert.ok(p.figure.classes.has("locked") && !p.figure.classes.has("grabbing"));
    assert.equal(p.lock.title, "Unlock graph");
  });

  it("keeps the zoom buttons working while locked, and the same button unlocks", () => {
    const p = run();
    p.click();
    const before = p.svg.style.transform;
    p.zoom();
    assert.notEqual(p.svg.style.transform, before);
    p.click();
    assert.equal(p.wheel(), true);
    assert.equal(p.lock.title, "Lock graph");
  });

  it("remembers the lock without dropping other saved choices", () => {
    const p = run({ flowFormat: "order" });
    p.click();
    assert.equal(p.state().graphLocked, true);
    assert.equal(p.state().flowFormat, "order");
    const again = run(p.state());
    assert.equal(again.lock.attrs["aria-pressed"], "true");
    assert.equal(again.wheel(), false);
  });

  it("styles both icons and the locked graph", () => {
    const html = buildHtml(BASE);
    for (const part of ['class="lock-open"', 'class="lock-closed"', ".graph-figure.locked", '#graph-lock[aria-pressed="true"] .lock-open']) {
      assert.ok(html.includes(part), part);
    }
  });
});
