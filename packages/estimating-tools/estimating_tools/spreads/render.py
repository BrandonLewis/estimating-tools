"""Render a Spread as a deterministic markdown table — the prototype "live artifact"
renderer (pure result -> str; stable column order; fixed number formatting)."""
from __future__ import annotations

from estimating_tools.artifacts import format_money, format_qty, md_table
from estimating_tools.spreads.model import Spread


def _row_label(row) -> str:
    return f"{row.item_number} ({row.schedule_name})" if row.schedule_name else row.item_number


def _vendor_by_id(spread: Spread):
    return {v["vendor_id"]: v for v in spread.vendors}


def render_spread(spread: Spread) -> str:
    vendors = spread.vendors
    best_set = {(r.work_package_item_id, r.best_vendor_id) for r in spread.rows}

    # header: append "*" to a vendor's name when it is DBE (at-a-glance scanning).
    # The per-item best cell is bolded in the body rows below, not marked here.
    headers = ["Item", "Description", "Unit", "Qty"]
    for v in vendors:
        headers.append(v["display_name"] + ("*" if v["is_dbe"] else ""))

    rows = []
    for row in spread.rows:
        cols = [_row_label(row), row.description, row.unit, format_qty(row.quantity)]
        for v in vendors:
            c = row.cells.get(v["vendor_id"])
            if c is None or c.status == "no_bid":
                cols.append("no bid")
            elif c.status == "excluded":
                cols.append("excl")
            else:
                price = format_money(c.unit_price)
                if (row.work_package_item_id, v["vendor_id"]) in best_set:
                    price = f"**{price}**"
                if c.is_partial:
                    price += "~"
                if c.not_comparable:
                    price += " n/c"
                cols.append(price)
        rows.append(cols)

    totals_by_v = {vt.vendor_id: vt for vt in spread.vendor_totals}
    total_cols = ["**Total**", "", "", ""]
    for v in vendors:
        vt = totals_by_v.get(v["vendor_id"])
        total_cols.append(f"{format_money(vt.total)} ({vt.items_bid}/{vt.items_total})" if vt else "")
    rows.append(total_cols)

    out = md_table(headers, rows) + "\n"

    vmap = _vendor_by_id(spread)
    rmap = {r.work_package_item_id: r for r in spread.rows}

    conditioned = bool(spread.scope_groups or spread.obtainable_single_vendor
                       or spread.best_of_breed_annotations
                       or spread.condition_warnings
                       or spread.obtainable_best_mix is not None
                       or spread.obtainable_best_mix_reason)
    if not conditioned:
        out += f"\nBest-of-breed total: {format_money(spread.best_of_breed_total)}\n"
    else:
        for g in spread.scope_groups:
            basis = ", ".join(_row_label(rmap[rid]) for rid in g.basis_row_ids
                              if rid in rmap)
            out += (f"\nScope group: {g.name} (items {basis}) — "
                    "subtotal per vendor (all-in for this scope):\n")
            for v in vendors:
                name = v["display_name"] + ("*" if v["is_dbe"] else "")
                s = g.subtotals.get(v["vendor_id"])
                if s is None:
                    out += f"- {name}: no full-scope coverage\n"
                else:
                    mark = " ← best" if v["vendor_id"] == g.best_vendor_id else ""
                    out += f"- {name}: {format_money(s)}{mark}\n"
            for w in g.warnings:
                out += f"- warning: {w}\n"

        out += "\n"
        osv = spread.obtainable_single_vendor
        if osv is not None:
            name = osv["display_name"]
            if vmap.get(osv["vendor_id"], {}).get("is_dbe"):
                name += "*"
            out += (f"Obtainable single-vendor total: "
                    f"{format_money(osv['total'])} ({name})\n")
        else:
            out += ("Obtainable single-vendor total: none "
                    "(no vendor covers the full package)\n")
        if spread.obtainable_best_mix is not None:
            out += f"Obtainable best mix: {format_money(spread.obtainable_best_mix)}\n"
        elif spread.obtainable_best_mix_reason == "coverage":
            out += "Obtainable best mix: none — coverage incomplete\n"
        else:
            out += "Obtainable best mix: none respects acceptance flags\n"
        has_winners = (any(r.best_vendor_id is not None for r in spread.rows)
                       or any(g.best_vendor_id is not None
                              for g in spread.scope_groups))
        if spread.best_of_breed_suppressed:
            out += ("Best-of-breed: suppressed "
                    "(every winning vendor forbids separate acceptance)\n")
        elif not has_winners:
            out += "Best-of-breed: no priced winners\n"
        elif spread.best_of_breed_annotations:
            names = ", ".join(a["display_name"]
                              for a in spread.best_of_breed_annotations)
            out += (f"Best-of-breed total: "
                    f"{format_money(spread.best_of_breed_total)} — "
                    f"NOT OBTAINABLE as shown "
                    f"(forbid separate acceptance: {names})\n")
        else:
            out += f"Best-of-breed total: {format_money(spread.best_of_breed_total)}\n"
        for w in spread.condition_warnings:
            if w["kind"] == "possible_scope_fold":
                r = rmap.get(w["work_package_item_id"])
                label = (_row_label(r) if r is not None
                         else str(w["work_package_item_id"]))
                names = ", ".join(
                    vmap.get(vid, {}).get("display_name", str(vid))
                    for vid in w["vendors"])
                out += (f"- possible scope fold: item {label} "
                        f"skipped untagged by {names}\n")
            elif w["kind"] == "unknown_acceptance":
                name = vmap.get(w["vendor_id"], {}).get(
                    "display_name", str(w["vendor_id"]))
                out += (f"- acceptance unverified for {name} — "
                        "mix numbers assume permission\n")
            elif w["kind"] == "unresolved_group":
                keys = ", ".join(w.get("keys", []))
                out += f"- unresolved group: {w['group']} (keys: {keys})\n"
    if spread.gaps:
        out += "\nGaps:\n"
        for g in spread.gaps:
            v = vmap.get(g["vendor_id"], {})
            r = rmap.get(g["work_package_item_id"])
            label = _row_label(r) if r is not None else str(g["work_package_item_id"])
            note = ""
            if g.get("reason") == "excluded" and r is not None:
                c = r.cells.get(g["vendor_id"])
                if c is not None and c.exclusion_notes:
                    note = f" ({c.exclusion_notes})"
            reason = "excluded" if g.get("reason") == "excluded" else "no bid"
            out += f"- {v.get('display_name', g['vendor_id'])}: item {label} — {reason}{note}\n"
    if spread.outliers:
        out += "\nOutliers:\n"
        for o in spread.outliers:
            v = vmap.get(o["vendor_id"], {})
            r = rmap.get(o["work_package_item_id"])
            label = _row_label(r) if r is not None else str(o["work_package_item_id"])
            out += (f"- {v.get('display_name', o['vendor_id'])}: item {label} — "
                    f"{format_money(o['unit_price'])} vs best {format_money(o['best_unit_price'])}\n")
    return out
