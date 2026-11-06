/**
 * Item rows as the heuristic parser and the fieldbook index read them
 * ("legacy rows": {itemNo, descr, cost, sheetName, totalAddr, isTotal}), their
 * total row, and their conversion into the Items tree the pane renders.
 */

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

/**
 * Legacy rows -> Items tree rows, one level deep. A click opens the item's
 * sheet (`jump`); a double-click, Enter or Space goes to its total (`focus`).
 * A row with no sheet is typed, not a link: no jump. `failing` (item number
 * -> failing check count) is given only for a stamped workbook, and then every
 * row but the total carries a status, as the pane always showed.
 */
export function legacyToTree(rows, failing = null) {
  return rows.map((r) => ({
    key: r.isTotal ? "total" : `item:${r.itemNo}`,
    no: r.itemNo,
    label: r.descr,
    cost: r.cost,
    total: r.isTotal,
    jump: r.sheetName ? { sheet: r.sheetName } : null,
    focus: r.sheetName ? { sheet: r.sheetName, addr: r.totalAddr } : null,
    status: failing && !r.isTotal ? { fails: failing.get(r.itemNo) || 0 } : null,
    children: [],
  }));
}
