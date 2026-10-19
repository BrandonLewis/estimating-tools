/** The Read back tab: is this workbook ready, and the exact command to run. */
import { cellText } from "./refs.js";

/**
 * Packs `est-estimate read-back` can read today -- and so any pack that
 * declares `derived_from:` one of them (an org fork that keeps its grid),
 * which the layout JSON carries as `derived_from`.
 */
export const READBACK_PACKS = new Set(["fieldbook"]);

/** True when read-back reads workbooks laid out by `layout`'s pack. */
export function readbackSupported(layout) {
  return READBACK_PACKS.has(layout?.pack) || READBACK_PACKS.has(layout?.derived_from);
}

/**
 * The readiness list. A row with `advisory: true` is a reminder the pane
 * shows but does not hold the command back for: the host cannot say whether
 * the workbook is saved, or a sheet was too large to scan here (read-back
 * itself still checks it).
 */
export function readiness({ layout, dirty, untagged, tooLarge = [] }) {
  const supported = readbackSupported(layout);
  const packs = [...READBACK_PACKS].join(", ");
  const rows = [
    { ok: !!layout, text: "Built by est-estimate", sub: layout ? `${layout.pack} pack` : "No estimate_layout stamp" },
    { ok: supported, text: "Read-back supports this pack", sub: supported ? "" : `Read-back reads ${packs} workbooks, or a pack derived from ${packs}` },
    dirty === false
      ? { ok: true, text: "No unsaved changes", sub: "" }
      : dirty === true
        ? { ok: false, text: "Unsaved changes", sub: "Save the workbook, then check again." }
        : { ok: false, advisory: true, text: "Save the workbook first", sub: "Excel here cannot say whether it has unsaved changes." },
    untagged.length
      ? { ok: false, text: "Rows outside the tagged blocks", sub: untagged.slice(0, 5).join("; ") + (untagged.length > 5 ? "; …" : "") }
      : { ok: true, text: "Every row sits inside a tagged block", sub: "" },
  ];
  if (tooLarge.length) {
    rows.push({ ok: false, advisory: true, text: "Some sheets were not checked",
                sub: tooLarge.map((s) => `${s}: too large to check here; read-back will still check it`).join("; ") });
  }
  return rows;
}

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

// `spec` comes from an editable workbook cell. PowerShell, bash and cmd all
// expand `$`, a backtick or `%` inside double quotes, so a quoted name is not
// enough: only a bare, punctuation-limited file name is ever interpolated
// into the shell command. No path separators, so a name cannot escape into
// another directory either.
const SAFE_SPEC = /^[\p{L}\p{N} _.\-()#&,+']+\.ya?ml$/u;
const SAFE_WORKBOOK = /^[\p{L}\p{N} _.\-()#&,+']+$/u;

/** The read-back command, or null when a name is not safe to interpolate. */
export function command(specName, workbookName) {
  if (!SAFE_SPEC.test(specName || "") || !SAFE_WORKBOOK.test(workbookName || "")) return null;
  return `est-estimate read-back "${specName}" "${workbookName}" --write`;
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
