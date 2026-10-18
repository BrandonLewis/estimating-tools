import { test } from "node:test";
import assert from "node:assert/strict";
import { parseLayout, tabsFor, KNOWN_LAYOUT_VERSION } from "../core/stamp.js";

const LAYOUT = {
  pack: "fieldbook", pack_version: "1", layout_version: 1, tables: ["checks", "codes", "index"],
  tags: { kind: "Q", code_chain: "R" },
  blocks: { item: "ITEM", head: "TASK", body: ["NOTE", "CREW", "LINE"], end: "END", sub: "SUBTOTAL", code_col: "A" },
  templates: true, spec: "job.estimate.yaml",
};

test("no property means no stamp", () => {
  assert.deepEqual(parseLayout(null), { kind: "none" });
  assert.deepEqual(parseLayout(""), { kind: "none" });
});

test("a good stamp parses", () => {
  const out = parseLayout(JSON.stringify(LAYOUT));
  assert.equal(out.kind, "ok");
  assert.equal(out.layout.pack, "fieldbook");
});

test("a newer layout says update, and never guesses", () => {
  const out = parseLayout(JSON.stringify({ ...LAYOUT, layout_version: KNOWN_LAYOUT_VERSION + 1 }));
  assert.equal(out.kind, "newer");
});

test("a malformed stamp is reported, not trusted", () => {
  assert.equal(parseLayout("{not json").kind, "bad");
  assert.equal(parseLayout(JSON.stringify({ ...LAYOUT, tags: { kind: "Q" } })).kind, "bad");
  assert.equal(parseLayout(JSON.stringify({ ...LAYOUT, tables: "index" })).kind, "bad");
});

test("tabs follow the tables that resolved", () => {
  assert.deepEqual(tabsFor({ kind: "ok", layout: LAYOUT }), ["items", "checks", "codes", "insert", "readback"]);
  assert.deepEqual(tabsFor({ kind: "ok", layout: { ...LAYOUT, tables: ["index"], templates: false } }),
                   ["items", "readback"]);
  assert.deepEqual(tabsFor({ kind: "heuristic" }), ["items"]);
  assert.deepEqual(tabsFor({ kind: "none" }), []);
});
