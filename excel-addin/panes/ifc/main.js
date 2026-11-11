/* global Office */
/**
 * IFC Navigator: the task pane over a sheet bundle (`est-bim sheet-bundle`).
 *
 * Model    open a bundle (folder or URL), pick a chunk, load it into sheets
 * Inspect  the selected element (from the sheet or the viewer), pset views
 * Measure  the viewer: select, distance, face area, box dims; send to a cell
 * Changes  diff the sheets against the loaded origin; save the change-set
 *
 * The pane never parses IFC and never writes one: `est-bim apply-changes`
 * does that from the change-set it saves. Nothing is sent anywhere.
 */
import * as X from "./excel.js";
import { h, replace } from "../view.js";
import { ELEMENT_COLUMNS, MEASUREMENT_COLUMNS, PROPERTY_COLUMNS, SHEETS, checkManifest, chunkEntry, elementTable,
         elementsFromTable, parseStamp, propertiesFromTable, propertyTable, psetView, quantityTable, quantityUnit,
         rowsOf, stampOf, typeTable, withoutInvalid } from "../../core/ifc/bundle.js";
import { parseGlb } from "../../core/ifc/glb.js";
import { display, formatNumber } from "../../core/ifc/measure.js";
import { applyCommand, changeSet, diffNames, diffProperties, dumpChangeSet, plan } from "../../core/ifc/changes.js";

const TABS = { model: "Model", inspect: "Inspect", measure: "Measure", changes: "Changes" };
const IFC_SHEETS = [SHEETS.elements, SHEETS.properties, SHEETS.types, SHEETS.quantities];
const FLASH_MS = 6000;

const ui = { tabs: document.getElementById("tabs"), panel: document.getElementById("panel"),
             source: document.getElementById("source"), flash: document.getElementById("flash") };

export const app = { tab: "model", source: null, manifest: null, chunkId: null, chunk: null, nodes: null, stamp: null,
                     selected: null, measure: null, review: null, busy: false, viewer: null, viewerCanvas: null,
                     mode: "select", status: "", flashTimer: null, urlText: "" };

/* ---------- sources: a picked folder or a served URL ---------- */

function folderSource(files) {
  const list = [...files];
  const manifest = list.find((f) => f.name === "manifest.json");
  if (!manifest) throw new Error("the folder has no manifest.json");
  const base = (manifest.webkitRelativePath || manifest.name).slice(0, -"manifest.json".length);
  const byPath = new Map(list.map((f) => [(f.webkitRelativePath || f.name).slice(base.length), f]));
  const file = (rel) => { const f = byPath.get(rel); if (!f) throw new Error(`the folder lacks ${rel}`); return f; };
  return { label: base.replace(/\/$/, "") || manifest.name,
           text: async (rel) => file(rel).text(), buffer: async (rel) => file(rel).arrayBuffer() };
}

function urlSource(url) {
  const manifestUrl = new URL(url.endsWith(".json") ? url : `${url.replace(/\/?$/, "/")}manifest.json`, location.href);
  const get = async (rel) => {
    const r = await fetch(new URL(rel, manifestUrl), { cache: "no-cache" });
    if (!r.ok) throw new Error(`${r.status} fetching ${rel}`);
    return r;
  };
  return { label: manifestUrl.href, text: async (rel) => (await get(rel)).text(), buffer: async (rel) => (await get(rel)).arrayBuffer() };
}

async function openSource(source) {
  app.source = source;
  app.manifest = checkManifest(JSON.parse(await source.text("manifest.json")));
  app.chunkId = app.manifest.chunks.length ? app.manifest.chunks[0].id : null;
  app.chunk = null;
  app.nodes = null;
  ui.source.textContent = `${app.manifest.model.file} · ${app.manifest.model.schema}`;
}

async function readChunk(id) {
  const entry = chunkEntry(app.manifest, id);
  if (!entry) throw new Error("the bundle has no chunks");
  app.chunkId = entry.id;
  app.chunk = JSON.parse(await app.source.text(entry.files.data));
  app.nodes = entry.files.geometry ? parseGlb(await app.source.buffer(entry.files.geometry)).nodes : [];
  return entry;
}

