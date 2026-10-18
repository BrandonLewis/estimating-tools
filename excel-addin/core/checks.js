/** The Checks table, as Excel evaluated it. The add-in never recomputes a check. */
import { cellText } from "./refs.js";

export const PASS = "✓";
export const FAIL = "✗";

export function checksFromTable({ ruleNo, rule, item, status }) {
  const rows = [];
  for (let i = 0; i < status.length; i += 1) {
    const s = cellText(status[i]?.[0]).trim();
    if (s !== PASS && s !== FAIL) continue;
    rows.push({ ruleNo: cellText(ruleNo[i]?.[0]), rule: cellText(rule[i]?.[0]),
                item: cellText(item[i]?.[0]).trim(), ok: s === PASS });
  }
  const failing = rows.filter((r) => !r.ok);
  const passing = rows.filter((r) => r.ok);
  return { pass: passing.length, fail: failing.length, rows: [...failing, ...passing] };
}

/** Map item number -> count of its failing checks. */
export function failingByItem(checks) {
  const m = new Map();
  for (const r of checks.rows) if (!r.ok && r.item) m.set(r.item, (m.get(r.item) || 0) + 1);
  return m;
}
