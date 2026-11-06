/**
 * The fieldbook adapter: workbooks `est-estimate build` stamps from a pack
 * with a `layout_map:` (fieldbook, or an org pack derived from it).
 *
 * The logic below moved here unchanged from core/stamp.js, blocks.js,
 * insert.js, items.js, checks.js and readback.js; those files now only
 * re-export it. The `fieldbook` object at the end puts it behind the adapter
 * interface (core/adapter.js).
 */
import { cellNumber, cellText, tryParseRef } from "../refs.js";
import { legacyToTree, withTotal } from "../rows.js";
import { untaggedRows } from "../readback-common.js";
import { codeList } from "../codes.js";

// ---- The stamp (was core/stamp.js) ----

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

// ---- Task blocks (was core/blocks.js) ----

/**
 * Task blocks on an item sheet, found from the hidden kind column.
 * `kinds[i]` is row i+1's tag. A block runs from its head row through its
 * subtotal row and must have an end row in between.
 */
export function findBlock(kinds, row, blocks) {
  if (row < 1 || row > kinds.length) return null;
  const member = new Set([blocks.head, ...blocks.body, blocks.end, blocks.sub, ""]);
  let head = null;
  for (let r = row; r >= 1; r -= 1) {
    const k = kinds[r - 1] || "";
    if (k === blocks.head) { head = r; break; }
    if (k === blocks.sub && r !== row) return null;     // we are below a closed block
    if (!member.has(k)) return null;
  }
  if (head === null) return null;
  let end = null;
  for (let r = head + 1; r <= kinds.length; r += 1) {
    const k = kinds[r - 1] || "";
    if (k === blocks.end && end === null) end = r;
    else if (k === blocks.sub) return end !== null && row <= r ? { head, end, sub: r } : null;
    else if (k === blocks.head || !member.has(k)) return null;
  }
  return null;
}

// ---- Insert placement (was core/insert.js) ----

/**
 * Where the Insert tab puts new rows. The add-in writes no formulas: it
 * copies prototype rows from the hidden _templates sheet (named est.tpl.*)
 * with Excel's own copy, the same operation as an estimator's copy-paste.
 */
const TEMPLATE = { task: "est.tpl.task", crew: "est.tpl.crew", line: "est.tpl.line" };

export function planInsert(what, kinds, row, blocks) {
  const tpl = TEMPLATE[what];
  if (!tpl) throw new Error(`unknown insert kind ${what}`);
  const block = findBlock(kinds, row, blocks);
  if (!block) return { ok: false, reason: "Put the cursor inside a task block first (from its header row down to its subtotal)." };
  if (what === "task") return { ok: true, at: block.sub + 1, tpl, block };
  if (row > block.end) {
    return { ok: false, reason: "The cursor is below this task's END row, outside its subtotal. Move it between the task header and END." };
  }
  // A crew/line insert at or above the task's note rows would land above
  // them, prying them loose from the header they document. blocks.body's
  // first entry is the note kind (fieldbook: [NOTE, CREW, LINE]); skip past
  // any run of it directly under the head so a note always stays on top.
  const noteKind = blocks.body[0];
  let afterNotes = block.head + 1;
  while ((kinds[afterNotes - 1] || "") === noteKind) afterNotes += 1;
  return { ok: true, at: Math.max(row, afterNotes), tpl, block };
}

// ---- Index rows (was core/items.js) ----

/** Each argument is a single-column 2-D array, as Excel's range.values/formulas return. */
export function itemsFromTable({ itemNo, descr, cost, link, sheetNames }) {
  const existing = new Set(sheetNames.map((n) => n.toUpperCase()));
  const rows = [];
  for (let i = 0; i < itemNo.length; i += 1) {
    const no = cellText(itemNo[i]?.[0]).trim();
    if (!no) continue;
    const ref = tryParseRef(link[i]?.[0]);
    const ok = ref && existing.has(ref.sheet.toUpperCase());
    rows.push({ itemNo: no, descr: cellText(descr[i]?.[0]), cost: cellNumber(cost[i]?.[0]),
                sheetName: ok ? ref.sheet : "", totalAddr: ok ? ref.addr : "", isTotal: false });
  }
  return rows;
}

// ---- Checks (was core/checks.js) ----

/** The Checks table, as Excel evaluated it. The add-in never recomputes a check. */
export const PASS = "✓";
export const FAIL = "✗";

export function checksFromTable({ ruleNo, rule, item, status }) {
  const rows = [];
  for (let i = 0; i < status.length; i += 1) {
    const s = cellText(status[i]?.[0]).trim();
    if (s !== PASS && s !== FAIL) continue;
    rows.push({ ruleNo: cellText(ruleNo[i]?.[0]), rule: cellText(rule[i]?.[0]),
                item: cellText(item[i]?.[0]).trim(), ok: s === PASS });
  }
  const failing = rows.filter((r) => !r.ok);
  const passing = rows.filter((r) => r.ok);
  return { pass: passing.length, fail: failing.length, rows: [...failing, ...passing] };
}