/* ---------- loading a chunk into the workbook ---------- */

async function loadChunk(id) {
  await busy(async () => {
    const entry = await readChunk(id);
    const c = app.chunk;
    await X.writeTable(SHEETS.elements, elementTable(c));
    await X.writeTable(SHEETS.properties, propertyTable(c));
    await X.writeTable(SHEETS.types, typeTable(c));
    await X.writeTable(SHEETS.quantities, quantityTable(c));
    await X.writeTable(SHEETS.originElements, elementTable(c), { hidden: true });
    await X.writeTable(SHEETS.originProperties, propertyTable(c), { hidden: true });
    app.stamp = parseStamp(stampOf(app.manifest, entry.id));
    await X.setStamp(stampOf(app.manifest, entry.id));
    await X.activate(SHEETS.elements);
    if (app.viewer) app.viewer.load(app.nodes, offset());
    flash(`Loaded ${entry.label}: ${c.elements.length} elements, ${c.properties.length} properties`
          + (app.nodes.length ? `, ${app.nodes.length} bodies in the viewer.` : ", no geometry."));
  });
}

const offset = () => (app.manifest && app.manifest.geometry ? app.manifest.geometry.offset_m : [0, 0, 0]);

/* ---------- selection ---------- */

async function selectionChanged() {
  const hit = await X.activeGlobalId(IFC_SHEETS);
  if (!hit || hit.globalId === app.selected) return;
  app.selected = hit.globalId;
  if (app.viewer) app.viewer.highlight(hit.globalId);
  if (app.tab === "inspect") render();
}

async function pickFromViewer(globalId) {
  app.selected = globalId;
  if (app.tab === "inspect") render();
  const found = await X.selectRow(SHEETS.elements, globalId);
  flash(found ? "" : `${globalId} has no row in ${SHEETS.elements}; load its chunk first.`);
}

/* ---------- rendering ---------- */

function flash(text) {
  clearTimeout(app.flashTimer);
  ui.flash.textContent = text;
  if (text) app.flashTimer = setTimeout(() => { ui.flash.textContent = ""; }, FLASH_MS);
}

async function busy(fn) {
  app.busy = true;
  render();
  try { await fn(); } catch (err) { flash(`Error: ${err.message}`); } finally { app.busy = false; render(); }
}

function selectTab(t) {
  app.tab = t;
  render();
  if (t === "measure" && app.viewer) app.viewer.resize();
}

function renderTabs() {
  replace(ui.tabs, Object.entries(TABS).map(([k, label]) => h("button", {
    role: "tab", "aria-selected": String(k === app.tab), onClick: () => selectTab(k) }, label)));
}

function renderModel() {
  const m = app.manifest;
  const open = h("div", { class: "card" },
    h("div", { class: "label" }, "Open a sheet bundle"),
    h("p", { class: "muted" }, "The folder est-bim sheet-bundle wrote (manifest.json and chunks/), or the URL where it is served."),
    h("label", { class: "btn file-btn" }, "Choose folder…",
      h("input", { type: "file", webkitdirectory: true, multiple: true, hidden: true,
                   onChange: (e) => busy(() => openSource(folderSource(e.target.files))) })),
    h("div", { class: "url-row" },
      h("input", { type: "search", placeholder: "http://127.0.0.1:8765/model-sheet/", value: app.urlText,
                   onInput: (e) => { app.urlText = e.target.value; } }),
      h("button", { class: "btn", disabled: app.busy, onClick: () => app.urlText && busy(() => openSource(urlSource(app.urlText))) }, "Open")));
  if (!m) return [open, h("p", { class: "muted" }, "Build one from a shell:"),
                  h("pre", { class: "cmd" }, "est-bim sheet-bundle model.ifc -o model-sheet/")];
  const counts = m.model.counts;
  const info = h("div", { class: "card" },
    h("div", { class: "label" }, "Model"),
    h("table", {}, h("tbody", {},
      ...[["File", m.model.file], ["Schema", m.model.schema], ["Project", m.model.project || "—"], ["Site", m.model.site || "—"],
          ["Elements", String(counts.elements)], ["Properties", String(counts.properties)], ["Chunks", String(counts.chunks)],
          ["Geometry", m.geometry ? `${m.geometry.format}, ${m.geometry.up}-up, offset ${m.geometry.offset_m.join(", ")} m` : "none"],
          ["Generator", m.model.generator]].map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, v))))));
  const chunks = h("div", {}, h("div", { class: "label" }, "Chunks"),
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Chunk"), h("th", { class: "num" }, "Elements"), h("th", { class: "num" }, "Props"), h("th", {}, ""))),
      h("tbody", {}, ...m.chunks.map((c) => h("tr", { class: c.id === app.chunkId && app.chunk ? "sel" : "" },
        h("td", { title: c.id }, c.label, c.files.geometry ? "" : h("span", { class: "muted" }, " (no geometry)")),
        h("td", { class: "num" }, String(c.elements)), h("td", { class: "num" }, String(c.properties)),
        h("td", {}, h("button", { class: "btn small", disabled: app.busy, onClick: () => loadChunk(c.id) },
                      c.id === app.chunkId && app.chunk ? "Reload" : "Load")))))));
  return [open, info, chunks,
          h("p", { class: "muted" }, "Loading a chunk writes the IFC Elements, Properties, Types and Quantities sheets and keeps a hidden copy to diff against. Quantities come from geometry and are not written back.")];
}

