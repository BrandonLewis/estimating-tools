import { h, replaceKeepingFocus, icon } from "./view.js";
import { costText } from "../core/rows.js";
import { flattenTree } from "../core/adapter.js";

/** What a screen reader announces for a row, e.g. "Item 3, Hot mix asphalt, 2 failing checks". */
function rowLabel(r) {
  if (r.total) return `${r.no} total, ${costText(r.cost)}`;
  const parts = r.no ? [`Item ${r.no}`] : [];
  if (r.label) parts.push(r.label);
  if (r.note) parts.push(r.note);
  if (r.status) parts.push(r.status.fails ? `${r.status.fails} failing check${r.status.fails === 1 ? "" : "s"}` : "all checks pass");
  if (!r.jump) parts.push("not a link");
  return parts.join(", ");
}

/**
 * The Items tree the adapter returned, each row's children indented under it.
 * A row whose jump names only a sheet (no row, no address) is highlighted
 * while that sheet is active.
 */
export function renderItems(root, app, x) {
  const rows = app.data.items || [];
  const active = (app.activeSheet || "").toUpperCase();
  const body = flattenTree(rows).map(({ row: r, depth }) => {
    const go = !!r.jump;
    const deep = r.focus || r.jump;
    const sel = go && !r.total && r.jump.row === undefined && !r.jump.addr && r.jump.sheet.toUpperCase() === active;
    const cls = [r.total ? "total" : "", go ? "go" : "dead", sel ? "sel" : ""].join(" ");
    const fails = r.status ? r.status.fails : 0;
    return h("tr", { class: cls, tabindex: go ? "0" : null, "aria-label": rowLabel(r),
      "data-focus-key": go ? r.key : null,
      onclick: go ? () => x.jump(r.jump) : null,
      ondblclick: go ? () => x.jump(deep) : null,
      onkeydown: go ? (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); x.jump(deep); }
      } : null },
      h("td", {}, r.no),
      h("td", { class: "c-descr", title: r.label, style: depth ? `padding-left:${6 + 14 * depth}px` : null }, r.label,
        r.status ? [" ", fails ? icon.bad() : icon.ok(), fails ? h("span", { class: "bad" }, ` ${fails}`) : null] : null,
        r.note ? [h("br"), h("span", { class: "muted" }, r.note)] : null),
      h("td", { class: "num" }, costText(r.cost)));
  });
  replaceKeepingFocus(root,
    h("table", {},
      h("colgroup", {}, h("col", { style: "width:3.6em" }), h("col", { class: "c-descr" }), h("col", { style: "width:8em" })),
      h("thead", {}, h("tr", {}, h("th", {}, "Item"), h("th", { class: "c-descr" }, "Description"), h("th", { class: "num" }, "Cost"))),
      h("tbody", {}, body)),
    h("p", { class: "muted" }, "Click an item to open its sheet; double-click, Enter or Space goes to its total. Grey rows are typed values, not links."));
}
