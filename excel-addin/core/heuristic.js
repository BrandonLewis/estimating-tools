/**
 * The heuristic index parser: a workbook est-estimate did not build.
 *
 * A port of the original task pane's parser with its constants moved into a
 * profile. Governing rule unchanged: DISPLAY FROM VALUES, NAVIGATE FROM
 * FORMULAS. A row's item number, description and cost are read as values, so
 * a hand-typed row still displays; it simply is not clickable. Formulas are
 * parsed only to learn which sheet to jump to and where its total lives.
 */
import { cellNumber, cellText, colIndex, colLetter, isErrorValue, itemLabel, tryParseRef } from "./refs.js";

export const DEFAULT_PROFILE = Object.freeze({
  index_sheet: "Summary",
  item_header: "ITEM",
  descr_header_prefix: "DESCRIPTION",
  item_col: "A",
  descr_col: "B",
  cost_col: "E",
  total_label: "DIRECT",
  max_scan: 200,
  max_header_scan: 40,
});

const COL_KEYS = ["item_col", "descr_col", "cost_col"];
const INT_KEYS = ["max_scan", "max_header_scan"];
const STRING_KEYS = ["index_sheet", "item_header", "descr_header_prefix", "total_label"];

/** DEFAULT_PROFILE overlaid with a brand's `heuristic` section. */
export function profileOf(overrides = {}) {
  const p = { ...DEFAULT_PROFILE };
  for (const [k, v] of Object.entries(overrides || {})) {
    // Object.hasOwn, not `k in DEFAULT_PROFILE`: `in` walks the prototype
    // chain, so a brand config with a `constructor` or `toString` key would
    // pass silently instead of being refused as unknown.
    if (!Object.hasOwn(DEFAULT_PROFILE, k)) throw new Error(`unknown heuristic key ${k}`);
    if (COL_KEYS.includes(k) && !/^[A-Z]{1,3}$/.test(v)) throw new Error(`heuristic ${k} must be a column letter`);
    if (INT_KEYS.includes(k) && !(Number.isInteger(v) && v > 0)) throw new Error(`heuristic ${k} must be a positive integer`);
    if (STRING_KEYS.includes(k) && !(typeof v === "string" && v.trim().length > 0)) throw new Error(`heuristic ${k} must be a non-empty string`);
    p[k] = v;
  }
  return Object.freeze(p);
}

/** The block the adapter must read: columns A..lastCol, rows 1..rows. */
export function readSize(profile = DEFAULT_PROFILE) {
  const widest = Math.max(...COL_KEYS.map((k) => colIndex(profile[k])));
  return { lastCol: colLetter(widest), rows: profile.max_header_scan + profile.max_scan + 10 };
}

/** The index sheet: the profile's sheet name if present, else the first sheet. */
export function pickIndexSheet(sheetNames, profile = DEFAULT_PROFILE) {
  const want = profile.index_sheet.toUpperCase();
  const found = sheetNames.find((n) => n.toUpperCase() === want);
  if (found !== undefined) return found;
  return sheetNames.length ? sheetNames[0] : null;
}

/** The header row (0-based): item column equals item_header, description column starts with descr_header_prefix. */
export function findHeaderRow(values, profile = DEFAULT_PROFILE) {
  const a = colIndex(profile.item_col), b = colIndex(profile.descr_col);
  const limit = Math.min(values.length, profile.max_header_scan);
  for (let r = 0; r < limit; r += 1) {
    const va = cellText(values[r]?.[a]).trim().toUpperCase();
    const vb = cellText(values[r]?.[b]).trim().toUpperCase();
    if (va === profile.item_header.toUpperCase() && vb.startsWith(profile.descr_header_prefix.toUpperCase())) return r;
  }
  return -1;
}

/**
 * Builds the bid item index from the index sheet's values and formulas.
 * Returns {rows, indexSheet}; rows is empty when the workbook has no usable index.
 */
export function buildIndex({ values, formulas, sheetNames, indexSheet }, profile = DEFAULT_PROFILE) {
  const none = { rows: [], indexSheet: null };
  if (!Array.isArray(values) || !values.length) return none;
  const h = findHeaderRow(values, profile);
  if (h < 0) return none;
  const ci = colIndex(profile.item_col), cd = colIndex(profile.descr_col), cc = colIndex(profile.cost_col);
  const existing = new Set(sheetNames.map((n) => n.toUpperCase()));
  const rows = [];
  let misses = 0, navigable = 0;
  const last = Math.min(values.length, h + 1 + profile.max_scan);
  for (let r = h + 1; r < last; r += 1) {
    const rawA = values[r]?.[ci];
    if (!isErrorValue(rawA) && cellText(rawA).trim() === "") {
      misses += 1;
      // Before the first hit, tolerate a wider gap; after it, two blanks end
      // the list. That excludes the =SUM() footer, whose item cell is empty.
      if (rows.length === 0 ? misses >= 5 : misses >= 2) break;
      continue;
    }
    misses = 0;
    const row = { itemNo: itemLabel(cellText(rawA)), descr: cellText(values[r]?.[cd]),
                  cost: cellNumber(values[r]?.[cc]), sheetName: "", totalAddr: "", indexRow: r + 1, isTotal: false };
    const refA = tryParseRef(formulas[r]?.[ci]);
    if (refA) row.sheetName = refA.sheet;
    const refE = tryParseRef(formulas[r]?.[cc]);
    if (refE) {
      row.totalAddr = refE.addr;
      if (!row.sheetName) row.sheetName = refE.sheet;
      // Item and cost columns name different sheets: keep the item column's
      // sheet, and drop an address that belongs to the other one.
      else if (row.sheetName.toUpperCase() !== refE.sheet.toUpperCase()) row.totalAddr = "";
    }
    // A reference to a deleted sheet parses cleanly but cannot be navigated.
    if (row.sheetName && !existing.has(row.sheetName.toUpperCase())) { row.sheetName = ""; row.totalAddr = ""; }
    if (row.sheetName) navigable += 1;
    rows.push(row);
  }
  // Nothing navigable means this is not an estimate workbook (a plain bid
  // item list satisfies the header heuristic and would show "DIRECT $0").
  if (!rows.length || navigable === 0) return none;
  return { rows, indexSheet };
}
