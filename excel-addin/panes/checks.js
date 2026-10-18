import { h, replace, icon } from "./view.js";

/** A workbook-wide check (the unbalance rule) names no one item: its item cell reads "all". */
const WHOLE = "all";
const itemLabel = (item) => (item.toLowerCase() === WHOLE ? "All items" : `Item ${item}`);

export function renderChecks(root, app, x) {
  const c = app.data.checks;
  const items = app.data.items || [];
  const sheetOf = (item) => items.find((r) => !r.isTotal && r.sheetName && r.itemNo === item);
  replace(root,
    h("div", { class: "card" }, h("strong", { class: "ok" }, `${c.pass} ✓`), "  ", h("strong", { class: "bad" }, `${c.fail} ✗`)),
    c.fail ? h("div", { class: "label" }, "Failing — click to open the item") : null,
    c.rows.filter((r) => !r.ok).map((r) => {
      const target = sheetOf(r.item);
      return h("button", { class: "row-btn", onclick: target ? () => x.go(target.sheetName, target.totalAddr) : null, disabled: !target },
        icon.bad(), h("span", {}, h("strong", {}, itemLabel(r.item)), ` · check ${r.ruleNo}`, h("br"), r.rule));
    }),
    h("div", { class: "label" }, "Passing"),
    c.rows.filter((r) => r.ok).map((r) => h("div", { class: "muted" }, icon.ok(), ` ${itemLabel(r.item)} · ${r.rule}`)));
}
