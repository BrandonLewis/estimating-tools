import { h, replace } from "./view.js";

/** The outcome card. Kept on `app` because the insert itself fires a workbook change, and the refresh re-renders this tab. */
function noteCard(note) {
  return note ? h("div", { class: `card ${note.warn ? "warn" : note.ok ? "ok" : "bad"}` }, note.text) : null;
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

/**
 * The adapter's Insert buttons. A plan with `confirm` is asked first: the pane
 * shows the question, and the same button at the same spot inserts on the
 * second click. Every insert is one Excel.run, so one undo reverts it.
 */
export async function renderInsert(root, app, x) {
  const { adapter, layout } = app.state;
  let ctx;
  // A chart sheet, a shape or another non-cell selection has no active cell.
  try { ctx = await adapter.readCursor(x, layout); } catch {
    if (x.current()) replace(root, h("p", { class: "muted" }, adapter.noCell));
    return;
  }
  if (!x.current()) return;
  const note = h("div");
  const say = (ok, text, warn = false) => { app.insertNote = { ok, text, warn }; replace(note, noteCard(app.insertNote)); };
  replace(note, noteCard(app.insertNote));
  const buttons = adapter.insertKinds(layout).map(({ what, label, sub }) => h("button", { class: "row-btn", disabled: app.inserting, onclick: async () => {
    if (app.inserting) return;
    setBusy(app, true);
    try {
      let fresh;
      try { fresh = await adapter.readCursor(x, layout); } catch { return say(false, adapter.noCell); }
      const plan = adapter.planInsert(what, fresh);
      if (plan.refused) { app.insertConfirm = null; return say(false, plan.refused); }
      const key = `${what}|${plan.sheet}|${plan.at}`;
      if (plan.confirm && app.insertConfirm !== key) {
        app.insertConfirm = key;
        return say(false, `${plan.confirm} Click ${label} again to insert.`, true);
      }
      app.insertConfirm = null;
      const done = await x.insertTemplate(plan.sheet, plan.at, plan.template);
      say(true, `Inserted rows ${done.first}–${done.last} from _templates. ${plan.fill || "Fill in the blank cells."}`);
    } catch (e) {
      say(false, `Could not insert: ${String(e.message || e)}. If the sheet is protected, unprotect it first.`);
    } finally {
      setBusy(app, false);
    }
  } }, h("span", {}, h("strong", {}, label), h("br"), h("span", { class: "muted" }, sub))));
  app.insertButtons = buttons;
  replace(root,
    h("div", { class: "card" }, h("div", { class: "label" }, "Cursor"), `${ctx.sheet} · row ${ctx.row}`),
    buttons,
    note,
    h("p", { class: "muted" }, adapter.insertFooter(layout)));
}
