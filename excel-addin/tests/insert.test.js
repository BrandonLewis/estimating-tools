import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { planInsert } from "../core/insert.js";

const BLOCKS = { item: "ITEM", head: "TASK", body: ["NOTE", "CREW", "LINE"], end: "END", sub: "SUBTOTAL", code_col: "A" };
const kinds = ["ITEM", "TASK", "CREW", "LINE", "END", "SUBTOTAL", "RECAP"];

// The real column-Q kind sequence of the fieldbook example's "2 - 8IN MAIN"
// sheet; see excel-addin/tests/fixtures/fieldbook-kinds.json for how it was
// generated. Its first task block (rows 18-29) has a NOTE row (19) right
// under the TASK head (18), unlike the synthetic fixture above.
const FIELDBOOK_BLOCKS = BLOCKS;
const fieldbookKinds = JSON.parse(readFileSync(new URL("./fixtures/fieldbook-kinds.json", import.meta.url), "utf8"));

test("a crew row or line goes at the cursor, never above the task head", () => {
  assert.deepEqual(planInsert("crew", kinds, 4, BLOCKS), { ok: true, at: 4, tpl: "est.tpl.crew", block: { head: 2, end: 5, sub: 6 } });
  assert.equal(planInsert("line", kinds, 2, BLOCKS).at, 3);
  assert.equal(planInsert("line", kinds, 5, BLOCKS).at, 5);        // above END stays inside every SUM
});

test("below END is refused for rows", () => {
  const out = planInsert("crew", kinds, 6, BLOCKS);
  assert.equal(out.ok, false);
  assert.match(out.reason, /END/);
});

test("a new task goes below the current block's subtotal", () => {
  assert.equal(planInsert("task", kinds, 6, BLOCKS).at, 7);
  assert.equal(planInsert("task", kinds, 3, BLOCKS).tpl, "est.tpl.task");
});

test("outside a block nothing is inserted", () => {
  const out = planInsert("task", kinds, 7, BLOCKS);
  assert.equal(out.ok, false);
  assert.match(out.reason, /task block/);
});

test("a crew or line row at the TASK head lands after the NOTE, not above it", () => {
  assert.equal(planInsert("crew", fieldbookKinds, 18, FIELDBOOK_BLOCKS).at, 20);
  assert.equal(planInsert("line", fieldbookKinds, 18, FIELDBOOK_BLOCKS).at, 20);
});

test("real fieldbook sequence: cursor on NOTE still lands after it", () => {
  assert.equal(planInsert("crew", fieldbookKinds, 19, FIELDBOOK_BLOCKS).at, 20);
});

test("real fieldbook sequence: cursor already past the NOTE goes at the cursor", () => {
  assert.equal(planInsert("crew", fieldbookKinds, 20, FIELDBOOK_BLOCKS).at, 20);
});

test("real fieldbook sequence: cursor at END inserts at END, pushing it down", () => {
  assert.equal(planInsert("crew", fieldbookKinds, 28, FIELDBOOK_BLOCKS).at, 28);
});

test("real fieldbook sequence: at SUBTOTAL a task is allowed, a row is refused", () => {
  assert.equal(planInsert("task", fieldbookKinds, 29, FIELDBOOK_BLOCKS).at, 30);
  assert.equal(planInsert("crew", fieldbookKinds, 29, FIELDBOOK_BLOCKS).ok, false);
});

test("real fieldbook sequence: every row before the first TASK is refused", () => {
  const firstTask = fieldbookKinds.indexOf("TASK") + 1;
  for (let row = 1; row < firstTask; row += 1) {
    assert.equal(planInsert("crew", fieldbookKinds, row, FIELDBOOK_BLOCKS).ok, false, `row ${row}`);
  }
});

test("real fieldbook sequence: a trailing row past the sheet is refused", () => {
  assert.equal(planInsert("task", fieldbookKinds, fieldbookKinds.length + 1, FIELDBOOK_BLOCKS).ok, false);
});
