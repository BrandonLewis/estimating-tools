/* global Excel */
/**
 * Everything in the IFC pane that touches Excel. core/ifc never sees an
 * Excel object. Tables are written in batches so a large chunk does not
 * build one giant request; every API here is in ExcelApi 1.9 or lower.
 */
export const BATCH_ROWS = 2000;
const STAMP = "ifc_bundle";

/** Column letter for a 0-based index (A..Z, AA..). */
function col(i) {
  let s = "";
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(64 + ((n - 1) % 26) + 1) + s;
  return s;
}

/** Office.js refuses a sheet name over 31 characters or with []:*?/\ in it. */
export function sheetName(name) {
  return String(name).replace(/[[\]:*?/\\]/g, "-").slice(0, 31);
}

async function sheetOrNew(ctx, name) {
  const s = ctx.workbook.worksheets.getItemOrNullObject(name);
  await ctx.sync();
  if (!s.isNullObject) return s;
  return ctx.workbook.worksheets.add(name);
}

/**
 * Write `table` (2-D array, header first) to the sheet `name`, replacing
 * what was there. Hidden sheets hold the origin copy. Returns the row count.
 */
export async function writeTable(name, table, { hidden = false, freeze = true } = {}) {
  const n = sheetName(name);
  await Excel.run(async (ctx) => {
    const sheet = await sheetOrNew(ctx, n);
    sheet.getRange().clear();
    const width = Math.max(1, ...table.map((r) => r.length));
    for (let start = 0; start < table.length; start += BATCH_ROWS) {
      const rows = table.slice(start, start + BATCH_ROWS).map((r) => [...r, ...Array(width - r.length).fill("")]);
      sheet.getRangeByIndexes(start, 0, rows.length, width).values = rows;
      await ctx.sync();                                            // one batch per round trip
    }
    if (table.length) {
      sheet.getRangeByIndexes(0, 0, 1, width).format.font.bold = true;
      if (freeze && !hidden) sheet.freezePanes.freezeRows(1);     // 1.7
      sheet.getRangeByIndexes(0, 0, Math.max(1, table.length), width).format.autofitColumns();
    }
    sheet.visibility = hidden ? "Hidden" : "Visible";
    await ctx.sync();
  });
  return table.length;
}

/** The used range of sheet `name` as a 2-D array, or null when the sheet is missing or empty. */
export async function readTable(name) {
  let out = null;
  await Excel.run(async (ctx) => {
    const sheet = ctx.workbook.worksheets.getItemOrNullObject(sheetName(name));
    await ctx.sync();
    if (sheet.isNullObject) return;
    const used = sheet.getUsedRangeOrNullObject(true);
    used.load("values");
    await ctx.sync();
    if (!used.isNullObject) out = used.values;
  });
  return out;
}

export async function activate(name) {
  await Excel.run(async (ctx) => {
    const sheet = ctx.workbook.worksheets.getItemOrNullObject(sheetName(name));
    await ctx.sync();
    if (!sheet.isNullObject) { sheet.activate(); await ctx.sync(); }
  });
}

/** The custom document property that remembers the loaded bundle. */
export async function setStamp(text) {
  await Excel.run(async (ctx) => {
    const props = ctx.workbook.properties.custom;
    const existing = props.getItemOrNullObject(STAMP);
    await ctx.sync();
    if (!existing.isNullObject) existing.delete();
    props.add(STAMP, text);
    await ctx.sync();
  });
}

export async function getStamp() {
  let text = null;
  await Excel.run(async (ctx) => {
    const it = ctx.workbook.properties.custom.getItemOrNullObject(STAMP);
    it.load("value");
    await ctx.sync();
    if (!it.isNullObject) text = String(it.value);
  });
  return text;
}

/** {sheet, row (0-based), globalId} for the active cell when its sheet is one of `sheets` and column A holds a GlobalId; else null. */
export async function activeGlobalId(sheets) {
  let out = null;
  await Excel.run(async (ctx) => {
    const sheet = ctx.workbook.worksheets.getActiveWorksheet();
    const cell = ctx.workbook.getActiveCell();
    sheet.load("name");
    cell.load("rowIndex");
    await ctx.sync();
    if (!sheets.includes(sheet.name) || cell.rowIndex === 0) return;
    const a = sheet.getRangeByIndexes(cell.rowIndex, 0, 1, 1);
    a.load("values");
    await ctx.sync();
    const gid = String(a.values[0][0] || "");
    if (gid) out = { sheet: sheet.name, row: cell.rowIndex, globalId: gid };
  });
  return out;
}

/** Select the row of `globalId` in sheet `name` (column A), activating the sheet. Returns true when found. */
export async function selectRow(name, globalId) {
  let found = false;
  await Excel.run(async (ctx) => {
    const sheet = ctx.workbook.worksheets.getItemOrNullObject(sheetName(name));
    await ctx.sync();
    if (sheet.isNullObject) return;
    const used = sheet.getUsedRangeOrNullObject(true);
    used.load("rowCount, columnCount");
    await ctx.sync();
    if (used.isNullObject) return;
    const a = sheet.getRangeByIndexes(0, 0, used.rowCount, 1);
    a.load("values");
    await ctx.sync();
    const row = a.values.findIndex((r) => String(r[0]) === globalId);
    if (row < 0) return;
    sheet.activate();
    sheet.getRangeByIndexes(row, 0, 1, used.columnCount).select();
    await ctx.sync();
    found = true;
  });
  return found;
}

/** Write `value` into the active cell. Returns its address. */
export async function writeActiveCell(value) {
  let address = "";
  await Excel.run(async (ctx) => {
    const cell = ctx.workbook.getActiveCell();
    cell.values = [[value]];
    cell.load("address");
    await ctx.sync();
    address = cell.address;
  });
  return address;
}

/** Append `row` under the header of sheet `name`, creating the sheet with `header` when missing. Returns the 1-based row number. */
export async function appendRow(name, header, row) {
  let at = 0;
  await Excel.run(async (ctx) => {
    const sheet = await sheetOrNew(ctx, sheetName(name));
    const used = sheet.getUsedRangeOrNullObject(true);
    used.load("rowCount");
    await ctx.sync();
    let next = 0;
    if (used.isNullObject) {
      sheet.getRangeByIndexes(0, 0, 1, header.length).values = [header];
      sheet.getRangeByIndexes(0, 0, 1, header.length).format.font.bold = true;
      next = 1;
    } else {
      next = used.rowCount;
    }
    sheet.getRangeByIndexes(next, 0, 1, row.length).values = [row];
    await ctx.sync();
    at = next + 1;
  });
  return at;
}

/** Call `fn` whenever the selection changes anywhere in the workbook (ExcelApi 1.2). */
export async function onSelectionChanged(fn) {
  await Excel.run(async (ctx) => {
    ctx.workbook.onSelectionChanged.add(async () => { try { await fn(); } catch { /* the pane re-reads on its next change */ } });
    await ctx.sync();
  });
}

/** Column letter helper, exported for the pane's status text. */
export { col as colLetter };
