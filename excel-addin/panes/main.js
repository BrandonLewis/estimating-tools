/* global Office */
import * as X from "./excel.js";
import { h, replace } from "./view.js";
import { parseLayout, tabsFor } from "../core/stamp.js";
import { buildIndex, pickIndexSheet, profileOf, readSize } from "../core/heuristic.js";
import { itemsFromTable, withTotal } from "../core/items.js";
import { checksFromTable, failingByItem } from "../core/checks.js";
import { codeList } from "../core/codes.js";
import { resolveBrand, cssVars, brandPath } from "../core/brand.js";
import { renderItems } from "./items.js";
import { renderChecks } from "./checks.js";
import { renderCodes } from "./codes.js";
import { renderInsert } from "./insert.js";
import { renderReadback } from "./readback.js";

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
// `insertNote` and `scan` survive the re-render every workbook change
// triggers; `scan` (the read-back sheet scan) is redone only on entering the
// Read back tab or on "Check again".
export const app = { state: { kind: "loading" }, tab: "items", brand: null, deploymentBrand: null, generic: null,
                     brandBase: null, workbookBrand: null, data: {}, activeSheet: "", busy: false, pending: false,
                     timer: null, selTimer: null, flashTimer: null, seq: 0,
                     codeQuery: "", insertNote: null, inserting: false, insertButtons: [], scan: null };

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
    app.codeQuery = "";
    if (t === "readback") app.scan = null;     // entering Read back re-scans
    flash("");
  }
  app.tab = t;
  render();
}

function renderTabs() {
  const tabs = tabsFor(app.state);
  if (!tabs.includes(app.tab)) app.tab = tabs[0] || "items";
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

export function render() {
  const seq = ++app.seq;
  renderTabs();
  const s = app.state;
  ui.source.textContent = s.kind === "ok" ? `${s.layout.pack} pack` : s.kind === "heuristic" ? "Hand-built workbook" : "";
  if (s.kind === "loading") return replace(ui.panel, h("p", { class: "muted" }, "Loading…"));
  if (s.kind === "error") return renderEmpty("Could not read this workbook.", s.message);
  if (s.kind === "newer") return renderEmpty("Update Estimate Navigator.",
    "This workbook was built with a newer layout than this version of the add-in understands. It shows nothing rather than guess.");
  if (s.kind === "bad") return renderEmpty("This workbook's Estimate Navigator stamp is damaged.", `${s.message}. Rebuild the workbook with est-estimate.`);
  if (s.kind === "none") return renderEmpty("No estimate here yet.",
    "Open a workbook built by est-estimate, or one with a Summary sheet whose header row reads ITEM and DESCRIPTION.");
  const done = RENDER[app.tab](ui.panel, app, { go, writeCell: X.writeCell, insertTemplate: X.insertTemplate,
    readActive: X.readActive, readDirty: X.readDirty, scanItemSheets: X.scanItemSheets,
    documentUrl: X.documentUrl, refresh, current: () => seq === app.seq });
  // An async renderer that throws past its own guards still says so in the pane.
  if (done && typeof done.catch === "function") {
    done.catch((e) => { if (seq === app.seq) replace(ui.panel, h("p", { class: "bad" }, String((e && e.message) || e))); });
  }
}

/** The stamped workbook's data, built whole so a render never sees half-old, half-new data. */
async function readStamped(layout, sheetNames) {
  const names = ["est.index.item_no", "est.index.descr", "est.index.cost", "est.index.link", "est.direct_total"];
  if (layout.tables.includes("checks")) names.push("est.checks.rule_no", "est.checks.rule", "est.checks.item", "est.checks.status");
  if (layout.tables.includes("codes")) names.push("est.codes.code", "est.codes.descr", "est.codes.listed");
  const n = await X.readNames(names);
  const v = (k) => n[k]?.values || [];
  const rows = itemsFromTable({ itemNo: v("est.index.item_no"), descr: v("est.index.descr"), cost: v("est.index.cost"),
                                link: n["est.index.link"]?.formulas || [], sheetNames });
  const totalCell = n["est.direct_total"];
  // A quoted sheet name may itself hold "!", so the separator is the last one.
  const bang = totalCell ? totalCell.address.lastIndexOf("!") : -1;
  const tSheet = bang >= 0 ? totalCell.address.slice(0, bang) : "";
  const tAddr = bang >= 0 ? totalCell.address.slice(bang + 1) : "";
  const checks = layout.tables.includes("checks")
    ? checksFromTable({ ruleNo: v("est.checks.rule_no"), rule: v("est.checks.rule"), item: v("est.checks.item"), status: v("est.checks.status") })
    : null;
  return {
    items: withTotal(rows, { total: totalCell?.values?.[0]?.[0], label: "DIRECT",
                             sheet: tSheet.replace(/^'|'$/g, "").replace(/''/g, "'"), addr: tAddr }),
    checks,
    failing: checks ? failingByItem(checks) : new Map(),
    codes: layout.tables.includes("codes")
      ? codeList({ code: v("est.codes.code"), descr: v("est.codes.descr"), listed: v("est.codes.listed") }) : [],
  };
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
  return { items: withTotal(built.rows, { label: profile.total_label, sheet: index }), failing: new Map(), codes: [], checks: null };
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
    const { layoutText, sheetNames, activeSheet } = await X.readWorkbook();
    app.activeSheet = activeSheet;
    const parsed = parseLayout(layoutText);
    applyBrand(parsed.kind === "ok" ? parsed.layout.brand : null);
    let data = app.data, state = parsed;
    if (parsed.kind === "ok") data = await readStamped(parsed.layout, sheetNames);
    else if (parsed.kind === "none") {
      const d = await readHeuristic(sheetNames);
      if (d) data = d;
      state = d ? { kind: "heuristic" } : { kind: "none" };
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
