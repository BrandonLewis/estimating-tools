/* global Excel, Office */
/**
 * Everything that touches Excel. core/ never sees an Excel object: this
 * module reads plain arrays out of the workbook and performs the few writes
 * (select, write a code, insert template rows), each in one Excel.run batch.
 *
 * Every API here is in ExcelApi 1.9 or lower (the manifest's MinVersion).
 * Workbook.isDirty is listed at 1.9 too, but readDirty still feature-detects
 * it: a host that cannot answer gets the "save first" reminder, not an error.
 */
import { colLetter, colIndex } from "../core/refs.js";
import { blankRuns, visibleFromRuns } from "../core/readback-common.js";

/**
 * Ranges behind workbook-scoped names, or null for a name that is missing or
 * not a range. Two syncs on purpose: the names are resolved first and a range
 * is asked for only on a name that exists, so nothing relies on how a host
 * treats a method called on a null object.
 */
async function rangesOf(ctx, names, props) {
  const items = names.map((n) => {
    const it = ctx.workbook.names.getItemOrNullObject(n);
    it.load("type");
    return it;
  });
  await ctx.sync();
  const ranges = items.map((it) => {
    if (it.isNullObject || it.type !== "Range") return null;
    const rng = it.getRange();
    rng.load(props);
    return rng;
  });
  if (ranges.some(Boolean)) await ctx.sync();
  return ranges;
}

/** {name: text | null} for each custom document property; null when the workbook has none by that name. A number, date or yes/no property comes back as text. */
async function propsOf(ctx, names) {
  const items = names.map((n) => {
    const it = ctx.workbook.properties.custom.getItemOrNullObject(n);   // ExcelApi 1.7
    it.load("value");
    return it;
  });
  await ctx.sync();
  return Object.fromEntries(names.map((n, i) => [n, items[i].isNullObject ? null : String(items[i].value ?? "")]));
}

/**
 * What every adapter's detect needs, in one Excel.run: the custom properties
 * `props`, the first cell of each defined name in `cells` (null when the name
 * is missing or not a range), the sheet names and the active sheet.
 *
 * A long layout JSON lives in a named cell (`est.layout` on the hidden
 * `_templates` sheet), not in a custom property: desktop Excel trims a custom
 * document property to 255 characters, so the `estimate_layout` property
 * holds only the layout version and serves as a marker.
 */
export async function readFacts({ props, cells }) {
  return Excel.run(async (ctx) => {
    const sheets = ctx.workbook.worksheets;
    sheets.load("items/name");
    const active = sheets.getActiveWorksheet();
    active.load("name");
    const found = await propsOf(ctx, props);       // this sync loads the sheets too
    const ranges = cells.length ? await rangesOf(ctx, cells, "values") : [];
    return {
      props: found,
      cells: Object.fromEntries(cells.map((n, i) => [n, ranges[i] ? ranges[i].values[0][0] : null])),
      sheetNames: sheets.items.map((s) => s.name),
      activeSheet: active.name,
    };
  });
}

/** One custom document property's value, or null when the workbook has none by that name. */
export async function readProperty(name) {
  return Excel.run(async (ctx) => (await propsOf(ctx, [name]))[name]);
}

/** The values (2-D) of the range behind a workbook-scoped name, or null when the name is missing or not a range. */
export async function readNamedValues(name) {
  return Excel.run(async (ctx) => {
    const [rng] = await rangesOf(ctx, [name], "values");
    return rng ? rng.values : null;
  });
}

/** The most rows readColumns and readActiveColumns read from one sheet; the same cap as SCAN_MAX_ROWS. */
export const READ_MAX_ROWS = 20000;

/**
 * Columns `cols` of `ws` from row 1 to the last row of `used` (already
 * loaded with rowIndex and rowCount), capped at READ_MAX_ROWS:
 * {last, truncated, columns: {col: values}}, where values[i] is row i+1's.
 */
async function columnsOf(ctx, ws, used, cols) {
  const end = used.isNullObject ? 1 : used.rowIndex + used.rowCount;
  const last = Math.min(end, READ_MAX_ROWS);
  const ranges = cols.map((c) => {
    const r = ws.getRange(`${c}1:${c}${last}`);
    r.load("values");
    return r;
  });
  await ctx.sync();
  return { last, truncated: end > READ_MAX_ROWS,
           columns: Object.fromEntries(cols.map((c, i) => [c, ranges[i].values.map((row) => row[0])])) };
}

/**
 * Raw values of columns `cols` (letters) on `sheet`, from row 1 to the last
 * used row, at most READ_MAX_ROWS: {last, truncated, columns: {col: values}},
 * where values[i] is row i+1's value. null when there is no sheet by that name.
 */
