import { test } from "node:test";
import assert from "node:assert/strict";
import { buildIndex, pickIndexSheet, DEFAULT_PROFILE, profileOf, readSize, findHeaderRow } from "../core/heuristic.js";

// A hand-built workbook shaped like the existing pane's: Summary sheet,
// ITEM / DESCRIPTION header, cost in E, rows that reference item sheets.
const values = [
  ["Example job", null, null, null, null],
  [null, null, null, null, null],
  ["ITEM", "DESCRIPTION", null, null, "TOTAL"],
  ["Item # 1", "Mobilization", null, null, 48500],
  ["Item # 2", "Excavation", null, null, 184300],
  ["3", "Allowance (typed)", null, null, 25000],
  [null, null, null, null, 257800],
];
const formulas = [
  ["", "", "", "", ""], ["", "", "", "", ""], ["ITEM", "DESCRIPTION", "", "", "TOTAL"],
  ["='1 Mob'!$A$2", "Mobilization", "", "", "='1 Mob'!$P$40"],
  ["='2 Exc'!$A$2", "Excavation", "", "", "='2 Exc'!$P$61"],
  ["3", "Allowance (typed)", "", "", "25000"],
  ["", "", "", "", "=SUM(E4:E6)"],
];
const sheetNames = ["Summary", "1 Mob", "2 Exc"];

test("the default profile reproduces today's parser", () => {
  const out = buildIndex({ values, formulas, sheetNames, indexSheet: "Summary" });
  assert.equal(out.indexSheet, "Summary");
  assert.deepEqual(out.rows.map((r) => [r.itemNo, r.descr, r.cost, r.sheetName, r.totalAddr]), [
    ["1", "Mobilization", 48500, "1 Mob", "$P$40"],
    ["2", "Excavation", 184300, "2 Exc", "$P$61"],
    ["3", "Allowance (typed)", 25000, "", ""],
  ]);
});

test("a workbook with nothing navigable is not an index", () => {
  const plain = formulas.map((r) => r.map((f) => (String(f).startsWith("=") ? "1" : f)));
  assert.deepEqual(buildIndex({ values, formulas: plain, sheetNames, indexSheet: "Summary" }).rows, []);
});

test("a reference to a deleted sheet is listed but not navigable", () => {
  const out = buildIndex({ values, formulas, sheetNames: ["Summary", "1 Mob"], indexSheet: "Summary" });
  assert.equal(out.rows[1].sheetName, "");
});

test("a brand profile moves the columns and labels", () => {
  const p = profileOf({ index_sheet: "Bid Items", item_header: "NO.", descr_header_prefix: "ITEM",
                        cost_col: "C" });
  const v = [["NO.", "ITEM DESCRIPTION", "COST"], ["7", "Paving", 99]];
  const f = [["NO.", "ITEM DESCRIPTION", "COST"], ["='7 Pave'!$A$1", "Paving", "='7 Pave'!$K$9"]];
  const out = buildIndex({ values: v, formulas: f, sheetNames: ["Bid Items", "7 Pave"], indexSheet: "Bid Items" }, p);
  assert.deepEqual([out.rows[0].cost, out.rows[0].totalAddr], [99, "$K$9"]);
  assert.equal(pickIndexSheet(["X", "bid items"], p), "bid items");
});

test("profileOf refuses unknown keys and bad columns", () => {
  assert.throws(() => profileOf({ colour: "red" }), /unknown heuristic key/);
  assert.throws(() => profileOf({ cost_col: "e" }), /column letter/);
});

test("profileOf rejects keys inherited from Object.prototype", () => {
  assert.throws(() => profileOf({ constructor: "x" }), /unknown heuristic key/);
  assert.throws(() => profileOf({ toString: "x" }), /unknown heuristic key/);
  assert.throws(() => profileOf({ hasOwnProperty: "x" }), /unknown heuristic key/);
});

test("profileOf requires max_scan and max_header_scan to be positive integers", () => {
  assert.throws(() => profileOf({ max_scan: 0 }), /positive integer/);
  assert.throws(() => profileOf({ max_scan: -1 }), /positive integer/);
  assert.throws(() => profileOf({ max_scan: 1.5 }), /positive integer/);
  assert.throws(() => profileOf({ max_scan: "3" }), /positive integer/);
  assert.throws(() => profileOf({ max_header_scan: 0 }), /positive integer/);
  assert.doesNotThrow(() => profileOf({ max_scan: 3, max_header_scan: 10 }));
});

