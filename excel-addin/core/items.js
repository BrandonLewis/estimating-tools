/** Index rows from a stamped workbook's named columns, and the total row. */
import { cellNumber, cellText, tryParseRef } from "./refs.js";

/** Each argument is a single-column 2-D array, as Excel's range.values/formulas return. */
export function itemsFromTable({ itemNo, descr, cost, link, sheetNames }) {
  const existing = new Set(sheetNames.map((n) => n.toUpperCase()));
  const rows = [];
  for (let i = 0; i < itemNo.length; i += 1) {
    const no = cellText(itemNo[i]?.[0]).trim();
    if (!no) continue;
    const ref = tryParseRef(link[i]?.[0]);
    const ok = ref && existing.has(ref.sheet.toUpperCase());
    rows.push({ itemNo: no, descr: cellText(descr[i]?.[0]), cost: cellNumber(cost[i]?.[0]),
                sheetName: ok ? ref.sheet : "", totalAddr: ok ? ref.addr : "", isTotal: false });
  }
  return rows;
}

export function totalOf(rows) {
  return rows.reduce((t, r) => t + (r.cost ?? 0), 0);
}

/** rows plus a total row. The workbook's own total wins when given; else the sum of the rows. */
export function withTotal(rows, { total, label, sheet = "", addr = "" }) {
  if (!rows.length) return [];
  return [...rows, { itemNo: label, descr: "", cost: typeof total === "number" ? total : totalOf(rows),
                     sheetName: sheet, totalAddr: addr, isTotal: true }];
}

/** Cost as the pane shows it; an em dash when there is no number. */
export function costText(cost) {
  if (cost === null || cost === undefined) return "—";
  return cost.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 });
}
