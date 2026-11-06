import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { installFakeDom } from "./helpers/fake-dom.js";
import { fieldbook } from "../core/packs/fieldbook.js";
import { renderItems } from "../panes/items.js";
import { renderChecks } from "../panes/checks.js";
import { renderInsert } from "../panes/insert.js";
import { renderReadback } from "../panes/readback.js";

const PANES = new URL("../panes/", import.meta.url);
const text = (e) => e.textContent;
const ITEMS = [
  { key: "item:1", no: "1", label: "Mob", cost: 1000, total: false, jump: { sheet: "1 - MOB" },
    focus: { sheet: "1 - MOB", addr: "$K$30" }, status: { fails: 0 }, children: [] },
  { key: "item:2", no: "2", label: "Main", cost: 2500, total: false, jump: { sheet: "2 - MAIN" },
    focus: { sheet: "2 - MAIN", addr: "$K$88" }, status: { fails: 2 }, children: [] },
  { key: "item:3", no: "3", label: "Typed", cost: 25, total: false, jump: null, focus: null, status: null, children: [] },
  { key: "total", no: "DIRECT", label: "", cost: 3525, total: true, jump: { sheet: "Cost Summary" },
    focus: { sheet: "Cost Summary", addr: "$H$9" }, status: null, children: [] },
];

function recorder() {
  const jumps = [];
  return { jumps, x: { jump: (j) => jumps.push(j), current: () => true } };
}

test("every named import in panes/*.js resolves to an export of its module", async () => {
  for (const file of readdirSync(PANES).filter((f) => f.endsWith(".js"))) {
    const src = readFileSync(new URL(file, PANES), "utf8");
    for (const [, names, from] of src.matchAll(/import\s*\{([^}]+)\}\s*from\s*"([^"]+)"/g)) {
      const mod = await import(new URL(from, new URL(file, PANES)).href);
      for (const name of names.split(",").map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean)) {
        assert.ok(name in mod, `${file} imports ${name} from ${from}, which does not export it`);
      }
    }
  }
});

test("main.js calls only functions panes/excel.js exports", async () => {
  const X = await import(new URL("excel.js", PANES).href);
  const src = readFileSync(new URL("main.js", PANES), "utf8");
  for (const [, name] of src.matchAll(/\bX\.(\w+)/g)) assert.equal(typeof X[name], "function", `X.${name}`);
});

test("Items: fieldbook rows render as before -- number, description, status, cost, links and the total", () => {
  const root = installFakeDom();
  const { jumps, x } = recorder();
  renderItems(root, { data: { items: ITEMS }, activeSheet: "2 - main" }, x);
  const trs = root.findAll((e) => e.tagName === "TR").slice(1);           // skip the header row
  assert.deepEqual(trs.map((tr) => tr.getAttribute("aria-label")), [
    "Item 1, Mob, all checks pass", "Item 2, Main, 2 failing checks", "Item 3, Typed, not a link", "DIRECT total, $3,525"]);
  assert.deepEqual(trs.map((tr) => tr.className), [" go ", " go sel", " dead ", "total go "]);
  assert.deepEqual(trs.map((tr) => tr.getAttribute("data-focus-key")), ["item:1", "item:2", null, "total"]);
  assert.deepEqual(trs.map(text), ["1Mob ✓$1,000", "2Main ✗ 2$2,500", "3Typed$25", "DIRECT$3,525"]);
  trs[0].fire("click");
  trs[0].fire("dblclick");
  trs[1].fire("keydown", { key: "Enter" });
  assert.deepEqual(jumps, [{ sheet: "1 - MOB" }, { sheet: "1 - MOB", addr: "$K$30" }, { sheet: "2 - MAIN", addr: "$K$88" }]);
  assert.deepEqual(trs[2].listeners, {});
});

test("Items: a hand-built workbook's rows show no ✓/✗", () => {
  const root = installFakeDom();
  renderItems(root, { data: { items: ITEMS.map((r) => ({ ...r, status: null })) }, activeSheet: "" }, recorder().x);
  const trs = root.findAll((e) => e.tagName === "TR").slice(1);
  assert.equal(trs[0].getAttribute("aria-label"), "Item 1, Mob");
  assert.equal(text(trs[0]), "1Mob$1,000");
});

