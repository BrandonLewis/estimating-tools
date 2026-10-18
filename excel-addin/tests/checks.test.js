import { test } from "node:test";
import assert from "node:assert/strict";
import { checksFromTable, failingByItem } from "../core/checks.js";

const col = (...xs) => xs.map((x) => [x]);

test("failing checks come first and the counts match the statuses", () => {
  const out = checksFromTable({
    ruleNo: col(1, 1, 9, null), rule: col("Takeoff = qty", "Takeoff = qty", "Code on list", null),
    item: col("1", "2", "2", null), status: col("✓", "✗", "✗", ""),
  });
  assert.deepEqual([out.pass, out.fail], [1, 2]);
  assert.deepEqual(out.rows.map((r) => [r.ruleNo, r.item, r.ok]), [["1", "2", false], ["9", "2", false], ["1", "1", true]]);
  assert.deepEqual([...failingByItem(out)], [["2", 2]]);
});

test("a fully blank row is skipped and the counts are unaffected", () => {
  const out = checksFromTable({
    ruleNo: col(1, null, 2), rule: col("Takeoff = qty", null, "Code on list"),
    item: col("1", null, "2"), status: col("✓", "", "✗"),
  });
  assert.deepEqual([out.pass, out.fail], [1, 1]);
  assert.equal(out.rows.length, 2);
});