function renderInspect() {
  if (!app.chunk) return [h("p", { class: "muted" }, "Load a chunk on the Model tab first.")];
  const c = app.chunk;
  const psets = h("div", { class: "card" }, h("div", { class: "label" }, "Property sets in this chunk"),
    ...(app.manifest.psets.length ? app.manifest.psets : ["(none)"]).map((p) => h("div", { class: "pset-row" },
      h("span", { class: "chip" }, p),
      app.manifest.psets.length ? h("button", { class: "btn small", disabled: app.busy, onClick: () => busy(async () => {
        await X.writeTable(`Pset ${p}`, psetView(c, p));
        await X.activate(`Pset ${p}`);
        flash(`Wrote a view of ${p}. Views are snapshots: edit IFC Properties, not the view.`);
      }) }, "View") : null)));
  const el = c.elements.find((e) => e.global_id === app.selected);
  if (!el) return [psets, h("p", { class: "muted" }, "Select a row on an IFC sheet, or click an element in the viewer.")];
  const props = c.properties.filter((p) => p.global_id === el.global_id);
  const typeProps = c.types.filter((t) => t.global_id === el.type_global_id);
  const qtos = c.quantities.filter((q) => q.global_id === el.global_id);
  const row = (k, v) => h("tr", {}, h("th", {}, k), h("td", { title: v }, v));
  return [
    h("div", { class: "card" },
      h("div", { class: "sel-head" }, h("strong", {}, el.name || el.global_id), h("span", { class: "chip" }, el.ifc_class)),
      h("table", {}, h("tbody", {}, row("GlobalId", el.global_id), row("Predefined", el.predefined_type || "—"),
        row("Type", el.type || "—"), row("Container", el.container || "—"), row("Whole", el.whole || "—"),
        row("Codes", (el.codes || []).join("; ") || "—"))),
      h("div", { class: "btn-row" },
        h("button", { class: "btn small", onClick: () => app.viewer && app.viewer.highlight(el.global_id) }, "Show in viewer"),
        h("button", { class: "btn small", onClick: () => X.selectRow(SHEETS.elements, el.global_id) }, "Go to row"))),
    h("div", { class: "label" }, "Properties"),
    props.length || typeProps.length ? h("table", {}, h("tbody", {},
      ...props.map((p) => h("tr", {}, h("th", { title: p.value_type }, `${p.pset}.${p.property}`), h("td", {}, String(p.value ?? "")))),
      ...typeProps.map((p) => h("tr", { class: "dead" }, h("th", { title: `${p.value_type} (type)` }, `${p.pset}.${p.property}`), h("td", {}, `${p.value ?? ""} (type)`)))))
      : h("p", { class: "muted" }, "No single-value properties."),
    h("div", { class: "label" }, "Quantities (from geometry, read-only)"),
    qtos.length ? h("table", {}, h("tbody", {}, ...qtos.map((q) => {
      const u = quantityUnit(q.quantity);
      return h("tr", {}, h("th", {}, q.quantity), h("td", { class: "num" }, `${formatNumber(q.value * u.factor, 3)} ${u.unit}`));
    }))) : h("p", { class: "muted" }, "No Qto sets."),
    psets,
  ];
}

