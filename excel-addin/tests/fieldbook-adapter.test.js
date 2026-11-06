import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { assertAdapter, pick } from "../core/adapter.js";
import { fieldbook, INSERT_KINDS, KNOWN_LAYOUT_VERSION, layoutText, namesFor, parseLayout, planInsert, readiness, tabsFor }
  from "../core/packs/fieldbook.js";

// The real column-Q kind sequence of the fieldbook example's "2 - 8IN MAIN" sheet.
const SHEET = "2 - 8IN MAIN";
const kinds = JSON.parse(readFileSync(new URL("./fixtures/fieldbook-kinds.json", import.meta.url), "utf8"));
const LAYOUT = {
  pack: "fieldbook", pack_version: "1", layout_version: 1, tables: ["checks", "codes", "index"],
  tags: { kind: "Q", code_chain: "R" },
  blocks: { item: "ITEM", head: "TASK", body: ["NOTE", "CREW", "LINE"], end: "END", sub: "SUBTOTAL", code_col: "A" },
  templates: true, spec: "job.estimate.yaml",
};
const facts = (marker, cell) => ({ props: { estimate_layout: marker }, cells: { "est.layout": cell },
                                   sheetNames: ["Cost Summary", "1 - MOB", SHEET], activeSheet: "Cost Summary" });
const col = (...xs) => xs.map((v) => [v]);

test("the fieldbook adapter implements the whole interface", () => {
  assert.equal(assertAdapter(fieldbook), fieldbook);
  assert.deepEqual([fieldbook.id, fieldbook.props, fieldbook.cells], ["fieldbook", ["estimate_layout"], ["est.layout"]]);
});

test("detect: no marker is no stamp, whatever the cell holds", () => {
  assert.equal(fieldbook.detect(facts(null, JSON.stringify(LAYOUT))), "no");
  assert.equal(pick([fieldbook], facts(null, null)), null);
});

test("detect: a marker with a good layout is yes, a newer one newer", () => {
  assert.equal(fieldbook.detect(facts("1", JSON.stringify(LAYOUT))), "yes");
  assert.equal(fieldbook.detect(facts("1", JSON.stringify({ ...LAYOUT, layout_version: KNOWN_LAYOUT_VERSION + 1 }))), "newer");
});

test("detect: a marker with a damaged, missing or empty cell is bad, as the pane always said", () => {
  assert.equal(fieldbook.detect(facts("1", "{not json")), "bad");
  assert.equal(fieldbook.damage(facts("1", "{not json")), "estimate_layout is not JSON. Rebuild the workbook with est-estimate.");
  assert.equal(fieldbook.detect(facts("1", null)), "bad");                 // est.layout name missing -> "{}"
  assert.equal(fieldbook.damage(facts("1", null)), "estimate_layout has no layout_version. Rebuild the workbook with est-estimate.");
  assert.equal(fieldbook.detect(facts("1", JSON.stringify({ ...LAYOUT, tags: { kind: "Q" } }))), "bad");
});

test("detect: a marker with an empty-string cell is no stamp (the heuristic runs), as before", () => {
  assert.equal(fieldbook.detect(facts("1", "")), "no");
});

test("layoutText parity with the old readWorkbook: an empty cell is no stamp, only a missing cell is damaged", () => {
  // The old read was `cell ? String(cell.values[0][0] ?? "{}") : "{}"`: an empty cell reads "" (none),
  // a missing name reads "{}" (bad).
  assert.equal(layoutText(facts("1", "")), "");
  assert.equal(parseLayout(layoutText(facts("1", ""))).kind, "none");
  assert.equal(layoutText(facts("1", null)), "{}");
  assert.equal(parseLayout(layoutText(facts("1", null))).kind, "bad");
  assert.equal(layoutText(facts(null, "")), null);
});

test("load returns the parsed layout; tabs, source and brand come from it", async () => {
  const layout = await fieldbook.load({}, facts("1", JSON.stringify({ ...LAYOUT, brand: { name: "Example Estimating" } })));
  assert.equal(layout.pack, "fieldbook");
  assert.deepEqual(fieldbook.tabs(layout), tabsFor({ kind: "ok", layout }));
  assert.deepEqual(fieldbook.tabs(LAYOUT), ["items", "checks", "codes", "insert", "readback"]);
  assert.equal(fieldbook.source(LAYOUT), "fieldbook pack");
  assert.deepEqual(fieldbook.brand(layout), { name: "Example Estimating" });
  assert.equal(fieldbook.brand(LAYOUT), null);
});

