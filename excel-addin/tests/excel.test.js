import { test } from "node:test";
import assert from "node:assert/strict";
import { installFakeExcel } from "./helpers/fake-excel.js";
import { READ_MAX_ROWS, readActiveColumns, readColumns, readFacts, readNamedValues, readProperty } from "../panes/excel.js";

const BOOK = {
  props: { estimate_layout: "1", estimate_format: "fieldbook 2" },
  names: {
    "est.layout": { sheet: "_templates", addr: "$Z$1" },
    "est.index.cost": { sheet: "Cost Summary", addr: "$H$3:$H$5" },
    "est.constant": { type: "String" },
  },
  sheets: {
    "Cost Summary": { cells: { A3: "1", H3: 1000, H4: 2500, H5: "" } },
    "2 - MAIN": { cells: { A1: "Item 2", Q1: "ITEM", Q3: "TASK", Q4: "CREW", R3: "03-100", Q6: "END", B9: "stray" } },
    "_templates": { cells: { Z1: '{"layout_version":1}' } },
  },
  active: { sheet: "2 - MAIN", row: 4 },
};

test("readFacts: requested properties and named cells, the sheets and the active sheet", async () => {
  installFakeExcel(BOOK);
  const f = await readFacts({ props: ["estimate_layout", "estimate_format", "missing"],
                              cells: ["est.layout", "nope", "est.constant"] });
  assert.deepEqual(f, {
    props: { estimate_layout: "1", estimate_format: "fieldbook 2", missing: null },
    cells: { "est.layout": '{"layout_version":1}', nope: null, "est.constant": null },
    sheetNames: ["Cost Summary", "2 - MAIN", "_templates"],
    activeSheet: "2 - MAIN",
  });
});

test("readFacts with no cells to read skips the names round trip", async () => {
  const stats = installFakeExcel(BOOK);
  const f = await readFacts({ props: ["estimate_layout"], cells: [] });
  assert.deepEqual(f.cells, {});
  assert.equal(stats.syncs, 1);
});

test("readProperty: a custom property's value as text, or null", async () => {
  installFakeExcel(BOOK);
  assert.equal(await readProperty("estimate_format"), "fieldbook 2");
  assert.equal(await readProperty("nope"), null);
});

test("readNamedValues: the 2-D values behind a name, or null for a missing or non-range name", async () => {
  installFakeExcel(BOOK);
  assert.deepEqual(await readNamedValues("est.index.cost"), [[1000], [2500], [""]]);
  assert.equal(await readNamedValues("nope"), null);
  assert.equal(await readNamedValues("est.constant"), null);
});

test("readColumns: raw values from row 1 to the last used row, one array per column", async () => {
  installFakeExcel(BOOK);
  const out = await readColumns("2 - MAIN", ["Q", "R"]);
  assert.equal(out.last, 9);
  assert.equal(out.truncated, false);
  assert.deepEqual(out.columns.Q, ["ITEM", "", "TASK", "CREW", "", "END", "", "", ""]);
  assert.deepEqual(out.columns.R, ["", "", "03-100", "", "", "", "", "", ""]);
  assert.equal(await readColumns("No such sheet", ["Q"]), null);
});

test("readActiveColumns: the active sheet and row, with its columns", async () => {
  installFakeExcel(BOOK);
  const out = await readActiveColumns(["Q"]);
  assert.deepEqual([out.sheet, out.row, out.last], ["2 - MAIN", 4, 9]);
  assert.equal(out.columns.Q[3], "CREW");
});

test("a custom property that is not text (a number, a date, a yes/no) still reads as text", async () => {
  installFakeExcel({ ...BOOK, props: { count: 3, flag: true, when: new Date(Date.UTC(2026, 0, 2)) } });
  const f = await readFacts({ props: ["count", "flag", "when"], cells: [] });
  assert.deepEqual([f.props.count, f.props.flag], ["3", "true"]);
  assert.equal(typeof f.props.when, "string");
  assert.equal(await readProperty("count"), "3");
});

test("readColumns and readActiveColumns stop at READ_MAX_ROWS and say so", async () => {
  const far = READ_MAX_ROWS + 5;
  installFakeExcel({ ...BOOK, sheets: { Big: { cells: { A1: "first", [`A${far}`]: "past the cap" } } },
                     active: { sheet: "Big", row: 2 } });
  const out = await readColumns("Big", ["A"]);
  assert.deepEqual([out.last, out.truncated, out.columns.A.length, out.columns.A[0]], [READ_MAX_ROWS, true, READ_MAX_ROWS, "first"]);
  const act = await readActiveColumns(["A"]);
  assert.deepEqual([act.sheet, act.row, act.last, act.truncated], ["Big", 2, READ_MAX_ROWS, true]);
});