test("Items: a tree indents children, shows a note, and never highlights a row-level jump by sheet", () => {
  const root = installFakeDom();
  const tree = [{ key: "i1", no: "1", label: "Item", cost: 10, jump: { sheet: "Cost Report", row: 6, cols: "A:R" },
                  status: { fails: 0 }, children: [
                    { key: "a9", no: "", label: "New activity", cost: 4, note: "new — not in the item total until applied",
                      jump: { sheet: "Cost Report", row: 9, cols: "A:R" }, children: [] }] }];
  const { jumps, x } = recorder();
  renderItems(root, { data: { items: tree }, activeSheet: "Cost Report" }, x);
  const trs = root.findAll((e) => e.tagName === "TR").slice(1);
  assert.deepEqual(trs.map((tr) => tr.className), [" go ", " go "]);
  assert.equal(trs[1].getAttribute("aria-label"), "New activity, new — not in the item total until applied");
  const descr = trs[1].findAll((e) => e.tagName === "TD")[1];
  assert.equal(descr.getAttribute("style"), "padding-left:20px");
  assert.equal(trs[0].findAll((e) => e.tagName === "TD")[1].getAttribute("style"), null);
  trs[1].fire("dblclick");
  assert.deepEqual(jumps, [{ sheet: "Cost Report", row: 9, cols: "A:R" }]);
});

test("Checks: counts, failures first with their check number, passes after, and a check with no item cannot jump", () => {
  const root = installFakeDom();
  const { jumps, x } = recorder();
  const checks = [
    { status: "fail", item: "Item 2", rule: "Takeoff = qty", ref: "check 1", jump: { sheet: "2 - MAIN", addr: "$K$88" } },
    { status: "fail", item: "All items", rule: "Unbalanced", ref: "check 4", jump: null },
    { status: "pass", item: "Item 1", rule: "Takeoff = qty", ref: "check 1", jump: { sheet: "1 - MOB", addr: "$K$30" } },
  ];
  renderChecks(root, { data: { checks } }, x);
  const top = root.children.map(text);
  assert.deepEqual(top, ["1 ✓  2 ✗", "Failing — click to open the item", "✗Item 2 · check 1Takeoff = qty",
                         "✗All items · check 4Unbalanced", "Passing", "✓ Item 1 · Takeoff = qty"]);
  root.children[2].fire("click");
  assert.deepEqual(jumps, [{ sheet: "2 - MAIN", addr: "$K$88" }]);
  assert.equal(root.children[3].disabled, true);
  assert.deepEqual(root.children[3].listeners, {});
});

test("Checks: info rows are listed apart and not counted", () => {
  const root = installFakeDom();
  renderChecks(root, { data: { checks: [{ status: "info", item: "Item 1", rule: "Export total", text: "12,000", jump: null }] } },
               recorder().x);
  assert.deepEqual(root.children.map(text), ["0 ✓  0 ✗", "Passing", "Export only", "Item 1 · Export total · 12,000"]);
});

const LAYOUT = {
  pack: "fieldbook", layout_version: 1, tables: ["checks", "index"], tags: { kind: "Q", code_chain: "R" },
  blocks: { item: "ITEM", head: "TASK", body: ["NOTE", "CREW", "LINE"], end: "END", sub: "SUBTOTAL", code_col: "A" },
  templates: true, spec: "job.estimate.yaml",
};

/** A fieldbook pane state over a fake x whose cursor sits on row `row` of the fixture's sheet. */
function insertSetup(row, extra = {}) {
  const kinds = JSON.parse(readFileSync(new URL("./fixtures/fieldbook-kinds.json", import.meta.url), "utf8"));
  const inserted = [];
  const x = { current: () => true,
              readActive: async () => ({ sheet: "2 - 8IN MAIN", row, kinds, chain: [] }),
              insertTemplate: async (sheet, at, tpl) => { inserted.push([sheet, at, tpl]); return { first: at, last: at }; } };
  const app = { state: { kind: "ok", adapter: { ...fieldbook, ...extra }, layout: LAYOUT },
                insertNote: null, insertConfirm: null, inserting: false, insertButtons: [] };
  return { x, app, inserted };
}