test("profileOf requires non-empty strings for sheet/header/label fields", () => {
  assert.throws(() => profileOf({ index_sheet: "" }), /non-empty string/);
  assert.throws(() => profileOf({ item_header: "" }), /non-empty string/);
  assert.throws(() => profileOf({ descr_header_prefix: "" }), /non-empty string/);
  assert.throws(() => profileOf({ total_label: "" }), /non-empty string/);
  assert.throws(() => profileOf({ index_sheet: 7 }), /non-empty string/);
});

test("readSize covers the header scan, the item scan and the widest column", () => {
  assert.deepEqual(readSize(DEFAULT_PROFILE), { lastCol: "E", rows: 250 });
});

test("item and cost columns naming different sheets keep the item column's sheet and drop the cost address", () => {
  const v = [["ITEM", "DESCRIPTION", null, null, "TOTAL"], ["1", "Mob", null, null, 100]];
  const f = [["ITEM", "DESCRIPTION", "", "", "TOTAL"], ["='1 Mob'!$A$2", "Mob", "", "", "='2 Exc'!$P$61"]];
  const out = buildIndex({ values: v, formulas: f, sheetNames: ["Summary", "1 Mob", "2 Exc"], indexSheet: "Summary" });
  assert.deepEqual([out.rows[0].sheetName, out.rows[0].totalAddr], ["1 Mob", ""]);
});

test("a reference to a deleted sheet clears both sheetName and totalAddr", () => {
  const out = buildIndex({ values, formulas, sheetNames: ["Summary", "1 Mob"], indexSheet: "Summary" });
  assert.deepEqual([out.rows[1].sheetName, out.rows[1].totalAddr], ["", ""]);
});

test("blank runs: a wide gap before the first item is tolerated, a short one after it ends the list", () => {
  const v = [
    ["ITEM", "DESCRIPTION", null, null, "TOTAL"],
    [null, null, null, null, null], [null, null, null, null, null],
    [null, null, null, null, null], [null, null, null, null, null],
    ["1", "Mob", null, null, 100],
    [null, null, null, null, null], [null, null, null, null, null],
    ["2", "Excavation", null, null, 200],
  ];
  const f = [
    ["ITEM", "DESCRIPTION", "", "", "TOTAL"],
    ["", "", "", "", ""], ["", "", "", "", ""],
    ["", "", "", "", ""], ["", "", "", "", ""],
    ["='1 Mob'!$A$2", "Mob", "", "", "100"],
    ["", "", "", "", ""], ["", "", "", "", ""],
    ["2", "Excavation", "", "", "200"],
  ];
  const out = buildIndex({ values: v, formulas: f, sheetNames: ["Summary", "1 Mob"], indexSheet: "Summary" });
  assert.deepEqual(out.rows.map((r) => r.itemNo), ["1"]);
});

test("a header below row 40 (max_header_scan) is not found", () => {
  const v = Array.from({ length: 41 }, () => [null, null, null, null, null]);
  v[40] = ["ITEM", "DESCRIPTION", null, null, "TOTAL"];
  assert.equal(findHeaderRow(v, DEFAULT_PROFILE), -1);
});

test("max_scan set via profileOf scans only that many rows", () => {
  const p = profileOf({ max_scan: 3 });
  const v = [
    ["ITEM", "DESCRIPTION", null, null, "TOTAL"],
    ["1", "Item1", null, null, 10], ["2", "Item2", null, null, 20],
    ["3", "Item3", null, null, 30], ["4", "Item4", null, null, 40],
  ];
  const f = [
    ["ITEM", "DESCRIPTION", "", "", "TOTAL"],
    ["='1 Item'!$A$2", "Item1", "", "", "10"], ["2", "Item2", "", "", "20"],
    ["3", "Item3", "", "", "30"], ["4", "Item4", "", "", "40"],
  ];
  const out = buildIndex({ values: v, formulas: f, sheetNames: ["Summary", "1 Item"], indexSheet: "Summary" }, p);
  assert.deepEqual(out.rows.map((r) => r.itemNo), ["1", "2", "3"]);
});

test("an error value in the item column counts as a row, not a blank", () => {
  const v = [
    ["ITEM", "DESCRIPTION", null, null, "TOTAL"],
    ["#REF!", "Broken", null, null, 0], ["#REF!", "Broken", null, null, 0],
    ["1", "Mob", null, null, 100],
  ];
  const f = [
    ["ITEM", "DESCRIPTION", "", "", "TOTAL"],
    ["#REF!", "Broken", "", "", "0"], ["#REF!", "Broken", "", "", "0"],
    ["='1 Mob'!$A$2", "Mob", "", "", "100"],
  ];
  const out = buildIndex({ values: v, formulas: f, sheetNames: ["Summary", "1 Mob"], indexSheet: "Summary" });
  assert.deepEqual(out.rows.map((r) => r.itemNo), ["#REF!", "#REF!", "1"]);
});
