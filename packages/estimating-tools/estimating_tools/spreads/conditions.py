"""apply_conditions — the scope-split/acceptance post-pass over a built
Spread (EP-6, spec 2026-08-07-quote-scope-split-design.md).

Additive and in-place: ``apply_conditions`` mutates the ``build_spread``
result it is given and returns that same Spread; an empty conditions list
returns it untouched. A scope group's comparable basis = tagged items ∪
fold targets — the smallest item set whose total means the same thing for
every vendor. Groups whose bases intersect (transitively) are union-merged
into one: scopes sharing a pricing vehicle cannot be compared separately.
Per-item best is suppressed on basis rows (their competition is the group
subtotal).

``obtainable_best_mix`` is deliberately a simple candidate comparison, not
a partition optimizer: flag-False vendors compete only as whole-package
awards against the eligible-vendor item/group mix.

Heuristics warn, never normalize."""
from __future__ import annotations

from estimating_tools.spreads.model import ScopeGroup, Spread


def _row_key(row) -> tuple[str, str]:
    return ((row.schedule_name or "").strip().casefold(),
            row.item_number.strip().casefold())


def _item_key(d: dict) -> tuple[str, str]:
    return ((d.get("schedule") or "").strip().casefold(),
            (d.get("item_number") or "").strip().casefold())


def _match_conditions(spread: Spread, conditions) -> dict:
    """vendor_id -> QuoteConditionRecord (bm_vendor_id first, else name)."""
    by_id = {v["vendor_id"]: v for v in spread.vendors}
    by_name = {v["display_name"].strip().casefold(): v["vendor_id"]
               for v in spread.vendors}
    out = {}
    for rec in conditions:
        vid = rec.vendor.get("bm_vendor_id")
        if vid not in by_id:
            vid = by_name.get(rec.vendor["org_name"].strip().casefold())
        if vid is not None:
            out[vid] = rec
    return out


def _covered(row, vid, cond, row_by_key) -> bool:
    """Vendor covers the row: an included bid cell, or their tags fold the
    row's scope into a row where they have one."""
    c = row.cells.get(vid)
    if c is not None and c.status == "bid" and c.extended_amount is not None:
        return True
    if cond is None:
        return False
    rk = _row_key(row)
    for tag in cond.scope_tags:
        if tag.get("treatment") != "folded":
            continue
        if rk not in {_item_key(i) for i in tag.get("items", [])}:
            continue
        target = row_by_key.get(_item_key(tag["folded_into"]))
        tc = target.cells.get(vid) if target is not None else None
        if tc is not None and tc.status == "bid" and tc.extended_amount is not None:
            return True
    return False


