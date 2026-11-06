/* global Office */
import * as X from "./excel.js";
import { h, replace } from "./view.js";
import { factRequest, jumpAddress, pick, sourceOf, tabsOf } from "../core/adapter.js";
import { fieldbook } from "../core/packs/fieldbook.js";
import { buildIndex, pickIndexSheet, profileOf, readSize } from "../core/heuristic.js";
import { legacyToTree, withTotal } from "../core/rows.js";
import { resolveBrand, cssVars, brandPath } from "../core/brand.js";
import { renderItems } from "./items.js";
import { renderChecks } from "./checks.js";
import { renderCodes } from "./codes.js";
import { renderInsert } from "./insert.js";
import { renderReadback } from "./readback.js";

/** The pack adapters, in detection order: the first whose detect is not "no" owns the workbook. */
const ADAPTERS = [fieldbook];
const FACTS = factRequest(ADAPTERS);
const TAB_LABELS = { items: "Items", checks: "Checks", codes: "Codes", insert: "Insert", readback: "Read back" };
const RENDER = { items: renderItems, checks: renderChecks, codes: renderCodes, insert: renderInsert, readback: renderReadback };
const REFRESH_MS = 400;
const SELECTION_MS = 150;
const FLASH_MS = 6000;
const SAMPLE_URL = "../../sample.xlsx";
const DARK = "(prefers-color-scheme: dark)";

const ui = { tabs: document.getElementById("tabs"), panel: document.getElementById("panel"),
             name: document.getElementById("brand-name"), source: document.getElementById("source"),
             logo: document.getElementById("logo"), flash: document.getElementById("flash") };
// `seq` counts renders: an async tab renderer that finds it has moved on
// draws nothing, so a slow read never paints over a newer one. `pending`
// queues one more refresh when a change lands mid-read. `codeQuery`,
// `insertNote`, `insertConfirm` and `scan` survive the re-render every
// workbook change triggers; `scan` (the read-back sheet scan) is redone only
// on entering the Read back tab or on "Check again". A stamped workbook's
// state is {kind: "ok", adapter, layout}.
export const app = { state: { kind: "loading" }, tab: "items", brand: null, deploymentBrand: null, generic: null,
                     brandBase: null, workbookBrand: null, data: {}, activeSheet: "", busy: false, pending: false,
                     timer: null, selTimer: null, flashTimer: null, seq: 0,
                     codeQuery: "", insertNote: null, insertConfirm: null, inserting: false, insertButtons: [], scan: null };

async function fetchJson(url) {
  try { const r = await fetch(url, { cache: "no-cache" }); return r.ok ? await r.json() : null; } catch { return null; }
}

async function loadBrands() {
  const slug = new URLSearchParams(location.search).get("brand") || "";
  app.generic = await fetchJson(brandPath(""));
  app.deploymentBrand = slug ? await fetchJson(brandPath(slug)) : null;
  app.brandBase = new URL(slug ? brandPath(slug) : brandPath(""), location.href);
}

function applyBrand(workbookBrand) {
  app.workbookBrand = workbookBrand;
  if (!app.generic) return;
  app.brand = resolveBrand({ generic: app.generic, deployment: app.deploymentBrand, workbook: workbookBrand });
  const dark = matchMedia(DARK).matches;
  for (const [k, v] of Object.entries(cssVars(app.brand, dark))) document.documentElement.style.setProperty(k, v);
  ui.name.textContent = app.brand.name;
  if (app.brand.logo) ui.logo.src = new URL(app.brand.logo, app.brandBase).href;
}

function flash(text) {
  clearTimeout(app.flashTimer);
  ui.flash.textContent = text;
  if (text) app.flashTimer = setTimeout(() => { ui.flash.textContent = ""; }, FLASH_MS);
}

function selectTab(t) {
  if (t !== app.tab) {
    app.insertNote = null;
    app.insertConfirm = null;
    app.codeQuery = "";
    if (t === "readback") app.scan = null;     // entering Read back re-scans
    flash("");
  }
  app.tab = t;
  render();
}

