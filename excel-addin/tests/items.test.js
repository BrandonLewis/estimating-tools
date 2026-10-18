import { test } from "node:test";
import assert from "node:assert/strict";
import { itemsFromTable, withTotal, costText, totalOf } from "../core/items.js";

const col = (...xs) => xs.map((x) => [x]);

test("stamped rows come from the named columns and link through the link column", () => {
  const rows = itemsFromTable({
    itemNo: col("1", "2", ""), descr: col("Mob", "Main", ""), cost: col(1000, 2500.5, null),
    link: col("='1 - MOB'!$K$30", "='2 - MAIN'!$K$88", ""),
    sheetNames: ["Cost Summary", "1 - MOB", "2 - MAIN"],
  });
  assert.deepEqual(rows.map((r) => [r.itemNo, r.cost, r.sheetName, r.totalAddr]), [
    ["1", 1000, "1 - MOB", "$K$30"], ["2", 2500.5, "2 - MAIN", "$K$88"],
  ]);
});

test("the total row carries the workbook's own total when there is one", () => {
  const rows = [{ itemNo: "1", cost: 1 }, { itemNo: "2", cost: 2 }];
  assert.equal(totalOf(rows), 3);
  const all = withTotal(rows, { total: 3.01, label: "DIRECT", sheet: "Cost Summary", addr: "$H$9" });
  assert.deepEqual(all.at(-1), { itemNo: "DIRECT", descr: "", cost: 3.01, sheetName: "Cost Summary",
                                 totalAddr: "$H$9", isTotal: true });
  assert.equal(withTotal(rows, { label: "DIRECT" }).at(-1).cost, 3);
  assert.deepEqual(withTotal([], { label: "DIRECT" }), []);
});

test("costText", () => {
  assert.equal(costText(1125680), "$1,125,680");
  assert.equal(costText(null), "—");
});

test("a numeric item number becomes a string", () => {
  const rows = itemsFromTable({
    itemNo: col(1), descr: col("Mob"), cost: col(1000), link: col(""), sheetNames: ["Cost Summary"],
  });
  assert.deepEqual(rows.map((r) => r.itemNo), ["1"]);
});
