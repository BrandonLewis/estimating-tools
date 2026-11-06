/**
 * The pack-adapter interface. Each workbook family (fieldbook today) has one
 * adapter; main.js asks the adapters, in order, whether the open workbook is
 * theirs, and the panes render whatever the chosen adapter returns.
 *
 * Pure: no Office.js. An adapter reaches Excel only through `x`, the thin
 * wrapper main.js builds over panes/excel.js, and everything it computes from
 * what `x` returned is a plain function that runs under `node --test`.
 */

/**
 * @typedef {object} Facts  What every detect sees, read in one Excel.run.
 * @property {Object<string, string|null>} props  each requested custom document property's value; null when absent
 * @property {Object<string, *>} cells  the first cell's raw value of each requested defined name; null when the name is missing or not a range
 * @property {string[]} sheetNames  every worksheet, in tab order
 * @property {string} activeSheet
 */

/**
 * @typedef {"yes"|"newer"|"bad"|"no"} Verdict
 * yes: this adapter reads the workbook. newer: it is this adapter's, built
 * with a layout newer than it knows ("update Estimate Navigator"). bad: it is
 * this adapter's, but its stamp is damaged. no: not this adapter's.
 */

/**
 * @typedef {object} Jump  Where a click goes.
 * @property {string} sheet
 * @property {number} [row]  1-based; with `cols`, selects those cells of that row
 * @property {string} [cols]  "A:R" for a span, "K" for one cell; default "A"
 * @property {string} [addr]  a literal address ("$K$30"); wins over row/cols
 */

/**
 * @typedef {object} ItemStatus
 * @property {number} fails  failing checks naming this row; 0 shows ✓
 */

/**
 * @typedef {object} ItemRow  One row of the Items tree.
 * @property {string} key  unique across the whole tree; keeps keyboard focus across a re-render
 * @property {string} no  the item number column; "" on a nested row
 * @property {string} label  the description column
 * @property {number|null} cost
 * @property {string} [note]  a second, muted line under the label
 * @property {ItemStatus|null} [status]  null or absent: no ✓/✗ shown
 * @property {boolean} [total]  the bottom total row
 * @property {Jump|null} jump  click; null means a typed row, not a link
 * @property {Jump|null} [focus]  double-click, Enter or Space; defaults to `jump`
 * @property {ItemRow[]} children  nested rows, rendered indented under this one
 */

/**
 * @typedef {object} CheckRow
 * @property {"pass"|"fail"|"info"} status  info rows are listed apart and never counted
 * @property {string} item  what the check names, as shown ("Item 3", "All items")
 * @property {string} rule
 * @property {string} [ref]  shown after the item on a failing row ("check 9")
 * @property {string} [text]  the figures, a muted line under the rule
 * @property {Jump|null} jump  null disables the row's button
 */

/**
 * @typedef {object} InsertKind  One Insert button.
 * @property {string} what  passed back to planInsert
 * @property {string} label
 * @property {string} sub  one line under the label
 */

/**
 * @typedef {object} InsertPlan
 * @property {string} sheet
 * @property {number} at  1-based row the template's first row lands on (whole rows inserted there)
 * @property {string} template  the defined name of the prototype rows
 * @property {string} [fill]  replaces "Fill in the blank cells." in the success note
 * @property {string} [confirm]  asked first: the pane shows it and inserts on the second click
 */

/** @typedef {{refused: string}} InsertRefusal */

/**
 * @typedef {object} ReadinessRow  One line of Read back's list.
 * @property {boolean} ok
 * @property {boolean} [advisory]  listed, but does not hold the copy button back
 * @property {string} text
 * @property {string} [sub]
 * @property {Jump} [jump]  shows a Go button
 */

/**
 * @typedef {object} ReadbackCommand
 * @property {string|null} command  the text Copy command puts on the clipboard; null when it cannot be built
 * @property {string} why  shown in place of the command when it is null
 * @property {string} note  shown under the button
 */

/**
 * @typedef {object} X  The wrapper main.js hands to adapters and panes; panes/excel.js underneath.
 * @property {(sheet: string, addr: string|null) => Promise<void>} go  activates the sheet and selects addr; says so when the sheet is hidden
 * @property {(jump: Jump) => Promise<void>} jump  go(jump.sheet, jumpAddress(jump))
 * @property {(name: string) => Promise<string|null>} readProperty  a custom document property's value
 * @property {(name: string) => Promise<Array<Array<*>>|null>} readNamedValues  the values behind a defined name
 * @property {(sheet: string, cols: string[]) => Promise<{last: number, truncated: boolean, columns: Object<string, Array<*>>}|null>} readColumns  raw values, rows 1..last used, at most READ_MAX_ROWS (truncated: true when the sheet runs past it); columns[c][i] is row i+1; null without that sheet
 * @property {(cols: string[]) => Promise<{sheet: string, row: number, last: number, truncated: boolean, columns: Object<string, Array<*>>}>} readActiveColumns  the active cell's sheet and row, and those columns of its sheet, capped as readColumns
 * @property {(names: string[]) => Promise<Object<string, {values: Array<Array<*>>, formulas: Array<Array<*>>, address: string}|null>>} readNames
 * @property {(sheet: string, lastCol: string, rows: number) => Promise<{values: Array<Array<*>>, formulas: Array<Array<*>>}>} readBlock
 * @property {(tags: {kind: string, code_chain: string}) => Promise<{sheet: string, row: number, kinds: string[], chain: string[]}>} readActive
 * @property {(tags: {kind: string}, itemKind: string) => Promise<{sheets: Array<{sheet: string, kinds: Array<*>, visible: Array<Array<*>>}>, tooLarge: string[]}>} scanItemSheets
 * @property {(sheet: string, at: number, template: string) => Promise<{first: number, last: number}>} insertTemplate  whole rows at `at`, Excel's own copy, one Excel.run
 * @property {(sheet: string, addr: string, value: *) => Promise<void>} writeCell
 * @property {() => Promise<boolean|null>} readDirty  null where the host cannot say
 * @property {() => string} documentUrl
 * @property {() => Promise<void>} refresh
 * @property {() => boolean} current  false once a newer render has started
 */

