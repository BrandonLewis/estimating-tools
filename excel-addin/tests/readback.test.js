import { test } from "node:test";
import assert from "node:assert/strict";
import { readiness, command, workbookFile, untaggedRows, blankRuns, visibleFromRuns } from "../core/readback.js";

const layout = { pack: "fieldbook", spec: "job.estimate.yaml" };

test("all green when stamped, supported, saved and fully tagged", () => {
  const r = readiness({ layout, dirty: false, untagged: [] });
  assert.ok(r.every((x) => x.ok));
  assert.equal(r.length, 4);
});

test("unknown dirtiness is a reminder, not a pass", () => {
  const saved = readiness({ layout, dirty: null, untagged: [] })[2];
  assert.deepEqual([saved.ok, saved.text], [false, "Save the workbook first"]);
});

test("an unsupported pack and untagged rows are named", () => {
  const r = readiness({ layout: { pack: "other" }, dirty: true, untagged: ["2 - MAIN row 40"] });
  assert.deepEqual(r.map((x) => x.ok), [true, false, false, false]);
  assert.match(r[3].sub, /2 - MAIN row 40/);
});

test("the command quotes both paths and refuses a quote inside one", () => {
  assert.equal(command("job.estimate.yaml", "Job.xlsx"),
               'est-estimate read-back "job.estimate.yaml" "Job.xlsx" --write');
  assert.equal(command('a"b.yaml', "Job.xlsx"), null);
  assert.equal(command(undefined, "Job.xlsx"), null);
});

test("the command accepts a realistic punctuated name", () => {
  assert.equal(command("job.estimate.yaml", "Bid (Rev 2) #12 & Co's.xlsx"),
               'est-estimate read-back "job.estimate.yaml" "Bid (Rev 2) #12 & Co\'s.xlsx" --write');
});

test("the command refuses shell metacharacters in either name", () => {
  for (const bad of ["job$.yaml", "job`.yaml", "job%.yaml", "job!.yaml", "dir/job.yaml", "dir\\job.yaml"]) {
    assert.equal(command(bad, "Job.xlsx"), null, bad);
  }
  for (const bad of ["Job$.xlsx", "Job`.xlsx", "Job%.xlsx", "Job!.xlsx", "dir/Job.xlsx", "dir\\Job.xlsx"]) {
    assert.equal(command("job.yaml", bad), null, bad);
  }
});

test("a spec name without a .yaml/.yml extension is refused", () => {
  assert.equal(command("job", "Job.xlsx"), null);
  assert.equal(command("job.txt", "Job.xlsx"), null);
});

test("workbookFile splits local and cloud documents, and only decodes the cloud name", () => {
  assert.deepEqual(workbookFile("C:\\Bids\\Job 12.xlsx"), { name: "Job 12.xlsx", cloud: false });
  assert.deepEqual(workbookFile("https://contoso.sharepoint.com/sites/x/Shared%20Documents/Job%2012.xlsx"),
                   { name: "Job 12.xlsx", cloud: true });
  assert.deepEqual(workbookFile(""), { name: "", cloud: false });
  assert.deepEqual(workbookFile("C:\\Bids\\50%25 off.xlsx"), { name: "50%25 off.xlsx", cloud: false });
});

test("untaggedRows lists rows with visible text but no kind", () => {
  const visible = [["Item 2"], [""], ["Saw cut"], ["x"]];
  const kinds = ["ITEM", "", "", "CREW"];
  assert.deepEqual(untaggedRows("2 - MAIN", visible, kinds), ["2 - MAIN row 3"]);
});

test("untaggedRows treats a kind outside `known` as untagged too", () => {
  const visible = [["Item 2"], ["Saw cut"], ["x"]];
  const kinds = ["ITEM", "WEIRD", "CREW"];
  const known = new Set(["ITEM", "CREW"]);
  assert.deepEqual(untaggedRows("2 - MAIN", visible, kinds, known), ["2 - MAIN row 2"]);
  // Without `known`, any non-blank kind still counts as tagged (today's behaviour).
  assert.deepEqual(untaggedRows("2 - MAIN", visible, kinds), []);
});

test("the save reminder is advisory; real failures are not", () => {
  const r = readiness({ layout, dirty: null, untagged: [] });
  assert.equal(r[2].advisory, true);
  assert.ok(r.every((x) => x.ok || x.advisory), "only the reminder is not ok, and it is advisory");
  const dirty = readiness({ layout, dirty: true, untagged: ["S row 2"] });
  assert.ok(!dirty[2].advisory, "known unsaved changes are a real failure");
  assert.ok(!dirty[3].advisory, "untagged rows are a real failure");
  assert.ok(readiness({ layout, dirty: false, untagged: [] }).every((x) => !x.advisory));
});

test("sheets too large to scan are named in an advisory row", () => {
  const r = readiness({ layout, dirty: false, untagged: [], tooLarge: ["Big 1", "Big 2"] });
  assert.equal(r.length, 5);
  const big = r[4];
  assert.deepEqual([big.ok, big.advisory], [false, true]);
  assert.match(big.sub, /Big 1: too large to check here; read-back will still check it/);
  assert.match(big.sub, /Big 2: too large to check here/);
  assert.equal(readiness({ layout, dirty: false, untagged: [], tooLarge: [] }).length, 4);
});

test("blankRuns groups the rows with a blank kind into 1-based runs", () => {
  assert.deepEqual(blankRuns(["ITEM", "", "", "HEAD", "", "TASK", null, " "]),
                   [{ first: 2, last: 3 }, { first: 5, last: 5 }, { first: 7, last: 8 }]);
  assert.deepEqual(blankRuns(["ITEM", "TASK"]), []);
  assert.deepEqual(blankRuns([]), []);
});

test("visibleFromRuns fills only the run rows and feeds untaggedRows", () => {
  const kinds = ["ITEM", "", "", "CREW", ""];
  const runs = blankRuns(kinds);
  const visible = visibleFromRuns(kinds.length, runs, [[[""], ["stray"]], [["also"]]]);
  assert.equal(visible.length, 5);
  assert.deepEqual(visible[0], []);
  assert.deepEqual(visible[2], ["stray"]);
  assert.deepEqual(untaggedRows("S", visible, kinds), ["S row 3", "S row 5"]);
});
