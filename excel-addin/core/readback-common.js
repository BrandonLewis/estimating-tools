/**
 * Read-back helpers every pack shares: the workbook's file name, and the scan
 * that finds rows with visible text but no kind tag.
 */
import { cellText } from "./refs.js";

/** Runs of rows (1-based, inclusive) whose kind is blank: the only rows that can be untagged. */
export function blankRuns(kinds) {
  const runs = [];
  for (let i = 0; i < kinds.length; i += 1) {
    if (cellText(kinds[i]).trim() !== "") continue;
    const last = runs[runs.length - 1];
    if (last && last.last === i) last.last = i + 1;
    else runs.push({ first: i + 1, last: i + 1 });
  }
  return runs;
}

/**
 * A `visible` array for untaggedRows from the values of just the blank-kind
 * runs (runValues[k] holds run k's rows). Every other row is left empty: it
 * has a kind, so it is tagged whatever it shows.
 */
export function visibleFromRuns(count, runs, runValues) {
  const visible = Array.from({ length: count }, () => []);
  runs.forEach((run, k) => {
    for (let r = run.first; r <= run.last; r += 1) visible[r - 1] = runValues[k]?.[r - run.first] || [];
  });
  return visible;
}

/**
 * The workbook's file name from Office.context.document.url, and whether it
 * lives in the cloud. Only a cloud (http/https) URL is percent-encoded; a
 * local path's name is literal, so decoding it would mangle a file that
 * genuinely has a `%` in its name.
 */
export function workbookFile(url) {
  const u = String(url || "");
  const cloud = /^https?:\/\//i.test(u);
  const last = u.split(/[\\/]/).pop() || "";
  let name = last.split("?")[0];
  if (cloud) {
    try { name = decodeURIComponent(name); } catch { /* keep the raw name */ }
  }
  return { name, cloud };
}

/**
 * "Sheet row N" for each row with visible text but no recognized kind tag.
 * visible[i] is row i+1's visible cells. `known`, when given, is the set of
 * kinds the pane recognizes for this workbook -- the pane passes the kinds
 * it knows from `layout.blocks` (head/body/end/sub), plus whatever kinds the
 * stamp lists in the future. Python read-back's full KINDS set (ITEM, HEAD,
 * TAKEOFF, RECAP, TOTAL, ...) is not carried in the stamp today, so a caller
 * that omits `known` keeps today's behaviour: any non-blank kind is tagged.
 */
export function untaggedRows(sheet, visible, kinds, known) {
  const out = [];
  for (let i = 0; i < visible.length; i += 1) {
    const hasText = (visible[i] || []).some((v) => cellText(v).trim() !== "");
    const kind = cellText(kinds[i]).trim();
    const tagged = kind !== "" && (!known || known.has(kind));
    if (hasText && !tagged) out.push(`${sheet} row ${i + 1}`);
  }
  return out;
}
