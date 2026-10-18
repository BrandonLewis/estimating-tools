import { h, replaceKeepingFocus, icon } from "./view.js";
import { costText } from "../core/items.js";

/** What a screen reader announces for a row, e.g. "Item 3, Hot mix asphalt, 2 failing checks". */
function rowLabel(r, stamped, fails) {
  if (r.isTotal) return `${r.itemNo} total, ${costText(r.cost)}`;
  const parts = [`Item ${r.itemNo}`];
  if (r.descr) parts.push(r.descr);
  if (stamped) parts.push(fails ? `${fails} failing check${fails === 1 ? "" : "s"}` : "all checks pass");
  if (!r.sheetName) parts.push("not a link");
  return parts.join(", ");
}

export function renderItems(root, app, x) {
  const rows = app.data.items || [];
  const failing = app.data.failing || new Map();
  const stamped = app.state.kind === "ok";
  const active = (app.activeSheet || "").toUpperCase();
  const body = rows.map((r) => {
    const go = !!r.sheetName;
    const cls = [r.isTotal ? "total" : "", go ? "go" : "dead",
                 go && !r.isTotal && r.sheetName.toUpperCase() === active ? "sel" : ""].join(" ");
    const fails = failing.get(r.itemNo) || 0;
    return h("tr", { class: cls, tabindex: go ? "0" : null, "aria-label": rowLabel(r, stamped, fails),
      "data-focus-key": go ? (r.isTotal ? "total" : `item:${r.itemNo}`) : null,
      onclick: go ? () => x.go(r.sheetName, null) : null,
      ondblclick: go ? () => x.go(r.sheetName, r.totalAddr) : null,
      onkeydown: go ? (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); x.go(r.sheetName, r.totalAddr); }
      } : null },
      h("td", {}, r.itemNo),
      h("td", { class: "c-descr", title: r.descr }, r.descr,
        stamped && !r.isTotal ? [" ", fails ? icon.bad() : icon.ok(), fails ? h("span", { class: "bad" }, ` ${fails}`) : null] : null),
      h("td", { class: "num" }, costText(r.cost)));
  });
  replaceKeepingFocus(root,
    h("table", {},
      h("colgroup", {}, h("col", { style: "width:3.6em" }), h("col", { class: "c-descr" }), h("col", { style: "width:8em" })),
      h("thead", {}, h("tr", {}, h("th", {}, "Item"), h("th", { class: "c-descr" }, "Description"), h("th", { class: "num" }, "Cost"))),
      h("tbody", {}, body)),
    h("p", { class: "muted" }, "Click an item to open its sheet; double-click, Enter or Space goes to its total. Grey rows are typed values, not links."));
}