test("Insert: today's buttons and footer; a click inserts the adapter's plan and says which rows", async () => {
  const root = installFakeDom();
  const { x, app, inserted } = insertSetup(18);
  await renderInsert(root, app, x);
  assert.equal(text(root.children[0]), "Cursor2 - 8IN MAIN · row 18");
  assert.deepEqual(app.insertButtons.map((b) => b.findAll((e) => e.tagName === "STRONG")[0].textContent),
                   ["New task", "New crew row", "New line"]);
  assert.match(text(root.children.at(-1)), /^Rows are copied from the hidden _templates sheet/);
  await app.insertButtons[1].fire("click");
  assert.deepEqual(inserted, [["2 - 8IN MAIN", 20, "est.tpl.crew"]]);
  assert.deepEqual(app.insertNote, { ok: true, warn: false, text: "Inserted rows 20–20 from _templates. Fill in the blank cells." });
  assert.equal(app.inserting, false);
});

test("Insert: a refusal is shown and nothing is inserted", async () => {
  const root = installFakeDom();
  const { x, app, inserted } = insertSetup(1);
  await renderInsert(root, app, x);
  await app.insertButtons[1].fire("click");
  assert.deepEqual(inserted, []);
  assert.equal(app.insertNote.ok, false);
  assert.match(app.insertNote.text, /task block/);
});

test("Insert: a plan that asks first inserts only on the second click, with its own fill note", async () => {
  const root = installFakeDom();
  const ask = (what, ctx) => ({ ...fieldbook.planInsert(what, ctx), confirm: "This edits a library crew.", fill: "Fill A and C." });
  const { x, app, inserted } = insertSetup(18, { planInsert: ask });
  await renderInsert(root, app, x);
  await app.insertButtons[1].fire("click");
  assert.deepEqual(inserted, []);
  assert.deepEqual(app.insertNote, { ok: false, warn: true, text: "This edits a library crew. Click New crew row again to insert." });
  await app.insertButtons[1].fire("click");
  assert.deepEqual(inserted, [["2 - 8IN MAIN", 20, "est.tpl.crew"]]);
  assert.equal(app.insertNote.text, "Inserted rows 20–20 from _templates. Fill A and C.");
});

test("Insert: no active cell shows the adapter's message", async () => {
  const root = installFakeDom();
  const { app } = insertSetup(18);
  await renderInsert(root, app, { current: () => true, readActive: async () => { throw new Error("chart"); } });
  assert.equal(text(root), "Select a cell on an item sheet.");
});

test("Read back: the adapter's readiness rows, its command, and Copy held back until ready", async () => {
  const root = installFakeDom();
  const scan = { sheets: [{ sheet: "2 - MAIN", kinds: ["ITEM", ""], visible: [[], ["stray"]] }], tooLarge: [] };
  const app = { state: { kind: "ok", adapter: fieldbook, layout: LAYOUT }, scan: null };
  const x = { current: () => true, readDirty: async () => false, scanItemSheets: async () => scan,
              documentUrl: () => "C:\\Bids\\Job.xlsx", refresh() {} };
  await renderReadback(root, app, x);
  const all = text(root);
  assert.match(all, /Rows outside the tagged blocks2 - MAIN row 2/);
  assert.match(all, /est-estimate read-back "job\.estimate\.yaml" "Job\.xlsx" --write/);
  assert.match(all, /Paste it into a terminal in the workbook's folder\. An add-in can't run it for you\.$/);
  const copy = root.findAll((e) => e.tagName === "BUTTON" && e.textContent === "Copy command")[0];
  assert.equal(copy.disabled, true);
});

test("Read back: a readiness row with a jump gets a Go button", async () => {
  const root = installFakeDom();
  const { jumps, x: base } = recorder();
  const adapter = { ...fieldbook, readiness: () => [{ ok: false, text: "Stray row", sub: "Cost Report row 31",
                                                      jump: { sheet: "Cost Report", row: 31, cols: "A:R" } }] };
  const x = { ...base, readDirty: async () => false, scanItemSheets: async () => ({ sheets: [], tooLarge: [] }),
              documentUrl: () => "https://contoso.sharepoint.com/Job.xlsx", refresh() {} };
  await renderReadback(root, { state: { kind: "ok", adapter, layout: LAYOUT }, scan: null }, x);
  root.findAll((e) => e.tagName === "BUTTON" && e.textContent === "Go")[0].fire("click");
  assert.deepEqual(jumps, [{ sheet: "Cost Report", row: 31, cols: "A:R" }]);
  assert.match(text(root), /sync it to this computer first\.$/);
});