/** Map item number -> count of its failing checks. */
export function failingByItem(checks) {
  const m = new Map();
  for (const r of checks.rows) if (!r.ok && r.item) m.set(r.item, (m.get(r.item) || 0) + 1);
  return m;
}

// ---- Read back (was core/readback.js) ----

/**
 * Packs `est-estimate read-back` can read today -- and so any pack that
 * declares `derived_from:` one of them (an org fork that keeps its grid),
 * which the layout JSON carries as `derived_from`.
 */
export const READBACK_PACKS = new Set(["fieldbook"]);

/** True when read-back reads workbooks laid out by `layout`'s pack. */
export function readbackSupported(layout) {
  return READBACK_PACKS.has(layout?.pack) || READBACK_PACKS.has(layout?.derived_from);
}

/**
 * The readiness list. A row with `advisory: true` is a reminder the pane
 * shows but does not hold the command back for: the host cannot say whether
 * the workbook is saved, or a sheet was too large to scan here (read-back
 * itself still checks it).
 */
export function readiness({ layout, dirty, untagged, tooLarge = [] }) {
  const supported = readbackSupported(layout);
  const packs = [...READBACK_PACKS].join(", ");
  const rows = [
    { ok: !!layout, text: "Built by est-estimate", sub: layout ? `${layout.pack} pack` : "No estimate_layout stamp" },
    { ok: supported, text: "Read-back supports this pack", sub: supported ? "" : `Read-back reads ${packs} workbooks, or a pack derived from ${packs}` },
    dirty === false
      ? { ok: true, text: "No unsaved changes", sub: "" }
      : dirty === true
        ? { ok: false, text: "Unsaved changes", sub: "Save the workbook, then check again." }
        : { ok: false, advisory: true, text: "Save the workbook first", sub: "Excel here cannot say whether it has unsaved changes." },
    untagged.length
      ? { ok: false, text: "Rows outside the tagged blocks", sub: untagged.slice(0, 5).join("; ") + (untagged.length > 5 ? "; …" : "") }
      : { ok: true, text: "Every row sits inside a tagged block", sub: "" },
  ];
  if (tooLarge.length) {
    rows.push({ ok: false, advisory: true, text: "Some sheets were not checked",
                sub: tooLarge.map((s) => `${s}: too large to check here; read-back will still check it`).join("; ") });
  }
  return rows;
}