// ---- Items and Checks, from what readNames returns ----

const NAMES = {
  "est.index.item_no": { values: col("1", "2", "3", "") },
  "est.index.descr": { values: col("Mob", "8in main", "Allowance", "") },
  "est.index.cost": { values: col(1000, 2500.5, 25, null) },
  "est.index.link": { formulas: col("='1 - MOB'!$K$30", `='${SHEET}'!$K$88`, "25", "") },
  "est.direct_total": { values: [[3525.5]], address: "'Cost Summary'!$H$9" },
  "est.checks.rule_no": { values: col(1, 1, 9, 4) },
  "est.checks.rule": { values: col("Takeoff = qty", "Takeoff = qty", "Code on list", "Unbalanced") },
  "est.checks.item": { values: col("1", "2", "2", "all") },
  "est.checks.status": { values: col("✓", "✗", "✗", "✗") },
  "est.codes.code": { values: col("03-100", "") },
  "est.codes.descr": { values: col("Forming", "") },
  "est.codes.listed": { values: col(1, null) },
};
const fakeX = { readNames: async (names) => Object.fromEntries(names.map((n) => [n, NAMES[n] ?? null])) };

test("read asks for the names the layout's tables back, in one call", async () => {
  const asked = [];
  await fieldbook.read({ readNames: async (n) => { asked.push(n); return {}; } }, LAYOUT, facts("1", ""));
  assert.equal(asked.length, 1);
  assert.deepEqual(asked[0], namesFor(LAYOUT));
  assert.deepEqual(namesFor({ ...LAYOUT, tables: ["index"] }),
                   ["est.index.item_no", "est.index.descr", "est.index.cost", "est.index.link", "est.direct_total"]);
});

test("Items is one level deep: linked items, a typed one, and the DIRECT total", async () => {
  const { items } = await fieldbook.read(fakeX, LAYOUT, facts("1", ""));
  assert.deepEqual(items.map((r) => [r.key, r.no, r.label, r.cost, r.status, r.jump, r.focus, r.children.length]), [
    ["item:1", "1", "Mob", 1000, { fails: 0 }, { sheet: "1 - MOB" }, { sheet: "1 - MOB", addr: "$K$30" }, 0],
    ["item:2", "2", "8in main", 2500.5, { fails: 2 }, { sheet: SHEET }, { sheet: SHEET, addr: "$K$88" }, 0],
    ["item:3", "3", "Allowance", 25, { fails: 0 }, null, null, 0],
    ["total", "DIRECT", "", 3525.5, null, { sheet: "Cost Summary" }, { sheet: "Cost Summary", addr: "$H$9" }, 0],
  ]);
});

test("Checks: each row names its item and jumps to that item's total; the whole-workbook check cannot jump", async () => {
  const { checks } = await fieldbook.read(fakeX, LAYOUT, facts("1", ""));
  assert.deepEqual(checks, [
    { status: "fail", item: "Item 2", rule: "Takeoff = qty", ref: "check 1", jump: { sheet: SHEET, addr: "$K$88" } },
    { status: "fail", item: "Item 2", rule: "Code on list", ref: "check 9", jump: { sheet: SHEET, addr: "$K$88" } },
    { status: "fail", item: "All items", rule: "Unbalanced", ref: "check 4", jump: null },
    { status: "pass", item: "Item 1", rule: "Takeoff = qty", ref: "check 1", jump: { sheet: "1 - MOB", addr: "$K$30" } },
  ]);
});

test("a layout without checks or codes reads neither, and every item shows ✓", async () => {
  const layout = { ...LAYOUT, tables: ["index"] };
  const data = await fieldbook.read(fakeX, layout, facts("1", ""));
  assert.equal(data.checks, null);
  assert.deepEqual(data.codes, []);
  assert.ok(data.items.filter((r) => !r.total).every((r) => r.status.fails === 0));
});

test("codes come through for the Codes tab", async () => {
  const { codes } = await fieldbook.read(fakeX, LAYOUT, facts("1", ""));
  assert.deepEqual(codes, [{ code: "03-100", descr: "Forming", listed: true }]);
});

