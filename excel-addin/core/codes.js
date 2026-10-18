/** The org code list, as the Codes table holds it (code, description, listed 1/0). */
import { cellText } from "./refs.js";

export function codeList({ code, descr, listed }) {
  const out = [];
  for (let i = 0; i < code.length; i += 1) {
    const c = cellText(code[i]?.[0]).trim();
    if (!c) continue;
    out.push({ code: c, descr: cellText(descr[i]?.[0]), listed: Number(listed[i]?.[0]) === 1 });
  }
  return out;
}

/** Listed codes whose code or description contains `query`, case-insensitively. */
export function searchCodes(list, query) {
  const q = String(query || "").trim().toLowerCase();
  return list.filter((c) => c.listed && (!q || c.code.toLowerCase().includes(q) || c.descr.toLowerCase().includes(q)));
}

export function isListed(list, code) {
  return list.some((c) => c.listed && c.code === String(code).trim());
}
