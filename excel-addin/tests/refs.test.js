import { test } from "node:test";
import assert from "node:assert/strict";
import { tryParseRef, itemLabel, cellNumber, cellText, isErrorValue, colIndex } from "../core/refs.js";

test("tryParseRef reads a plain cross-sheet single-cell reference", () => {
  assert.deepEqual(tryParseRef("='SP soldier piles'!$G$107"), { sheet: "SP soldier piles", addr: "$G$107" });
  assert.deepEqual(tryParseRef("=Rates!B4"), { sheet: "Rates", addr: "B4" });
  assert.deepEqual(tryParseRef("='Bob''s sheet'!$A$1"), { sheet: "Bob's sheet", addr: "$A$1" });
});

test("tryParseRef refuses expressions, ranges and external references", () => {
  for (const f of ["=A1", "=Rates!A1:B2", "=SUM(Rates!A1)", "='[Book.xlsx]S'!A1", "=Rates!A1+1",
                   "", null, "Rates!A1", "=a b!A1"]) {
    assert.equal(tryParseRef(f), null, String(f));
  }
});

test("itemLabel trims Item # boilerplate conservatively", () => {
  assert.equal(itemLabel("Item # 66"), "66");
  assert.equal(itemLabel("#12"), "12");
  assert.equal(itemLabel("Itemized bid"), "Itemized bid");
  assert.equal(itemLabel("Item #"), "Item #");
  assert.equal(itemLabel("#REF!"), "#REF!");
});

test("cell helpers", () => {
  assert.equal(cellNumber(3.5), 3.5);
  assert.equal(cellNumber("3.5"), null);
  assert.equal(cellText(null), "");
  assert.ok(isErrorValue("#N/A"));
  assert.equal(colIndex("A"), 0);
  assert.equal(colIndex("E"), 4);
  assert.equal(colIndex("AA"), 26);
});

test("tryParseRef allows ! inside a quoted sheet name, which Excel permits", () => {
  assert.deepEqual(tryParseRef("='Cost Summary!'!$H$5"), { sheet: "Cost Summary!", addr: "$H$5" });
  assert.deepEqual(tryParseRef("='A!B'!C3"), { sheet: "A!B", addr: "C3" });
});

test("tryParseRef still refuses an unquoted ! as an expression", () => {
  assert.equal(tryParseRef("=A!B!C3"), null);
  assert.equal(tryParseRef("='A'!B!C3"), null);
});
