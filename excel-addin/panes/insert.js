import { h, replace } from "./view.js";
import { planInsert } from "../core/insert.js";
import { NO_CELL } from "./codes.js";

const ACTIONS = [
  ["task", "New task", "A task block (header, crew, line, END, subtotal) below this one. The item total picks it up after read-back and a rebuild."],
  ["crew", "New crew row", "A crew row inside this task, at the cursor."],
  ["line", "New line", "A material, equipment or subcontract line inside this task, at the cursor."],
];

/** The outcome card. Kept on `app` because the insert itself fires a workbook change, and the refresh re-renders this tab. */
function noteCard(note) {
  return note ? h("div", { class: `card ${note.ok ? "ok" : "bad"}` }, note.text) : null;
}

/**
 * One insert at a time. `app.inserting` outlives this render (the insert's own
 * change event re-renders the tab mid-call), so every render's buttons start
 * disabled while one is in flight, and the finishing call re-enables whichever
 * buttons are on screen by then.
 */
function setBusy(app, busy) {
  app.inserting = busy;
  for (const b of app.insertButtons) b.disabled = busy;
}

export async function renderInsert(root, app, x) {
  const { blocks, tags } = app.state.layout;
  let ctx;
  try { ctx = await x.readActive(tags); } catch {
    if (x.current()) replace(root, h("p", { class: "muted" }, NO_CELL));
    return;
  }
  if (!x.current()) return;
  const note = h("div");
  const say = (ok, text) => { app.insertNote = { ok, text }; replace(note, noteCard(app.insertNote)); };
  replace(note, noteCard(app.insertNote));
  const buttons = ACTIONS.map(([what, title, sub]) => h("button", { class: "row-btn", disabled: app.inserting, onclick: async () => {
    if (app.inserting) return;
    setBusy(app, true);
    try {
      let fresh;
      try { fresh = await x.readActive(tags); } catch { return say(false, NO_CELL); }
      const plan = planInsert(what, fresh.kinds, fresh.row, blocks);
      if (!plan.ok) return say(false, plan.reason);
      const done = await x.insertTemplate(fresh.sheet, plan.at, plan.tpl);
      say(true, `Inserted rows ${done.first}–${done.last} from _templates. Fill in the blank cells.`);
    } catch (e) {
      say(false, `Could not insert: ${String(e.message || e)}. If the sheet is protected, unprotect it first.`);
    } finally {
      setBusy(app, false);
    }
  } }, h("span", {}, h("strong", {}, title), h("br"), h("span", { class: "muted" }, sub))));
  app.insertButtons = buttons;
  replace(root,
    h("div", { class: "card" }, h("div", { class: "label" }, "Cursor"), `${ctx.sheet} · row ${ctx.row}`),
    buttons,
    note,
    h("p", { class: "muted" }, "Rows are copied from the hidden _templates sheet with Excel's own copy, exactly like a copy-paste, so read-back accepts them. Rows are never inserted below a task's END row, so every subtotal still covers them."));
}
