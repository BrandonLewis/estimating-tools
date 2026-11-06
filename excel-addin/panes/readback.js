import { h, replace, icon } from "./view.js";
import { workbookFile } from "../core/readback-common.js";

/**
 * The adapter's scan is the slow part, so it is cached on `app.scan` and
 * redone only when the tab is entered or "Check again" is clicked (both clear
 * it), never on the refresh every workbook edit triggers. The cache holds the
 * promise, so two renders in a row share one scan.
 */
function scanOnce(app, x, adapter, layout) {
  if (!app.scan) {
    const scan = { at: new Date(), promise: adapter.scan(x, layout) };
    scan.promise.catch(() => { if (app.scan === scan) app.scan = null; });
    app.scan = scan;
  }
  return app.scan;
}

export async function renderReadback(root, app, x) {
  const { adapter, layout } = app.state;
  if (!app.scan) replace(root, h("p", { class: "muted" }, "Checking…"));
  const scan = scanOnce(app, x, adapter, layout);
  let dirty, result;
  try {
    [dirty, result] = await Promise.all([x.readDirty(), scan.promise]);
  } catch (e) {
    if (x.current()) replace(root, h("p", {}, String(e.message || e)));
    return;
  }
  if (!x.current()) return;
  const checks = adapter.readiness(layout, { dirty, scan: result });
  const file = workbookFile(x.documentUrl());
  const cmd = adapter.readbackCommand(layout, file);
  // Advisory rows (unknown save state, a sheet too large to scan here) are
  // reminders: they are listed but do not hold the copy button back.
  const ready = checks.every((c) => c.ok || c.advisory);
  const status = h("span", { class: "muted" });
  const time = scan.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  replace(root,
    h("div", { class: "label" }, "Ready to read back?"),
    checks.map((c) => h("div", { style: "display:flex;gap:8px;padding:6px 2px;border-bottom:1px solid var(--line)" },
      c.ok ? icon.ok() : icon.warn(), h("span", {}, c.text, c.sub ? [h("br"), h("span", { class: "muted" }, c.sub)] : null),
      c.jump ? h("button", { class: "btn", style: "margin-left:auto", onclick: () => x.jump(c.jump) }, "Go") : null)),
    h("p", { class: "muted" }, `Rows checked at ${time}.`),
    h("button", { class: "btn", onclick: () => { app.scan = null; x.refresh(); } }, "Check again"),
    h("div", { class: "label" }, "Command"),
    cmd.command ? h("div", { class: "cmd" }, cmd.command) : h("p", {}, cmd.why),
    h("button", { class: "btn primary", style: "margin-top:10px;width:100%", disabled: !cmd.command || !ready, onclick: async () => {
      try { await navigator.clipboard.writeText(cmd.command); status.textContent = " Copied."; }
      catch { status.textContent = " Select the command above and copy it."; }
    } }, "Copy command"), status,
    h("p", { class: "muted" }, cmd.note,
      file.cloud ? " This workbook is on OneDrive or SharePoint: sync it to this computer first." : ""));
}
