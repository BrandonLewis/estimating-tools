/**
 * Where the Insert tab puts new rows. The add-in writes no formulas: it
 * copies prototype rows from the hidden _templates sheet (named est.tpl.*)
 * with Excel's own copy, the same operation as an estimator's copy-paste.
 */
import { findBlock } from "./blocks.js";

const TEMPLATE = { task: "est.tpl.task", crew: "est.tpl.crew", line: "est.tpl.line" };

export function planInsert(what, kinds, row, blocks) {
  const tpl = TEMPLATE[what];
  if (!tpl) throw new Error(`unknown insert kind ${what}`);
  const block = findBlock(kinds, row, blocks);
  if (!block) return { ok: false, reason: "Put the cursor inside a task block first (from its header row down to its subtotal)." };
  if (what === "task") return { ok: true, at: block.sub + 1, tpl, block };
  if (row > block.end) {
    return { ok: false, reason: "The cursor is below this task's END row, outside its subtotal. Move it between the task header and END." };
  }
  // A crew/line insert at or above the task's note rows would land above
  // them, prying them loose from the header they document. blocks.body's
  // first entry is the note kind (fieldbook: [NOTE, CREW, LINE]); skip past
  // any run of it directly under the head so a note always stays on top.
  const noteKind = blocks.body[0];
  let afterNotes = block.head + 1;
  while ((kinds[afterNotes - 1] || "") === noteKind) afterNotes += 1;
  return { ok: true, at: Math.max(row, afterNotes), tpl, block };
}
