import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const PANES = new URL("../panes/ifc/", import.meta.url);

test("every named import in panes/ifc/*.js resolves to an export of its module", async () => {
  for (const file of readdirSync(PANES).filter((f) => f.endsWith(".js"))) {
    const src = readFileSync(new URL(file, PANES), "utf8");
    for (const [, names, from] of src.matchAll(/import\s*\{([^}]+)\}\s*from\s*"([^"]+)"/g)) {
      if (!from.startsWith(".")) continue;                     // "three" and its addons come from the import map
      const mod = await import(new URL(from, new URL(file, PANES)).href);
      for (const name of names.split(",").map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean)) {
        assert.ok(name in mod, `${file} imports ${name} from ${from}, which does not export it`);
      }
    }
  }
});

test("main.js calls only functions panes/ifc/excel.js exports", async () => {
  const src = readFileSync(new URL("main.js", PANES), "utf8");
  const excel = await import(new URL("excel.js", PANES).href);
  for (const [, name] of src.matchAll(/\bX\.([A-Za-z_]+)\(/g)) {
    assert.ok(typeof excel[name] === "function", `X.${name} is not exported by panes/ifc/excel.js`);
  }
});

test("the pane's Office.js use stays within ExcelApi 1.9", () => {
  const src = readFileSync(new URL("excel.js", PANES), "utf8");
  // APIs that first appeared after 1.9 must not creep in without the manifest's MinVersion moving with them.
  for (const late of ["getRangeByAddresses", "onFormulaChanged", "comments.add", "showAsTable", "namedSheetViews", "linkedDataTypes"]) {
    assert.ok(!src.includes(late), `${late} is newer than ExcelApi 1.9`);
  }
});

test("ifc.html pins three.js and loads the pane as a module", () => {
  const html = readFileSync(new URL("ifc.html", PANES), "utf8");
  assert.match(html, /"three": "https:\/\/cdn\.jsdelivr\.net\/npm\/three@\d+\.\d+\.\d+\/build\/three\.module\.js"/);
  assert.match(html, /"three\/addons\/": "https:\/\/cdn\.jsdelivr\.net\/npm\/three@\d+\.\d+\.\d+\/examples\/jsm\/"/);
  assert.ok(html.includes('<script type="module" src="main.js"></script>'));
  assert.ok(html.includes('href="../taskpane.css"'), "shares the navigator's stylesheet");
});