// ---- Insert ----

test("Insert offers today's three buttons", () => {
  assert.deepEqual(fieldbook.insertKinds(LAYOUT).map((k) => [k.what, k.label]),
                   [["task", "New task"], ["crew", "New crew row"], ["line", "New line"]]);
  assert.equal(fieldbook.insertKinds(LAYOUT), INSERT_KINDS);
  assert.match(fieldbook.insertFooter(LAYOUT), /never inserted below a task's END row/);
});

test("readCursor reads the kind and code-chain columns through x.readActive and carries the layout", async () => {
  const seen = [];
  const ctx = await fieldbook.readCursor({ readActive: async (tags) => { seen.push(tags); return { sheet: SHEET, row: 20, kinds, chain: [] }; } }, LAYOUT);
  assert.deepEqual(seen, [{ kind: "Q", code_chain: "R" }]);
  assert.deepEqual([ctx.sheet, ctx.row, ctx.layout], [SHEET, 20, LAYOUT]);
});

test("planInsert parity: every row of the real sheet, every kind, matches the moved core/insert.js", () => {
  for (const what of ["task", "crew", "line"]) {
    for (let row = 1; row <= kinds.length + 1; row += 1) {
      const old = planInsert(what, kinds, row, LAYOUT.blocks);
      const got = fieldbook.planInsert(what, { sheet: SHEET, row, kinds, layout: LAYOUT });
      const want = old.ok ? { sheet: SHEET, at: old.at, template: old.tpl } : { refused: old.reason };
      assert.deepEqual(got, want, `${what} at row ${row}`);
    }
  }
});

test("planInsert on the real sheet: rows land after the NOTE, a task below the subtotal, END refuses rows", () => {
  const plan = (what, row) => fieldbook.planInsert(what, { sheet: SHEET, row, kinds, layout: LAYOUT });
  assert.deepEqual(plan("crew", 18), { sheet: SHEET, at: 20, template: "est.tpl.crew" });
  assert.deepEqual(plan("task", 29), { sheet: SHEET, at: 30, template: "est.tpl.task" });
  assert.match(plan("crew", 29).refused, /END/);
  assert.match(plan("line", 1).refused, /task block/);
});

// ---- Read back ----

const SCAN = { sheets: [{ sheet: SHEET, kinds: ["ITEM", "", "TASK"], visible: [[], ["stray"], []] }], tooLarge: [] };

test("scan is x.scanItemSheets over the layout's kind column and item kind", async () => {
  const seen = [];
  const out = await fieldbook.scan({ scanItemSheets: async (tags, item) => { seen.push([tags, item]); return SCAN; } }, LAYOUT);
  assert.equal(out, SCAN);
  assert.deepEqual(seen, [[{ kind: "Q", code_chain: "R" }, "ITEM"]]);
});

test("readiness is today's list, with the scan's untagged rows and too-large sheets", () => {
  const rows = fieldbook.readiness(LAYOUT, { dirty: false, scan: { ...SCAN, tooLarge: ["Big"] } });
  assert.deepEqual(rows, readiness({ layout: LAYOUT, dirty: false, untagged: [`${SHEET} row 2`], tooLarge: ["Big"] }));
  assert.deepEqual(rows.map((r) => r.ok), [true, true, true, false, false]);
  assert.ok(fieldbook.readiness(LAYOUT, { dirty: false, scan: { sheets: [], tooLarge: [] } }).every((r) => r.ok));
});

test("readbackCommand: today's command, or why there is none, and the paste note", () => {
  assert.deepEqual(fieldbook.readbackCommand(LAYOUT, { name: "Job.xlsx", cloud: false }), {
    command: 'est-estimate read-back "job.estimate.yaml" "Job.xlsx" --write',
    why: "This workbook's stamp names no spec file, or the spec or workbook name has characters that are not safe to paste into a terminal, or the workbook has not been saved yet. Run read-back by hand.",
    note: "Paste it into a terminal in the workbook's folder. An add-in can't run it for you.",
  });
  assert.equal(fieldbook.readbackCommand({ ...LAYOUT, spec: undefined }, { name: "Job.xlsx", cloud: false }).command, null);
  assert.equal(fieldbook.readbackCommand(LAYOUT, { name: "", cloud: false }).command, null);
});