function renderTabs() {
  const tabs = tabsOf(app.state);
  if (!tabs.includes(app.tab)) {
    // A forced switch (the workbook changed under the pane) drops per-tab state, as selectTab does.
    const next = tabs[0] || "items";
    if (next !== app.tab) { app.insertNote = null; app.insertConfirm = null; app.codeQuery = ""; }
    app.tab = next;
  }
  const move = (t, step) => {
    const next = tabs[(tabs.indexOf(t) + step + tabs.length) % tabs.length];
    selectTab(next);
    const btn = ui.tabs.childNodes[tabs.indexOf(next)];
    if (btn && btn.focus) btn.focus();
  };
  replace(ui.tabs, tabs.map((t) => h("button", {
    role: "tab", id: `tab-${t}`, "aria-controls": "panel", "aria-selected": t === app.tab ? "true" : "false",
    tabindex: t === app.tab ? "0" : "-1",
    onclick: () => selectTab(t),
    onkeydown: (e) => {
      if (e.key === "ArrowRight") { e.preventDefault(); move(t, 1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); move(t, -1); }
    } }, TAB_LABELS[t])));
  if (tabs.length) ui.panel.setAttribute("aria-labelledby", `tab-${app.tab}`);
}

function renderEmpty(title, body) {
  const support = app.brand?.support_url;
  replace(ui.panel, h("div", { class: "card" },
    h("p", {}, h("strong", {}, title)), h("p", {}, body),
    h("p", {}, h("a", { href: SAMPLE_URL, target: "_blank", rel: "noopener" }, "Download a sample workbook"),
      support ? [" · ", h("a", { href: support, target: "_blank", rel: "noopener" }, "Help")] : null)));
}

/** Navigation that cannot reject unhandled: a hidden sheet says so, a vanished one refreshes the pane. */
async function go(sheet, addr) {
  flash("");
  try {
    const r = await X.go(sheet, addr);
    if (r && r.hidden) flash("That item sheet is hidden. Unhide it to go there.");
  } catch {
    scheduleRefresh();
  }
}

/**
 * `x`, the wrapper every adapter and pane reaches Excel through. `current`
 * tells an async renderer whether it is still the latest render.
 */
function wrapper(current) {
  return {
    go, jump: (j) => go(j.sheet, jumpAddress(j)), writeCell: X.writeCell, insertTemplate: X.insertTemplate,
    readNames: X.readNames, readBlock: X.readBlock, readActive: X.readActive, readActiveColumns: X.readActiveColumns,
    readColumns: X.readColumns, readNamedValues: X.readNamedValues, readProperty: X.readProperty,
    readDirty: X.readDirty, scanItemSheets: X.scanItemSheets, documentUrl: X.documentUrl, refresh, current,
  };
}

export function render() {
  const seq = ++app.seq;
  renderTabs();
  const s = app.state;
  ui.source.textContent = sourceOf(s);
  if (s.kind === "loading") return replace(ui.panel, h("p", { class: "muted" }, "Loading…"));
  if (s.kind === "error") return renderEmpty("Could not read this workbook.", s.message);
  if (s.kind === "newer") return renderEmpty("Update Estimate Navigator.",
    "This workbook was built with a newer layout than this version of the add-in understands. It shows nothing rather than guess.");
  if (s.kind === "bad") return renderEmpty("This workbook's Estimate Navigator stamp is damaged.", s.message);
  if (s.kind === "none") return renderEmpty("No estimate here yet.",
    "Open a workbook built by est-estimate, or one with a Summary sheet whose header row reads ITEM and DESCRIPTION.");
  const done = RENDER[app.tab](ui.panel, app, wrapper(() => seq === app.seq));
  // An async renderer that throws past its own guards still says so in the pane.
  if (done && typeof done.catch === "function") {
    done.catch((e) => { if (seq === app.seq) replace(ui.panel, h("p", { class: "bad" }, String((e && e.message) || e))); });
  }
}

