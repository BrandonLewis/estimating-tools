import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { findBlock } from "../core/blocks.js";

// The real column-Q kind sequence of the fieldbook example's "2 - 8IN MAIN"
// sheet, generated from the fieldbook pack's own builder (see
// excel-addin/tests/fixtures/fieldbook-kinds.json for how).
const FIELDBOOK_BLOCKS = { item: "ITEM", head: "TASK", body: ["NOTE", "CREW", "LINE"], end: "END", sub: "SUBTOTAL", code_col: "A" };
const fieldbookKinds = JSON.parse(readFileSync(new URL("./fixtures/fieldbook-kinds.json", import.meta.url), "utf8"));

const BLOCKS = { item: "ITEM", head: "TASK", body: ["NOTE", "CREW", "LINE"], end: "END", sub: "SUBTOTAL", code_col: "A" };
//            1       2       3       4       5      6      7          8       9       10     11     12
const kinds = ["ITEM", "HEAD", "TASK", "CREW", "LINE", "END", "SUBTOTAL", "TASK", "CREW", "END", "SUBTOTAL", "RECAP"];

test("a row inside a block finds its head, end and subtotal", () => {
  for (const row of [3, 4, 5, 6, 7]) assert.deepEqual(findBlock(kinds, row, BLOCKS), { head: 3, end: 6, sub: 7 }, `row ${row}`);
  assert.deepEqual(findBlock(kinds, 9, BLOCKS), { head: 8, end: 10, sub: 11 });
});

test("rows outside every block find none", () => {
  for (const row of [1, 2, 12, 99]) assert.equal(findBlock(kinds, row, BLOCKS), null, `row ${row}`);
});

test("an untagged row inside a block still belongs to it", () => {
  const k = ["TASK", "CREW", "", "END", "SUBTOTAL"];
  assert.deepEqual(findBlock(k, 3, BLOCKS), { head: 1, end: 4, sub: 5 });
});

test("a block with no END is not a block", () => {
  assert.equal(findBlock(["TASK", "CREW", "SUBTOTAL"], 2, BLOCKS), null);
});

test("real fieldbook sequence: every row before the first TASK finds no block", () => {
  const firstTask = fieldbookKinds.indexOf("TASK") + 1;         // 1-based row
  for (let row = 1; row < firstTask; row += 1) {
    assert.equal(findBlock(fieldbookKinds, row, FIELDBOOK_BLOCKS), null, `row ${row}`);
  }
});

test("real fieldbook sequence: TASK, NOTE, CREW, END and SUBTOTAL all resolve the same block", () => {
  for (const row of [18, 19, 20, 28, 29]) {
    assert.deepEqual(findBlock(fieldbookKinds, row, FIELDBOOK_BLOCKS), { head: 18, end: 28, sub: 29 }, `row ${row}`);
  }
});

test("real fieldbook sequence: a row past the end of the sheet finds no block", () => {
  assert.equal(findBlock(fieldbookKinds, fieldbookKinds.length + 1, FIELDBOOK_BLOCKS), null);
});
