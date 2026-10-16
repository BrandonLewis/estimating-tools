"""Adapt the simpler per-bid-item Quote model into a leveled Spread by reshaping it
into build_spread's inputs. Pure: stdlib + build_spread only (no MCP/Django).

A per-item quote is a lump `amount` for one bid item from one vendor (no unit_price,
no quantity, no line items). We synthesize unit_price = amount / full_quantity so the
existing leveling core ranks on the implied per-unit rate (equivalent to ranking on
amount, since quantity is constant per item). When full_quantity is 0/None we fall
back to unit_price = amount, quantity = 1.
"""
from __future__ import annotations

from estimating_tools.spreads.level import build_spread


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_key(quote):
    """Sort key to pick the surviving quote for a (bid_item, vendor): most recent
    received_date first (None sorts as oldest), then lowest amount."""
    date = quote.get("received_date") or ""
    amount = _num(quote.get("amount"))
    # higher date string sorts later; we want most-recent to WIN, so sort ascending
    # and take the last. For the amount tie-break (lower wins on equal date), a lower
    # amount should also WIN, i.e. sort later -> negate.
    return (date, -(amount if amount is not None else 0.0))


def build_item_spread(bid_items, quotes):
    """Reshape per-item quotes into build_spread inputs and delegate. Returns a Spread."""
    quotes = [q for q in quotes if _num(q.get("amount")) is not None]
    bid_by_id = {b["id"]: b for b in bid_items}

    # 1) dedupe to one quote per (bid_item_id, vendor_id): most recent, then lowest amount.
    best_by_pair: dict[tuple, dict] = {}
    for q in quotes:
        pair = (q["bid_item_id"], q["vendor_id"])
        cur = best_by_pair.get(pair)
        if cur is None or _dedupe_key(q) > _dedupe_key(cur):
            best_by_pair[pair] = q

    # 2) rows = quoted bid items, in bid_items order; vendors = distinct, first-seen.
    quoted_ids = {pair[0] for pair in best_by_pair}   # precompute once (linear filter below)
    quoted_item_ids = [b["id"] for b in bid_items if b["id"] in quoted_ids]

    items = []
    for item_id in quoted_item_ids:
        b = bid_by_id[item_id]
        items.append({
            "id": item_id,
            "project_bid_item_id": item_id,
            "item_code": b.get("item_code"),
            "item_number": b.get("item_number", ""),
            "schedule_name": b.get("schedule_name"),
        })

    vendors_seen = []
    vendor_meta: dict[int, dict] = {}
    for q in quotes:
        vid = q["vendor_id"]
        if vid not in vendor_meta:
            vendors_seen.append(vid)
            vendor_meta[vid] = {"id": vid, "vendor_id": vid,
                                "vendor_display_name": q.get("vendor") or "",
                                "is_dbe": False, "status": q.get("status", "")}
        # DBE is a vendor-level fact: any of the vendor's quote rows carrying
        # is_dbe marks the vendor (absence tolerated -> False).
        if q.get("is_dbe"):
            vendor_meta[vid]["is_dbe"] = True
    quotes_cols = [vendor_meta[vid] for vid in vendors_seen]

    # 3) synthetic lines per vendor: unit_price = amount/full_qty (fallback amount, qty 1).
    lines_by_quote: dict[int, list] = {vid: [] for vid in vendors_seen}
    for (item_id, vid), q in best_by_pair.items():
        amount = _num(q.get("amount"))
        full_qty = _num(bid_by_id.get(item_id, {}).get("quantity"))
        if full_qty and full_qty != 0 and amount is not None:
            unit_price, qty = amount / full_qty, full_qty
        else:
            unit_price, qty = amount, 1.0
        lines_by_quote[vid].append({
            "id": q["id"],
            "work_package_item_id": item_id,
            "unit_price": unit_price,
            "quantity": qty,
            "amount": amount,
            "is_included": True,
        })

    return build_spread(items, bid_items, quotes_cols, lines_by_quote)
