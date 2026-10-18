/**
 * The layout JSON est-estimate writes, parsed and checked. It lives in the
 * `est.layout` defined-name cell on the hidden `_templates` sheet, not in
 * the `estimate_layout` custom document property: Office.js truncates a
 * custom property past 255 characters on desktop Excel, so that property
 * carries only the layout version marker, and the pane must read the full
 * JSON from the cell.
 */
export const KNOWN_LAYOUT_VERSION = 1;

const isStr = (v) => typeof v === "string" && v.length > 0;
const isCol = (v) => typeof v === "string" && /^[A-Z]{1,3}$/.test(v);

/** {kind: "none"} | {kind: "ok", layout} | {kind: "newer", layout} | {kind: "bad", message}. */
export function parseLayout(text) {
  if (text === null || text === undefined || text === "") return { kind: "none" };
  let v;
  try { v = JSON.parse(text); } catch { return { kind: "bad", message: "estimate_layout is not JSON" }; }
  if (!v || typeof v !== "object" || !Number.isInteger(v.layout_version)) {
    return { kind: "bad", message: "estimate_layout has no layout_version" };
  }
  if (v.layout_version > KNOWN_LAYOUT_VERSION) return { kind: "newer", layout: v };
  const b = v.blocks || {};
  const ok = isStr(v.pack) && Array.isArray(v.tables) && v.tables.includes("index")
    && v.tags && isCol(v.tags.kind) && isCol(v.tags.code_chain)
    && isStr(b.item) && isStr(b.head) && isStr(b.end) && isStr(b.sub) && Array.isArray(b.body) && isCol(b.code_col);
  return ok ? { kind: "ok", layout: v } : { kind: "bad", message: "estimate_layout is missing fields" };
}

/** The tabs a workbook state supports, in display order. */
export function tabsFor(state) {
  if (state.kind === "heuristic") return ["items"];
  if (state.kind !== "ok") return [];
  const t = state.layout.tables;
  return ["items",
    ...(t.includes("checks") ? ["checks"] : []),
    ...(t.includes("codes") ? ["codes"] : []),
    ...(state.layout.templates ? ["insert"] : []),
    "readback"];
}
