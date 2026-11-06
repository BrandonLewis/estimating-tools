/**
 * A fake of the slice of Office.js panes/excel.js's generic reads use:
 * Excel.run, custom properties, workbook-scoped names, worksheets, used
 * ranges, single-column ranges and the active cell. Loads are no-ops (every
 * value is already there) and sync() only counts.
 *
 * book = {
 *   props: {name: value},
 *   names: {name: {sheet, addr} | {type: "String"}},   // addr "A1" or "W1:W9"
 *   sheets: {name: {cells: {A1: value, ...}}},          // in tab order
 *   active: {sheet, row},                               // row 1-based
 * }
 */
import { colIndex, colLetter } from "../../core/refs.js";

const CELL = /^([A-Z]{1,3})([0-9]+)$/;

function parseAddr(addr) {
  const [a, b = a] = addr.replace(/\$/g, "").split(":");
  const m1 = CELL.exec(a), m2 = CELL.exec(b);
  return { c1: m1[1], r1: Number(m1[2]), c2: m2[1], r2: Number(m2[2]) };
}

function rangeOf(sheet, addr) {
  const { c1, r1, c2, r2 } = parseAddr(addr);
  const values = [];
  for (let r = r1; r <= r2; r += 1) {
    const row = [];
    for (let c = colIndex(c1); c <= colIndex(c2); c += 1) {
      const v = sheet.cells[`${colLetter(c)}${r}`];
      row.push(v === undefined ? "" : v);
    }
    values.push(row);
  }
  return { values, rowCount: values.length, load() {} };
}

function usedOf(sheet) {
  const rows = Object.keys(sheet.cells).map((k) => Number(CELL.exec(k)[2]));
  if (!rows.length) return { isNullObject: true, load() {} };
  const first = Math.min(...rows), last = Math.max(...rows);
  return { isNullObject: false, rowIndex: first - 1, rowCount: last - first + 1, load() {} };
}

function worksheet(book, name) {
  const sheet = book.sheets[name];
  return {
    isNullObject: false, name, load() {},
    getRange: (addr) => rangeOf(sheet, addr),
    getUsedRangeOrNullObject: () => usedOf(sheet),
  };
}

/** Installs globalThis.Excel over `book`; returns {syncs} so a test can count round trips. */
export function installFakeExcel(book) {
  const stats = { syncs: 0 };
  const ctx = {
    sync: async () => { stats.syncs += 1; },
    workbook: {
      properties: { custom: { getItemOrNullObject: (n) => (Object.hasOwn(book.props || {}, n)
        ? { isNullObject: false, value: book.props[n], load() {} } : { isNullObject: true, load() {} }) } },
      names: { getItemOrNullObject: (n) => {
        const def = (book.names || {})[n];
        if (!def) return { isNullObject: true, load() {} };
        if (!def.sheet) return { isNullObject: false, type: def.type || "String", load() {} };
        return { isNullObject: false, type: "Range", load() {}, getRange: () => rangeOf(book.sheets[def.sheet], def.addr) };
      } },
      worksheets: {
        load() {},
        get items() { return Object.keys(book.sheets).map((n) => worksheet(book, n)); },
        getActiveWorksheet: () => worksheet(book, book.active.sheet),
        getItemOrNullObject: (n) => (Object.hasOwn(book.sheets, n) ? worksheet(book, n) : { isNullObject: true, load() {} }),
      },
      getActiveCell: () => ({ rowIndex: book.active.row - 1, load() {} }),
    },
  };
  globalThis.Excel = { run: async (fn) => fn(ctx) };
  return stats;
}
