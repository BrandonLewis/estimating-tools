import { test } from "node:test";
import assert from "node:assert/strict";
import { legacyToTree, withTotal } from "../core/rows.js";

const legacy = withTotal([
  { itemNo: "1", descr: "Mob", cost: 1000, sheetName: "1 - MOB", totalAddr: "$K$30", isTotal: false },
  { itemNo: "2", descr: "Typed", cost: 25, sheetName: "", totalAddr: "", isTotal: false },
], { total: 1025, label: "DIRECT", sheet: "Cost Summary", addr: "$H$9" });

test("a linked row clicks to its sheet and double-clicks to its total", () => {
  const [mob] = legacyToTree(legacy, new Map());
  assert.deepEqual(mob, { key: "item:1", no: "1", label: "Mob", cost: 1000, total: false,
                          jump: { sheet: "1 - MOB" }, focus: { sheet: "1 - MOB", addr: "$K$30" },
                          status: { fails: 0 }, children: [] });
});

test("a typed row is not a link", () => {
  const typed = legacyToTree(legacy, new Map())[1];
  assert.deepEqual([typed.jump, typed.focus], [null, null]);
});

test("a stamped workbook's rows carry their failing-check count; the total never does", () => {
  const rows = legacyToTree(legacy, new Map([["2", 3]]));
  assert.deepEqual(rows.map((r) => r.status), [{ fails: 0 }, { fails: 3 }, null]);
  assert.deepEqual([rows[2].key, rows[2].total, rows[2].jump], ["total", true, { sheet: "Cost Summary" }]);
});

test("a hand-built workbook's rows carry no status", () => {
  assert.ok(legacyToTree(legacy).every((r) => r.status === null));
});