export async function readColumns(sheet, cols) {
  return Excel.run(async (ctx) => {
    const ws = ctx.workbook.worksheets.getItemOrNullObject(sheet);
    await ctx.sync();
    if (ws.isNullObject) return null;
    const used = ws.getUsedRangeOrNullObject(true);
    used.load(["rowIndex", "rowCount"]);
    await ctx.sync();
    return columnsOf(ctx, ws, used, cols);
  });
}

/**
 * The active cell's sheet and row, plus the raw values of columns `cols` on
 * that sheet as readColumns reads them (capped, with `truncated`).
 */
export async function readActiveColumns(cols) {
  return Excel.run(async (ctx) => {
    const cell = ctx.workbook.getActiveCell();
    cell.load("rowIndex");
    const ws = ctx.workbook.worksheets.getActiveWorksheet();
    ws.load("name");
    const used = ws.getUsedRangeOrNullObject(true);
    used.load(["rowIndex", "rowCount"]);
    await ctx.sync();
    return { sheet: ws.name, row: cell.rowIndex + 1, ...(await columnsOf(ctx, ws, used, cols)) };
  });
}

/** {name: {values, formulas, address} | null} for each workbook-scoped name. */
export async function readNames(names) {
  return Excel.run(async (ctx) => {
    const ranges = await rangesOf(ctx, names, ["values", "formulas", "address"]);
    return Object.fromEntries(names.map((n, i) => {
      const r = ranges[i];
      return [n, r ? { values: r.values, formulas: r.formulas, address: r.address } : null];
    }));
  });
}

/** values and formulas of A1:{lastCol}{rows} on `sheet`. */
export async function readBlock(sheet, lastCol, rows) {
  return Excel.run(async (ctx) => {
    const rng = ctx.workbook.worksheets.getItem(sheet).getRange(`A1:${lastCol}${rows}`);
    rng.load(["values", "formulas"]);
    await ctx.sync();
    return { values: rng.values, formulas: rng.formulas };
  });
}

/** The active cell's sheet and row, plus that sheet's kind and code-chain columns. */
export async function readActive(tags) {
  return Excel.run(async (ctx) => {
    const cell = ctx.workbook.getActiveCell();
    cell.load("rowIndex");
    const ws = ctx.workbook.worksheets.getActiveWorksheet();
    ws.load("name");
    const used = ws.getUsedRangeOrNullObject(true);
    used.load(["rowIndex", "rowCount"]);
    await ctx.sync();
    const last = used.isNullObject ? 1 : used.rowIndex + used.rowCount;
    const kinds = ws.getRange(`${tags.kind}1:${tags.kind}${last}`);
    const chain = ws.getRange(`${tags.code_chain}1:${tags.code_chain}${last}`);
    kinds.load("values");
    chain.load("values");
    await ctx.sync();
    return { sheet: ws.name, row: cell.rowIndex + 1,
             kinds: kinds.values.map((r) => (r[0] == null ? "" : String(r[0]).trim())),
             chain: chain.values.map((r) => (r[0] == null ? "" : String(r[0]).trim())) };
  });
}

/** Only the active sheet's name: the cheap read a selection change needs. */
export async function readActiveSheetName() {
  return Excel.run(async (ctx) => {
    const ws = ctx.workbook.worksheets.getActiveWorksheet();
    ws.load("name");
    await ctx.sync();
    return ws.name;
  });
}

/**
 * Activate `sheet`; when `addr` is given, select it too. Returns
 * {hidden: true} without navigating when the sheet is hidden, since Excel
 * cannot activate a hidden sheet.
 */
export async function go(sheet, addr) {
  return Excel.run(async (ctx) => {
    const ws = ctx.workbook.worksheets.getItem(sheet);
    ws.load("visibility");
    await ctx.sync();
    if (ws.visibility !== "Visible") return { hidden: true };
    ws.activate();
    if (addr) ws.getRange(addr.replace(/\$/g, "")).select();
    await ctx.sync();
    return { hidden: false };
  });
}

export async function writeCell(sheet, addr, value) {
  return Excel.run(async (ctx) => {
    ctx.workbook.worksheets.getItem(sheet).getRange(addr).values = [[value]];
    await ctx.sync();
  });
}

/**
 * Insert the template rows named `tplName` at row `at` on `sheet`, with
 * Excel's own copy. Selecting the new rows is a separate sync whose failure
 * is ignored: the insert has already happened, and a selection the host
 * refuses must not be reported as a failed insert.
 */
