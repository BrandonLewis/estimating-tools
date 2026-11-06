import { test } from "node:test";
import assert from "node:assert/strict";
import { assertAdapter, factRequest, flattenTree, jumpAddress, pick, sourceOf, summarizeChecks, tabsOf, TAB_ORDER }
  from "../core/adapter.js";

const stub = (id, verdict, extra = {}) => ({ id, props: [], cells: [], detect: () => verdict, ...extra });

test("pick returns the first adapter, in order, whose verdict is not no", () => {
  const a = stub("a", "no"), b = stub("b", "yes"), c = stub("c", "yes");
  assert.deepEqual(pick([a, b, c], {}), { adapter: b, verdict: "yes" });
  assert.equal(pick([c, b], {}).adapter, c);
});

test("newer and bad claim the workbook: it never falls through to a later adapter", () => {
  const later = stub("later", "yes");
  assert.deepEqual(pick([stub("a", "newer"), later], {}).verdict, "newer");
  assert.deepEqual(pick([stub("a", "bad"), later], {}).verdict, "bad");
});

test("no adapter claims the workbook: null, so the heuristic runs", () => {
  assert.equal(pick([stub("a", "no"), stub("b", "no")], {}), null);
  assert.equal(pick([], {}), null);
});

test("every detect sees the same facts, and detection stops at the first claim", () => {
  const seen = [];
  const spy = (id, verdict) => stub(id, verdict, { detect: (f) => { seen.push([id, f]); return verdict; } });
  const facts = { props: { estimate_layout: null }, cells: {}, sheetNames: ["Summary"], activeSheet: "Summary" };
  pick([spy("a", "no"), spy("b", "yes"), spy("c", "yes")], facts);
  assert.deepEqual(seen.map(([id]) => id), ["a", "b"]);
  assert.ok(seen.every(([, f]) => f === facts));
});

test("a verdict outside yes/newer/bad/no is a programming error", () => {
  assert.throws(() => pick([stub("odd", "maybe")], {}), /odd: detect returned maybe/);
});

test("factRequest merges every adapter's properties and cells once each, in order", () => {
  assert.deepEqual(factRequest([{ props: ["estimate_layout"], cells: ["est.layout"] },
                                { props: ["estimate_format", "estimate_layout"], cells: ["hc.layout"] }]),
                   { props: ["estimate_layout", "estimate_format"], cells: ["est.layout", "hc.layout"] });
  assert.deepEqual(factRequest([]), { props: [], cells: [] });
});

test("tabsOf: the adapter's tabs in display order; Items alone for a hand-built book; none otherwise", () => {
  const adapter = stub("a", "yes", { tabs: () => ["readback", "items", "checks"] });
  assert.deepEqual(tabsOf({ kind: "ok", adapter, layout: {} }), ["items", "checks", "readback"]);
  assert.deepEqual(tabsOf({ kind: "heuristic" }), ["items"]);
  for (const kind of ["none", "newer", "bad", "error", "loading"]) assert.deepEqual(tabsOf({ kind }), [], kind);
  assert.deepEqual(TAB_ORDER, ["items", "checks", "codes", "insert", "readback"]);
});

test("sourceOf names the adapter's source, or a hand-built workbook", () => {
  const adapter = stub("a", "yes", { source: (l) => `${l.pack} pack` });
  assert.equal(sourceOf({ kind: "ok", adapter, layout: { pack: "fieldbook" } }), "fieldbook pack");
  assert.equal(sourceOf({ kind: "heuristic" }), "Hand-built workbook");
  assert.equal(sourceOf({ kind: "none" }), "");
});

test("jumpAddress: a literal address wins; a row with columns selects that span; a bare sheet selects nothing", () => {
  assert.equal(jumpAddress({ sheet: "S", addr: "$K$30" }), "$K$30");
  assert.equal(jumpAddress({ sheet: "S", row: 31, cols: "A:R" }), "A31:R31");
  assert.equal(jumpAddress({ sheet: "S", row: 31, cols: "K" }), "K31");
  assert.equal(jumpAddress({ sheet: "S", row: 31 }), "A31");
  assert.equal(jumpAddress({ sheet: "S" }), null);
  assert.equal(jumpAddress({ sheet: "S", addr: "" }), null);
  assert.equal(jumpAddress({ sheet: "S", row: 0, cols: "A:R" }), null);
  assert.equal(jumpAddress(null), null);
});

test("flattenTree lists each row before its children, with depth", () => {
  const tree = [{ key: "1", children: [{ key: "1a", children: [{ key: "1a1", children: [] }] }, { key: "1b", children: [] }] },
                { key: "2", children: [] }];
  assert.deepEqual(flattenTree(tree).map(({ row, depth }) => [row.key, depth]),
                   [["1", 0], ["1a", 1], ["1a1", 2], ["1b", 1], ["2", 0]]);
});

test("summarizeChecks puts failures first and leaves info rows out of the counts", () => {
  const rows = [{ status: "pass", item: "A" }, { status: "info", item: "B" }, { status: "fail", item: "C" },
                { status: "fail", item: "D" }];
  const s = summarizeChecks(rows);
  assert.deepEqual([s.pass, s.fail], [1, 2]);
  assert.deepEqual(s.failing.map((r) => r.item), ["C", "D"]);
  assert.deepEqual(s.info.map((r) => r.item), ["B"]);
});

test("assertAdapter names everything an adapter is missing", () => {
  assert.throws(() => assertAdapter({ id: "half", props: [], detect() {} }),
                /adapter half is missing load, damage, tabs, source, read, readCursor, insertKinds, insertFooter, planInsert, scan, readiness, readbackCommand, cells, noCell/);
  assert.throws(() => assertAdapter(null), /adapter \? is missing id/);
});

test("a detect that throws counts as no, with a warning, so a later adapter or the heuristic still runs", (t) => {
  const warn = t.mock.method(console, "warn", () => {});
  const boom = stub("boom", "yes", { detect: () => { throw new Error("garbled"); } });
  const later = stub("later", "yes");
  assert.deepEqual(pick([boom, later], {}), { adapter: later, verdict: "yes" });
  assert.equal(pick([boom], {}), null);
  assert.equal(warn.mock.callCount(), 2);
  assert.match(String(warn.mock.calls[0].arguments[0]), /boom/);
});