def apply_conditions(spread: Spread, conditions) -> Spread:
    if not conditions:
        return spread
    cond_by_vid = _match_conditions(spread, conditions)
    row_by_key = {_row_key(r): r for r in spread.rows}

    # --- scope groups -----------------------------------------------------
    group_defs: dict[str, dict] = {}
    for vid, rec in cond_by_vid.items():
        for tag in rec.scope_tags:
            g = group_defs.setdefault(tag["group"].strip().casefold(),
                                      {"name": tag["group"].strip(), "keys": set()})
            g["keys"].update(_item_key(i) for i in tag.get("items", []))
            if tag.get("folded_into"):
                g["keys"].add(_item_key(tag["folded_into"]))

    # resolve each group's keys against the package; a group with nothing
    # resolvable is not built — that failure must be loud, not silent
    resolved: list[dict] = []
    for gkey, gdef in sorted(group_defs.items()):
        keys = {k for k in gdef["keys"] if k in row_by_key}
        unresolved = sorted(k for k in gdef["keys"] if k not in row_by_key)
        if not keys:
            spread.condition_warnings.append(
                {"kind": "unresolved_group", "group": gdef["name"],
                 "keys": [f"{s}::{n}" for s, n in unresolved]})
            continue
        resolved.append({"names": [gdef["name"]], "keys": keys,
                         "unresolved": unresolved})

    # union-merge groups whose resolved bases intersect (transitively):
    # a shared pricing row means their subtotals are not independently
    # comparable — summing both would double-count the shared row
    merged: list[dict] = []
    for g in resolved:
        overlapping = [m for m in merged if m["keys"] & g["keys"]]
        for m in overlapping:
            merged.remove(m)
            g = {"names": sorted(set(m["names"]) | set(g["names"])),
                 "keys": m["keys"] | g["keys"],
                 "unresolved": sorted(set(m["unresolved"])
                                      | set(g["unresolved"]))}
        merged.append(g)

    basis_ids_all: set[int] = set()
    for gdef in sorted(merged, key=lambda m: m["names"]):
        basis_rows = [row_by_key[k] for k in sorted(gdef["keys"])]
        group = ScopeGroup(name=" + ".join(gdef["names"]),
                           basis_row_ids=[r.work_package_item_id
                                          for r in basis_rows])
        if len(gdef["names"]) > 1:
            group.warnings.append(
                f"groups {', '.join(gdef['names'])} share pricing items "
                "and were merged for comparison")
        for s, n in gdef["unresolved"]:
            group.warnings.append(
                f"unresolved item key {s}::{n} — not in this package")
        basis_ids_all.update(group.basis_row_ids)
        for v in spread.vendors:
            vid = v["vendor_id"]
            cond = cond_by_vid.get(vid)
            if all(_covered(r, vid, cond, row_by_key) for r in basis_rows):
                subtotal = sum(
                    r.cells[vid].extended_amount for r in basis_rows
                    if vid in r.cells and r.cells[vid].status == "bid"
                    and r.cells[vid].extended_amount is not None)
                group.subtotals[vid] = subtotal
            else:
                group.subtotals[vid] = None
        priced = {vid: s for vid, s in group.subtotals.items() if s is not None}
        if priced:
            # ties break on lowest vendor_id, same as the obtainable-single
            # min over (total, vendor_id, ...) tuples
            group.best_vendor_id = min(priced.items(),
                                       key=lambda kv: (kv[1], kv[0]))[0]
        spread.scope_groups.append(group)
        for r in basis_rows:
            r.best_vendor_id = r.best_unit_price = r.best_extended = None
            for c in r.cells.values():
                c.not_comparable = True

    # --- best-of-breed recompute: item winners off-basis + group winners --
    bob = sum(r.best_extended for r in spread.rows
              if r.work_package_item_id not in basis_ids_all
              and r.best_extended is not None)
    winners: set[int] = {r.best_vendor_id for r in spread.rows
                         if r.work_package_item_id not in basis_ids_all
                         and r.best_vendor_id is not None}
    for g in spread.scope_groups:
        if g.best_vendor_id is not None:
            bob += g.subtotals[g.best_vendor_id]
            winners.add(g.best_vendor_id)
    spread.best_of_breed_total = bob

    def _flag(vid):
        rec = cond_by_vid.get(vid)
        return rec.separate_acceptance_permitted if rec else None

    spread.best_of_breed_annotations = [
        {"vendor_id": vid,
         "display_name": next(v["display_name"] for v in spread.vendors
                              if v["vendor_id"] == vid)}
        for vid in sorted(winners) if _flag(vid) is False]
    spread.best_of_breed_suppressed = bool(winners) and all(
        _flag(vid) is False for vid in winners)

    # --- obtainable single vendor ----------------------------------------
    totals = {vt.vendor_id: vt for vt in spread.vendor_totals}
    full = []
    for v in spread.vendors:
        vid = v["vendor_id"]
        cond = cond_by_vid.get(vid)
        if all(_covered(r, vid, cond, row_by_key) for r in spread.rows):
            full.append((totals[vid].total, vid, v["display_name"]))
    if full:
        total, vid, name = min(full)
        spread.obtainable_single_vendor = {
            "vendor_id": vid, "display_name": name, "total": total}

    # --- obtainable best mix (two-candidate, see module docstring) --------
    candidates: list[float] = []
    mix = 0.0
    complete = True
    incomplete_reason = ""
    for r in spread.rows:
        if r.work_package_item_id in basis_ids_all:
            continue
        priced_cells = [c for c in r.cells.values()
                        if c.status == "bid" and c.unit_price is not None]
        eligible = [c for c in priced_cells
                    if _flag(c.vendor_id) is not False]
        if not eligible or r.quantity is None:
            complete = False
            incomplete_reason = ("flags" if priced_cells
                                 and r.quantity is not None else "coverage")
            break
        mix += min(c.unit_price for c in eligible) * r.quantity
    if complete:
        for g in spread.scope_groups:
            priced_subs = {vid: s for vid, s in g.subtotals.items()
                           if s is not None}
            eligible = {vid: s for vid, s in priced_subs.items()
                        if _flag(vid) is not False}
            if not eligible:
                complete = False
                incomplete_reason = "flags" if priced_subs else "coverage"
                break
            mix += min(eligible.values())
    if complete:
        candidates.append(mix)
    for total, vid, _name in full:
        if _flag(vid) is False:
            candidates.append(total)
    if candidates:
        spread.obtainable_best_mix = min(candidates)
    else:
        spread.obtainable_best_mix_reason = incomplete_reason or "coverage"

    # --- heuristics -------------------------------------------------------
    tagged_keys_by_vid: dict[int, set] = {}
    for vid, rec in cond_by_vid.items():
        keys = set()
        for tag in rec.scope_tags:
            keys.update(_item_key(i) for i in tag.get("items", []))
            if tag.get("folded_into"):
                keys.add(_item_key(tag["folded_into"]))
        tagged_keys_by_vid[vid] = keys
    for r in spread.rows:
        bid_vids = [c.vendor_id for c in r.cells.values() if c.status == "bid"]
        nobid_vids = [c.vendor_id for c in r.cells.values()
                      if c.status == "no_bid"]
        untagged = [vid for vid in nobid_vids
                    if _row_key(r) not in tagged_keys_by_vid.get(vid, set())]
        if bid_vids and untagged:
            spread.condition_warnings.append(
                {"kind": "possible_scope_fold",
                 "work_package_item_id": r.work_package_item_id,
                 "vendors": sorted(untagged)})
    for vid in sorted(winners):
        if _flag(vid) is None:
            spread.condition_warnings.append(
                {"kind": "unknown_acceptance", "vendor_id": vid})
    return spread