function measureText(m) {
  if (!m) return null;
  if (m.kind === "box") {
    const L = display(m.dims.L, "length"), W = display(m.dims.W, "length"), H = display(m.dims.H, "length");
    return { title: "Box", lines: [`L ${formatNumber(L.value)} ft`, `W ${formatNumber(W.value)} ft`, `H ${formatNumber(H.value)} ft`],
             cells: [["L", L], ["W", W], ["H", H]] };
  }
  const d = display(m.si, m.kind);
  const title = m.kind === "area" ? `Face area (${m.triangles} triangles)` : m.snapped ? "Distance, vertex to vertex" : "Distance";
  return { title, lines: [`${formatNumber(d.value)} ${d.unit}`, `${formatNumber(d.si, 4)} ${d.siUnit}`], cells: [[m.kind === "area" ? "Area" : "Length", d]] };
}

async function sendToCell(label, d) {
  const address = await X.writeActiveCell(Math.round(d.value * 1e4) / 1e4);
  flash(`${label} ${formatNumber(d.value)} ${d.unit} written to ${address}.`);
}

async function logMeasurement(label, d) {
  const m = app.measure;
  const at = await X.appendRow(SHEETS.measurements, MEASUREMENT_COLUMNS,
    [label, Math.round(d.value * 1e4) / 1e4, d.unit, d.si, d.siUnit, m.elements.join("; "),
     m.points.map((p) => p.join(", ")).join(" → "), app.chunkId || ""]);
  flash(`Logged to ${SHEETS.measurements} row ${at}.`);
}

function renderMeasure() {
  if (!app.viewerCanvas) {
    app.viewerCanvas = h("canvas", { class: "viewer", "aria-label": "3D view of the loaded chunk" });
  }
  const modes = h("div", { class: "modes", role: "group", "aria-label": "Measure mode" },
    ...[["select", "Select"], ["distance", "Distance"], ["face", "Face"], ["box", "Box"]].map(([k, label]) =>
      h("button", { class: `btn small${app.mode === k ? " primary" : ""}`, "aria-pressed": String(app.mode === k),
                    onClick: () => { app.mode = k; if (app.viewer) app.viewer.setMode(k); app.measure = null; render(); } }, label)),
    h("button", { class: "btn small", title: "Fit the view", onClick: () => app.viewer && app.viewer.fit() }, "Fit"));
  const text = measureText(app.measure);
  const result = text ? h("div", { class: "card result" }, h("div", { class: "label" }, text.title),
    ...text.lines.map((l) => h("div", { class: "big" }, l)),
    h("div", { class: "muted" }, `Elements: ${app.measure.elements.join(", ")}`),
    h("div", { class: "btn-row" }, ...text.cells.flatMap(([label, d]) => [
      h("button", { class: "btn small primary", onClick: () => sendToCell(label, d) }, text.cells.length > 1 ? `${label} → cell` : "Send to cell"),
      h("button", { class: "btn small", onClick: () => logMeasurement(label, d) }, text.cells.length > 1 ? `Log ${label}` : "Log")])))
    : h("p", { class: "muted" }, app.status || "Load a chunk with geometry, then pick a mode.");
  return [modes, app.viewerCanvas, result,
          h("p", { class: "muted" }, "Measurements are on the tessellation the takeoff was checked against. Curves measure as chords; the model's Qto stays the quantity of record.")];
}

