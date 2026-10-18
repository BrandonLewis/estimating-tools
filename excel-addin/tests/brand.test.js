import { test } from "node:test";
import assert from "node:assert/strict";
import { resolveBrand, cssVars, brandPath, TOKENS } from "../core/brand.js";

const generic = { name: "Estimate Navigator", support_url: "https://x/support",
  colors: { light: { accent: "#24507A", on_accent: "#FFFFFF", surface: "#FFFFFF", text: "#1F2328", muted: "#5B616B", line: "#D5D9DF" },
            dark: { accent: "#7FB0E0", on_accent: "#0E1A26", surface: "#1F1F1F", text: "#E8E8E8", muted: "#B3B0AD", line: "#3B3A39" } } };

test("workbook beats deployment beats generic, colour by colour", () => {
  const b = resolveBrand({ generic,
    deployment: { name: "Client Index", colors: { light: { accent: "#B4531A" } } },
    workbook: { colors: { light: { muted: "#444444" } }, support_url: "https://evil" } });
  assert.equal(b.name, "Client Index");
  assert.equal(b.colors.light.accent, "#B4531A");
  assert.equal(b.colors.light.muted, "#444444");
  assert.equal(b.colors.light.surface, "#FFFFFF");
  assert.equal(b.support_url, "https://x/support");     // a workbook never sets links
});

test("bad colours are ignored", () => {
  const b = resolveBrand({ generic, workbook: { colors: { light: { accent: "red;background:url(x)" } } } });
  assert.equal(b.colors.light.accent, "#24507A");
});

test("cssVars maps tokens to custom properties", () => {
  const v = cssVars(generic, false);
  assert.equal(v["--accent"], "#24507A");
  assert.equal(Object.keys(v).length, TOKENS.length);
  assert.equal(cssVars(generic, true)["--surface"], "#1F1F1F");
});

test("brandPath reads a safe slug only, relative to panes/taskpane.html", () => {
  assert.equal(brandPath(""), "../../../brand.json");
  assert.equal(brandPath("client-a"), "../../../client-a/brand.json");
  assert.equal(brandPath("../etc"), "../../../brand.json");
  const pane = "https://h/excel/addons/navigator/1.0.0/panes/taskpane.html";
  assert.equal(new URL(brandPath(""), pane).href, "https://h/excel/addons/brand.json");
  assert.equal(new URL(brandPath("client-a"), pane).href, "https://h/excel/addons/client-a/brand.json");
});
