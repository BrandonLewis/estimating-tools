/**
 * Which brand the pane wears. Order: the workbook's stamp, then the
 * deployment's brand.json, then the generic brand. A workbook brand may
 * restyle the pane's interior (name, colours) and nothing else: no links,
 * no icons. Those come from the deployment, which the manifest pins.
 */
export const TOKENS = ["accent", "on_accent", "surface", "text", "muted", "line"];
const HEX = /^#[0-9A-Fa-f]{6}$/;

function overlayColors(base, over) {
  const out = { light: { ...base.light }, dark: { ...base.dark } };
  for (const mode of ["light", "dark"]) {
    for (const [k, v] of Object.entries(over?.[mode] || {})) {
      if (TOKENS.includes(k) && HEX.test(v)) out[mode][k] = v;
    }
  }
  return out;
}

export function resolveBrand({ generic, deployment = null, workbook = null }) {
  let b = { ...generic, colors: overlayColors(generic.colors, {}) };
  if (deployment) b = { ...b, ...deployment, colors: overlayColors(b.colors, deployment.colors) };
  if (workbook) {
    b = { ...b, colors: overlayColors(b.colors, workbook.colors) };
    if (typeof workbook.name === "string" && workbook.name.trim()) b.name = workbook.name.trim();
  }
  return b;
}

export function cssVars(brand, dark) {
  const p = brand.colors[dark ? "dark" : "light"];
  return Object.fromEntries(TOKENS.map((t) => [`--${t.replace("_", "-")}`, p[t]]));
}

/**
 * brand.json for a deployment, relative to /excel/addons/navigator/<version>/panes/taskpane.html:
 * three levels up is /excel/addons/, where the generic brand and each client's <slug>/ folder live.
 */
export function brandPath(slug) {
  return /^[a-z0-9][a-z0-9-]{0,62}$/.test(slug || "") ? `../../../${slug}/brand.json` : "../../../brand.json";
}
