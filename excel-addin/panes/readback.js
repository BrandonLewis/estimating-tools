import { h, replace, icon } from "./view.js";
import { readiness, command, workbookFile, untaggedRows } from "../core/readback.js";

/**
 * The sheet scan is the slow part, so it is cached on `app.scan` and redone
 * only when the tab is entered or "Check again" is clicked (both clear it),
 * never on the refresh every workbook edit triggers. The cache holds the
 * promise, so two renders in a row share one scan.
 */
function scanOnce(app, x, layout) {
  if (!app.scan) {
    const scan = { at: new Date(), promise: x.scanItemSheets(layout.tags, layout.blocks.item) };
    scan.promise.catch(() => { if (app.scan === scan) app.scan = null; });
    app.scan = scan;
  }
  return app.scan;
}

export async function renderReadback(root, app, x) {
  const layout = app.state.layout;
  if (!app.scan) replace(root, h("p", { class: "muted" }, "Checking…"));
  const scan = scanOnce(app, x, layout);
  let dirty, result;
  try {
    [dirty, result] = await Promise.all([x.readDirty(), scan.promise]);
  } catch (e) {
    if (x.current()) replace(root, h("p", {}, String(e.message || e)));
    return;
  }
  if (!x.current()) return;
  // No `known` set: item sheets also carry HEAD, TAKEOFF, RECAP, TOTAL and
  // ITEM rows, which the stamp's blocks do not list, so any non-blank kind
  // counts as tagged.
  const untagged = result.sheets.flatMap((s) => untaggedRows(s.sheet, s.visible, s.kinds));
  const checks = readiness({ layout, dirty, untagged, tooLarge: result.tooLarge });
  const file = workbookFile(x.documentUrl());
  const cmd = command(layout.spec, file.name);
  // Advisory rows (unknown save state, a sheet too large to scan here) are
  // reminders: they are listed but do not hold the copy button back.
  const ready = checks.every((c) => c.ok || c.advisory);
  const status = h("span", { class: "muted" });
  const time = scan.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  replace(root,
    h("div", { class: "label" }, "Ready to read back?"),
    checks.map((c) => h("div", { style: "display:flex;gap:8px;padding:6px 2px;border-bottom:1px solid var(--line)" },
      c.ok ? icon.ok() : icon.warn(), h("span", {}, c.text, c.sub ? [h("br"), h("span", { class: "muted" }, c.sub)] : null))),
    h("p", { class: "muted" }, `Rows checked at ${time}.`),
    h("button", { class: "btn", onclick: () => { app.scan = null; x.refresh(); } }, "Check again"),
    h("div", { class: "label" }, "Command"),
    cmd ? h("div", { class: "cmd" }, cmd)
      : h("p", {}, "This workbook's stamp names no spec file, or the spec or workbook name has characters that are not safe to paste into a terminal, or the workbook has not been saved yet. Run read-back by hand."),
    h("button", { class: "btn primary", style: "margin-top:10px;width:100%", disabled: !cmd || !ready, onclick: async () => {
      try { await navigator.clipboard.writeText(cmd); status.textContent = " Copied."; }
      catch { status.textContent = " Select the command above and copy it."; }
    } }, "Copy command"), status,
    h("p", { class: "muted" }, "Paste it into a terminal in the workbook's folder. An add-in can't run it for you.",
      file.cloud ? " This workbook is on OneDrive or SharePoint: sync it to this computer first." : ""));
}