export async function insertTemplate(sheet, at, tplName) {
  return Excel.run(async (ctx) => {
    const src = ctx.workbook.names.getItem(tplName).getRange();
    src.load("rowCount");
    await ctx.sync();
    const ws = ctx.workbook.worksheets.getItem(sheet);
    const rows = `${at}:${at + src.rowCount - 1}`;
    ws.getRange(rows).insert(Excel.InsertShiftDirection.down);
    const dest = ws.getRange(rows);
    dest.copyFrom(src, Excel.RangeCopyType.all);
    await ctx.sync();
    try {
      dest.select();
      await ctx.sync();
    } catch { /* cosmetic only */ }
    return { first: at, last: at + src.rowCount - 1 };
  });
}

/** true / false, or null where the host has no Workbook.isDirty. */
export async function readDirty() {
  try {
    return await Excel.run(async (ctx) => {
      ctx.workbook.load("isDirty");
      await ctx.sync();
      return typeof ctx.workbook.isDirty === "boolean" ? ctx.workbook.isDirty : null;
    });
  } catch {
    return null;
  }
}

/** Item sheets scanned per sync, and the longest sheet scanned in the pane at all. */
export const SCAN_CHUNK = 10;
export const SCAN_MAX_ROWS = 20000;

/**
 * The read-back scan of every item sheet (kind ITEM in rows 1-5), skipping
 * _templates. Returns {sheets: [{sheet, visible, kinds}], tooLarge: [name]}.
 *
 * Phase 1 is one sync for every sheet's first five kinds and used range.
 * Phase 2 walks the item sheets SCAN_CHUNK at a time: one sync loads the
 * chunk's kind columns, a second loads the visible cells of only the rows
 * whose kind is blank (in runs), since a row with a kind is tagged whatever
 * it shows. A sheet past SCAN_MAX_ROWS is listed in `tooLarge`, unread.
 */
export async function scanItemSheets(tags, itemKind) {
  const lastVisible = colLetter(colIndex(tags.kind) - 1);
  return Excel.run(async (ctx) => {
    const sheets = ctx.workbook.worksheets;
    sheets.load("items/name");
    await ctx.sync();
    const heads = sheets.items.filter((s) => s.name !== "_templates").map((s) => {
      const r = s.getRange(`${tags.kind}1:${tags.kind}5`);
      r.load("values");
      const used = s.getUsedRangeOrNullObject(true);
      used.load(["rowIndex", "rowCount"]);
      return { s, r, used };
    });
    await ctx.sync();
    const items = heads.filter(({ r }) => r.values.some((v) => String(v[0]).trim() === itemKind))
      .map(({ s, used }) => ({ s, last: used.isNullObject ? 1 : used.rowIndex + used.rowCount }));
    const tooLarge = items.filter((i) => i.last > SCAN_MAX_ROWS).map((i) => i.s.name);
    const todo = items.filter((i) => i.last <= SCAN_MAX_ROWS);
    const out = [];
    for (let c = 0; c < todo.length; c += SCAN_CHUNK) {
      const chunk = todo.slice(c, c + SCAN_CHUNK).map(({ s, last }) => {
        const k = s.getRange(`${tags.kind}1:${tags.kind}${last}`);
        k.load("values");
        return { s, k };
      });
      await ctx.sync();
      const withRuns = chunk.map(({ s, k }) => {
        const kinds = k.values.map((r) => r[0]);
        const runs = blankRuns(kinds);
        const ranges = runs.map((run) => {
          const v = s.getRange(`A${run.first}:${lastVisible}${run.last}`);
          v.load("values");
          return v;
        });
        return { name: s.name, kinds, runs, ranges };
      });
      if (withRuns.some((w) => w.ranges.length)) await ctx.sync();
      for (const { name, kinds, runs, ranges } of withRuns) {
        out.push({ sheet: name, kinds, visible: visibleFromRuns(kinds.length, runs, ranges.map((v) => v.values)) });
      }
    }
    return { sheets: out, tooLarge };
  });
}

export function documentUrl() {
  return (Office.context && Office.context.document && Office.context.document.url) || "";
}

/**
 * Subscribe to the workbook events that should refresh the pane. Office.js
 * always defines these event getters, so nothing here can test for support:
 * on a host without one, the registration sync rejects, and main.js catches
 * that and runs without live refresh. All are ExcelApi 1.9 or lower.
 */
export async function watch(onChange, onActivated) {
  return Excel.run(async (ctx) => {
    const sheets = ctx.workbook.worksheets;
    sheets.onChanged.add(async () => onChange());                 // ExcelApi 1.9
    sheets.onAdded.add(async () => onChange());                   // ExcelApi 1.7
    sheets.onDeleted.add(async () => onChange());                 // ExcelApi 1.7
    sheets.onActivated.add(async () => onActivated());            // ExcelApi 1.7
    ctx.workbook.onSelectionChanged.add(async () => onActivated());   // ExcelApi 1.2
    await ctx.sync();
  });
}