async function review() {
  await busy(async () => {
    const stampText = await X.getStamp();
    app.stamp = parseStamp(stampText) || app.stamp;
    const originP = await X.readTable(SHEETS.originProperties), currentP = await X.readTable(SHEETS.properties);
    const originE = await X.readTable(SHEETS.originElements), currentE = await X.readTable(SHEETS.elements);
    if (!originP || !originE) throw new Error("this workbook has no loaded bundle to diff against");
    const o = propertiesFromTable(originP), cur = propertiesFromTable(currentP || [PROPERTY_COLUMNS]);
    const known = new Set();
    for (const r of rowsOf(originE)) { known.add(String(r.GlobalId)); if (r.TypeGlobalId) known.add(String(r.TypeGlobalId)); }
    // a cell that did not parse is reported, and its property is left as it was
    const { ops, problems } = diffProperties(withoutInvalid(o.properties, cur.invalid), cur.properties, known);
    const names = diffNames(elementsFromTable(originE), elementsFromTable(currentE || [ELEMENT_COLUMNS]));
    const all = [...ops, ...names];
    app.review = { ops: all, groups: plan(all), problems: [...cur.errors, ...problems] };
  });
}

function download(name, text) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "application/json" })), download: name });
  document.body.append(a);
  a.click();
  a.remove();
}

function renderChanges() {
  const head = h("div", { class: "btn-row" },
    h("button", { class: "btn primary", disabled: app.busy, onClick: review }, "Check changes"),
    app.review && app.review.ops.length ? h("button", { class: "btn", onClick: () => {
      download("changes.json", dumpChangeSet(changeSet(app.stamp, app.review.ops)));
      flash("Saved changes.json. Apply it with the command below.");
    } }, "Save change-set") : null);
  if (!app.review) return [head, h("p", { class: "muted" }, "Compares IFC Properties and the Name column of IFC Elements with the hidden copy made when the chunk loaded. GlobalIds and quantities are never changed.")];
  const r = app.review;
  return [head,
    r.problems.length ? h("div", { class: "card" }, h("div", { class: "label bad" }, `${r.problems.length} cell(s) not understood`),
      ...r.problems.slice(0, 20).map((p) => h("div", { class: "muted mono" }, p))) : null,
    r.ops.length ? h("div", {}, h("div", { class: "label" }, `${r.ops.length} operation(s)`),
      ...r.groups.map((g) => h("details", { class: "card" }, h("summary", {}, `${g.title} `, h("span", { class: "chip" }, String(g.count))),
        h("table", {}, h("tbody", {}, ...g.ops.slice(0, 50).map((op) => h("tr", {}, h("td", { class: "mono", title: op.global_id }, op.global_id),
          h("td", {}, op.op === "remove_property" ? "(removed)" : String(op.value ?? "")))))))))
      : h("p", { class: "ok" }, "No changes against the loaded bundle."),
    r.ops.length ? h("div", {}, h("div", { class: "label" }, "Apply it"), h("pre", { class: "cmd" }, applyCommand(app.stamp)),
      h("p", { class: "muted" }, "Save the change-set beside the IFC and run this from a shell. The original is left alone; the edited copy opens in any IFC viewer.")) : null];
}

const RENDER = { model: renderModel, inspect: renderInspect, measure: renderMeasure, changes: renderChanges };

export function render() {
  renderTabs();
  replace(ui.panel, RENDER[app.tab]());
  if (app.tab === "measure" && !app.viewer && app.viewerCanvas) startViewer();
}

async function startViewer() {
  try {
    const { createViewer } = await import("./viewer.js");
    app.viewer = createViewer(app.viewerCanvas, {
      onPick: pickFromViewer,
      onMeasure: (m) => { app.measure = m; render(); },
      onStatus: (s) => { app.status = typeof s === "string" ? s : String(s); if (!app.measure) render(); },
    });
    if (app.viewer) { app.viewer.setMode(app.mode); if (app.nodes) app.viewer.load(app.nodes, offset()); }
  } catch (err) {
    app.status = `The viewer could not start: ${err.message}`;
    render();
  }
}

async function start() {
  render();
  try {
    const stamp = parseStamp(await X.getStamp());
    if (stamp) { app.stamp = stamp; ui.source.textContent = `${stamp.file} · ${stamp.schema} (loaded earlier; open the bundle again for the viewer)`; }
    await X.onSelectionChanged(selectionChanged);
  } catch (err) {
    flash(`Excel: ${err.message}`);
  }
}

if (typeof Office !== "undefined" && Office.onReady) Office.onReady().then(start);
else start();