// `spec` comes from an editable workbook cell. PowerShell, bash and cmd all
// expand `$`, a backtick or `%` inside double quotes, so a quoted name is not
// enough: only a bare, punctuation-limited file name is ever interpolated
// into the shell command. No path separators, so a name cannot escape into
// another directory either.
const SAFE_SPEC = /^[\p{L}\p{N} _.\-()#&,+']+\.ya?ml$/u;
const SAFE_WORKBOOK = /^[\p{L}\p{N} _.\-()#&,+']+$/u;

/** The read-back command, or null when a name is not safe to interpolate. */
export function command(specName, workbookName) {
  if (!SAFE_SPEC.test(specName || "") || !SAFE_WORKBOOK.test(workbookName || "")) return null;
  return `est-estimate read-back "${specName}" "${workbookName}" --write`;
}

// ---- The adapter ----

/** A workbook-wide check (the unbalance rule) names no one item: its item cell reads "all". */
const WHOLE = "all";
const checkItemLabel = (item) => (item.toLowerCase() === WHOLE ? "All items" : `Item ${item}`);

export const NO_CELL = "Select a cell on an item sheet.";

export const INSERT_KINDS = Object.freeze([
  { what: "task", label: "New task", sub: "A task block (header, crew, line, END, subtotal) below this one. The item total picks it up after read-back and a rebuild." },
  { what: "crew", label: "New crew row", sub: "A crew row inside this task, at the cursor." },
  { what: "line", label: "New line", sub: "A material, equipment or subcontract line inside this task, at the cursor." },
]);

const INSERT_FOOTER = "Rows are copied from the hidden _templates sheet with Excel's own copy, exactly like a copy-paste, so read-back accepts them. Rows are never inserted below a task's END row, so every subtotal still covers them.";
const NO_COMMAND = "This workbook's stamp names no spec file, or the spec or workbook name has characters that are not safe to paste into a terminal, or the workbook has not been saved yet. Run read-back by hand.";
const PASTE_NOTE = "Paste it into a terminal in the workbook's folder. An add-in can't run it for you.";

/**
 * The layout JSON's text, as the pane always read it: null without the
 * `estimate_layout` marker (no stamp); "{}" when the marker is there but the
 * `est.layout` name is missing or not a range, which parseLayout reports as
 * damaged. An empty `est.layout` cell reads as "", which parseLayout treats
 * as no stamp, so the hand-built parser runs, as it always did.
 */
export function layoutText(facts) {
  if (facts.props.estimate_layout === null || facts.props.estimate_layout === undefined) return null;
  const cell = facts.cells["est.layout"];
  return cell === null || cell === undefined ? "{}" : String(cell);
}

/** The defined names a stamped workbook's data comes from, for the tables its layout lists. */
export function namesFor(layout) {
  const names = ["est.index.item_no", "est.index.descr", "est.index.cost", "est.index.link", "est.direct_total"];
  if (layout.tables.includes("checks")) names.push("est.checks.rule_no", "est.checks.rule", "est.checks.item", "est.checks.status");
  if (layout.tables.includes("codes")) names.push("est.codes.code", "est.codes.descr", "est.codes.listed");
  return names;
}

/** "'Cost Summary'!$H$9" -> {sheet: "Cost Summary", addr: "$H$9"}. A quoted sheet name may itself hold "!", so the separator is the last one. */
export function splitAddress(address) {
  const bang = address ? address.lastIndexOf("!") : -1;
  if (bang < 0) return { sheet: "", addr: "" };
  return { sheet: address.slice(0, bang).replace(/^'|'$/g, "").replace(/''/g, "'"), addr: address.slice(bang + 1) };
}

/** Check rows for the pane; each jumps to its item's total, as the pane always did. */
export function checkRows(checks, legacy) {
  const target = (item) => legacy.find((r) => !r.isTotal && r.sheetName && r.itemNo === item);
  return checks.rows.map((r) => {
    const t = target(r.item);
    return { status: r.ok ? "pass" : "fail", item: checkItemLabel(r.item), rule: r.rule, ref: `check ${r.ruleNo}`,
             jump: t ? { sheet: t.sheetName, addr: t.totalAddr } : null };
  });
}

/** The stamped workbook's data from readNames' result, built whole so a render never sees half-old, half-new data. */
export function dataFromNames(layout, n, sheetNames) {
  const v = (k) => n[k]?.values || [];
  const rows = itemsFromTable({ itemNo: v("est.index.item_no"), descr: v("est.index.descr"), cost: v("est.index.cost"),
                                link: n["est.index.link"]?.formulas || [], sheetNames });
  const totalCell = n["est.direct_total"];
  const t = splitAddress(totalCell?.address);
  const checks = layout.tables.includes("checks")
    ? checksFromTable({ ruleNo: v("est.checks.rule_no"), rule: v("est.checks.rule"), item: v("est.checks.item"), status: v("est.checks.status") })
    : null;
  const legacy = withTotal(rows, { total: totalCell?.values?.[0]?.[0], label: "DIRECT", sheet: t.sheet, addr: t.addr });
  return {
    items: legacyToTree(legacy, checks ? failingByItem(checks) : new Map()),
    checks: checks ? checkRows(checks, legacy) : null,
    codes: layout.tables.includes("codes")
      ? codeList({ code: v("est.codes.code"), descr: v("est.codes.descr"), listed: v("est.codes.listed") }) : [],
  };
}

/** @type {import("../adapter.js").Adapter} */
export const fieldbook = Object.freeze({
  id: "fieldbook",
  props: ["estimate_layout"],
  cells: ["est.layout"],
  noCell: NO_CELL,

  detect(facts) {
    const text = layoutText(facts);
    if (text === null) return "no";
    const kind = parseLayout(text).kind;
    return kind === "ok" ? "yes" : kind === "none" ? "no" : kind;
  },
  async load(x, facts) {
    return parseLayout(layoutText(facts)).layout;
  },
  damage(facts) {
    return `${parseLayout(layoutText(facts)).message}. Rebuild the workbook with est-estimate.`;
  },
  tabs(layout) {
    return tabsFor({ kind: "ok", layout });
  },
  source(layout) {
    return `${layout.pack} pack`;
  },
  brand(layout) {
    return layout.brand ?? null;
  },
  async read(x, layout, facts) {
    return dataFromNames(layout, await x.readNames(namesFor(layout)), facts.sheetNames);
  },
  async readCursor(x, layout) {
    return { ...(await x.readActive(layout.tags)), layout };
  },
  insertKinds() {
    return INSERT_KINDS;
  },
  insertFooter() {
    return INSERT_FOOTER;
  },
  planInsert(what, ctx) {
    const p = planInsert(what, ctx.kinds, ctx.row, ctx.layout.blocks);
    return p.ok ? { sheet: ctx.sheet, at: p.at, template: p.tpl } : { refused: p.reason };
  },
  async scan(x, layout) {
    return x.scanItemSheets(layout.tags, layout.blocks.item);
  },
  readiness(layout, { dirty, scan }) {
    // No `known` set: item sheets also carry HEAD, TAKEOFF, RECAP, TOTAL and
    // ITEM rows, which the stamp's blocks do not list, so any non-blank kind
    // counts as tagged.
    const untagged = scan.sheets.flatMap((s) => untaggedRows(s.sheet, s.visible, s.kinds));
    return readiness({ layout, dirty, untagged, tooLarge: scan.tooLarge });
  },
  readbackCommand(layout, file) {
    return { command: command(layout.spec, file.name), why: NO_COMMAND, note: PASTE_NOTE };
  },
});
