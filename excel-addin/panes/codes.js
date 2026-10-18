import { h, replace, replaceKeepingFocus } from "./view.js";
import { findBlock } from "../core/blocks.js";
import { searchCodes, isListed } from "../core/codes.js";

export const NO_CELL = "Select a cell on an item sheet.";

export async function renderCodes(root, app, x) {
  const { blocks, tags } = app.state.layout;
  let ctx;
  // A chart sheet, a shape or another non-cell selection has no active cell.
  try { ctx = await x.readActive(tags); } catch {
    if (x.current()) replace(root, h("p", { class: "muted" }, NO_CELL));
    return;
  }
  if (!x.current()) return;
  const block = findBlock(ctx.kinds, ctx.row, blocks);
  const current = block ? ctx.chain[block.head - 1] : "";
  const results = h("div");
  const status = h("div");
  const q = h("input", { type: "search", id: "code-q", "data-focus-key": "code-q", "aria-label": "Search codes",
                         placeholder: "Search code or description" });
  q.value = app.codeQuery || "";
  const draw = () => replace(results, searchCodes(app.data.codes, q.value).slice(0, 50).map((c) =>
    h("div", { style: "display:flex;align-items:center;gap:10px;padding:6px 2px;border-bottom:1px solid var(--line)" },
      h("span", { class: "chip" }, c.code), h("span", { style: "flex:1" }, c.descr),
      c.code === current ? h("span", { class: "ok" }, "In use")
        : h("button", { class: "btn", disabled: !block, onclick: async () => {
            try {
              await x.writeCell(ctx.sheet, `${blocks.code_col}${block.head}`, c.code);
            } catch (e) {
              replace(status, h("div", { class: "card bad" }, `Could not write the code: ${String(e.message || e)}`));
              return;
            }
            // Queued behind any refresh already running, so it cannot race it.
            await x.refresh();
          } }, "Use"))));
  q.addEventListener("input", () => { app.codeQuery = q.value; draw(); });
  draw();
  replaceKeepingFocus(root,
    h("div", { class: "card" }, block
      ? [h("div", { class: "label" }, "Cursor is in"), `${ctx.sheet} · task at row ${block.head}`, h("br"),
         "Current code ", h("span", { class: "chip" }, current || "—"), " ",
         current ? (isListed(app.data.codes, current) ? h("span", { class: "ok" }, "on the org list")
                                                       : h("span", { class: "bad" }, "not on the org list (check 9)")) : null]
      : "Put the cursor in a task block (its header row down to its subtotal) to set its code."),
    status,
    h("label", { for: "code-q", class: "label" }, "Search codes"), q, results,
    h("p", { class: "muted" }, "Use writes the code into the task's header row."));
}