/** A hand-built workbook's data, or null when it has no usable index. */
async function readHeuristic(sheetNames) {
  const profile = profileOf(app.deploymentBrand?.heuristic || {});
  const index = pickIndexSheet(sheetNames, profile);
  if (!index) return null;
  const { lastCol, rows } = readSize(profile);
  const { values, formulas } = await X.readBlock(index, lastCol, rows);
  const built = buildIndex({ values, formulas, sheetNames, indexSheet: index }, profile);
  if (!built.rows.length) return null;
  return { items: legacyToTree(withTotal(built.rows, { label: profile.total_label, sheet: index })), checks: null, codes: [] };
}

/**
 * Re-read the workbook and re-render. A call that lands while a refresh is
 * running is not dropped: it queues exactly one more pass, which runs as soon
 * as the current one finishes, so the last change is always read.
 */
export async function refresh() {
  if (app.busy) { app.pending = true; return; }
  app.busy = true;
  app.pending = false;
  try {
    const facts = await X.readFacts(FACTS);
    app.activeSheet = facts.activeSheet;
    const hit = pick(ADAPTERS, facts);
    let data = app.data, state;
    if (hit && hit.verdict === "yes") {
      const x = wrapper(() => true);
      const layout = await hit.adapter.load(x, facts);
      applyBrand(hit.adapter.brand ? hit.adapter.brand(layout) : null);
      data = await hit.adapter.read(x, layout, facts);
      state = { kind: "ok", adapter: hit.adapter, layout };
    } else {
      applyBrand(null);
      if (hit && hit.verdict === "newer") state = { kind: "newer" };
      else if (hit && hit.verdict === "bad") state = { kind: "bad", message: hit.adapter.damage(facts) };
      else {
        const d = await readHeuristic(facts.sheetNames);
        if (d) data = d;
        state = d ? { kind: "heuristic" } : { kind: "none" };
      }
    }
    app.data = data;
    app.state = state;
  } catch (e) {
    app.state = { kind: "error", message: String(e && e.message || e) };
  } finally {
    app.busy = false;
  }
  render();
  if (app.pending) await refresh();
}

function scheduleRefresh() {
  clearTimeout(app.timer);
  app.timer = setTimeout(refresh, REFRESH_MS);
}

/**
 * Selection and sheet changes, debounced: holding an arrow key fires one read
 * when the cursor settles, not one per cell. Items re-renders only when the
 * active sheet changed (it highlights that sheet's row); Codes and Insert
 * follow the cursor, and `seq` keeps only the latest of their reads.
 */
function onActivated() {
  clearTimeout(app.selTimer);
  app.selTimer = setTimeout(applyActivated, SELECTION_MS);
}

async function applyActivated() {
  let name;
  try { name = await X.readActiveSheetName(); } catch { return; }
  const changed = name !== app.activeSheet;
  app.activeSheet = name;
  if ((app.tab === "items" && changed) || app.tab === "codes" || app.tab === "insert") render();
}

Office.onReady(async (info) => {
  if (info.host !== Office.HostType.Excel) {
    replace(ui.panel, h("p", {}, "Estimate Navigator runs in Excel."));
    return;
  }
  await loadBrands();
  applyBrand(null);
  try {
    const mq = matchMedia(DARK);
    const reapply = () => applyBrand(app.workbookBrand);
    if (mq.addEventListener) mq.addEventListener("change", reapply);
    else if (mq.addListener) mq.addListener(reapply);
  } catch { /* no theme events: the brand keeps its first palette */ }
  // A failed subscription costs live refresh, not the pane: "Check again"
  // on the Read back tab still re-reads the workbook.
  try { await X.watch(scheduleRefresh, onActivated); } catch (e) { console.warn("Estimate Navigator: no workbook events", e); }
  await refresh();
});
