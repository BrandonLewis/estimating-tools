import { h, replace, icon } from "./view.js";
import { summarizeChecks } from "../core/adapter.js";

/** The adapter's check rows: failures first, then passes, then export-only rows, which are never counted. */
export function renderChecks(root, app, x) {
  const c = summarizeChecks(app.data.checks || []);
  replace(root,
    h("div", { class: "card" }, h("strong", { class: "ok" }, `${c.pass} ✓`), "  ", h("strong", { class: "bad" }, `${c.fail} ✗`)),
    c.fail ? h("div", { class: "label" }, "Failing — click to open the item") : null,
    c.failing.map((r) => h("button", { class: "row-btn", onclick: r.jump ? () => x.jump(r.jump) : null, disabled: !r.jump },
      icon.bad(), h("span", {}, h("strong", {}, r.item), r.ref ? ` · ${r.ref}` : null, h("br"), r.rule,
        r.text ? [h("br"), h("span", { class: "muted" }, r.text)] : null))),
    h("div", { class: "label" }, "Passing"),
    c.passing.map((r) => h("div", { class: "muted" }, icon.ok(), ` ${r.item} · ${r.rule}`)),
    c.info.length ? h("div", { class: "label" }, "Export only") : null,
    c.info.map((r) => h("div", { class: "muted" }, `${r.item} · ${r.rule}${r.text ? ` · ${r.text}` : ""}`)));
}