/**
 * @typedef {object} Adapter
 * @property {string} id
 * @property {string[]} props  custom document properties detect reads
 * @property {string[]} cells  defined names whose first cell detect reads
 * @property {string} noCell  shown when the selection has no active cell
 * @property {(facts: Facts) => Verdict} detect  pure and cheap; should not throw: a throw counts as "no"
 * @property {(x: X, facts: Facts) => Promise<object>} load  the layout, on a "yes"
 * @property {(facts: Facts) => string} damage  the message for a "bad"
 * @property {(layout: object) => string[]} tabs  a subset of TAB_ORDER, in that order
 * @property {(layout: object) => string} source  the line under the pane's name
 * @property {(layout: object) => object|null} [brand]  the workbook's brand section, if any
 * @property {(x: X, layout: object, facts: Facts) => Promise<{items: ItemRow[], checks: CheckRow[]|null, codes: object[]}>} read
 * @property {(x: X, layout: object) => Promise<object>} readCursor  ctx for planInsert; must carry sheet and row
 * @property {(layout: object) => InsertKind[]} insertKinds
 * @property {(layout: object) => string} insertFooter
 * @property {(what: string, ctx: object) => InsertPlan|InsertRefusal} planInsert  may throw on a `what` not in insertKinds
 * @property {(x: X, layout: object) => Promise<object>} scan  the slow read-back scan; the pane caches it
 * @property {(layout: object, got: {dirty: boolean|null, scan: object}) => ReadinessRow[]} readiness
 * @property {(layout: object, file: {name: string, cloud: boolean}) => ReadbackCommand} readbackCommand
 */

export const VERDICTS = Object.freeze(["yes", "newer", "bad", "no"]);
export const TAB_ORDER = Object.freeze(["items", "checks", "codes", "insert", "readback"]);
const METHODS = ["detect", "load", "damage", "tabs", "source", "read", "readCursor", "insertKinds",
                 "insertFooter", "planInsert", "scan", "readiness", "readbackCommand"];

/** Throws naming everything `a` is missing; returns `a` when it is a whole adapter. */
export function assertAdapter(a) {
  const missing = METHODS.filter((m) => typeof a?.[m] !== "function");
  if (typeof a?.id !== "string" || !a.id) missing.unshift("id");
  for (const k of ["props", "cells"]) if (!Array.isArray(a?.[k])) missing.push(k);
  if (typeof a?.noCell !== "string") missing.push("noCell");
  if (missing.length) throw new Error(`adapter ${a?.id || "?"} is missing ${missing.join(", ")}`);
  return a;
}

/** Every adapter's properties and cells, each once, in first-seen order: what readFacts reads. */
export function factRequest(adapters) {
  const props = [], cells = [];
  for (const a of adapters) {
    for (const p of a.props || []) if (!props.includes(p)) props.push(p);
    for (const c of a.cells || []) if (!cells.includes(c)) cells.push(c);
  }
  return { props, cells };
}

/**
 * The first adapter, in order, whose verdict is not "no": {adapter, verdict}.
 * newer and bad claim the workbook too, so it never falls through to a later
 * adapter or the heuristic. null when no adapter claims it.
 *
 * A detect that throws counts as "no" (with a console warning), not "bad":
 * it may have thrown on a workbook that is not its own, and "bad" would claim
 * that workbook and hide it from every later adapter and the heuristic.
 */
export function pick(adapters, facts) {
  for (const adapter of adapters) {
    let verdict;
    try { verdict = adapter.detect(facts); } catch (e) {
      console.warn(`Estimate Navigator: ${adapter.id}: detect threw; treated as no`, e);
      continue;
    }
    if (!VERDICTS.includes(verdict)) throw new Error(`${adapter.id}: detect returned ${verdict}`);
    if (verdict !== "no") return { adapter, verdict };
  }
  return null;
}

/** The tabs a pane state shows, in display order. */
export function tabsOf(state) {
  if (state.kind === "heuristic") return ["items"];
  if (state.kind !== "ok") return [];
  const want = new Set(state.adapter.tabs(state.layout));
  return TAB_ORDER.filter((t) => want.has(t));
}

/** The line under the pane's name. */
export function sourceOf(state) {
  if (state.kind === "ok") return state.adapter.source(state.layout);
  return state.kind === "heuristic" ? "Hand-built workbook" : "";
}

/** The address a Jump selects, or null to only activate its sheet. */
export function jumpAddress(jump) {
  if (!jump) return null;
  if (jump.addr) return jump.addr;
  if (!Number.isInteger(jump.row) || jump.row < 1) return null;
  const [a, b = a] = String(jump.cols || "A").split(":");
  return a === b ? `${a}${jump.row}` : `${a}${jump.row}:${b}${jump.row}`;
}

/** The tree in display order, each row with its depth (0 = top level). */
export function flattenTree(rows, depth = 0, out = []) {
  for (const row of rows) {
    out.push({ row, depth });
    flattenTree(row.children || [], depth + 1, out);
  }
  return out;
}

/** Checks split for display: failures first; info rows apart and left out of the counts. */
export function summarizeChecks(rows) {
  const failing = rows.filter((r) => r.status === "fail");
  const passing = rows.filter((r) => r.status === "pass");
  const info = rows.filter((r) => r.status === "info");
  return { pass: passing.length, fail: failing.length, failing, passing, info };
}
