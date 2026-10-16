"""The quote-space coverage join — solicited/received/leveled/awarded per
bid item x vendor, plus the zero-coverage gap list.

Inputs are the journal (SolicitationRecords) and plain-dict exports the
quote-coverage skill dumps from BidSheet.ai:

  packages     [{"name", "strategy", "items": [{"schedule", "item_number",
                 "description"}]}]
  quotes       [{"vendor_name", "work_package_name"}] for package-scope
               quotes, or [{"vendor_name", "schedule", "item_number"}] for
               per-item quotes — rows may mix.
  allocations  [{"vendor_name", "schedule", "item_number"}]
  leveled      package names with a current spread (caller-decided; e.g.
               packages with a written spread-<package>.md)

Statuses are DERIVED here, never stored (model.py owns the stored side).
Ladder per cell: planned < solicited < declined < received < leveled <
awarded — later rungs override earlier ones (a declined vendor who quoted
anyway shows received)."""
from __future__ import annotations

from estimating_tools.quotespace.itb import md_cell
from estimating_tools.quotespace.model import SolicitationRecord, current_records

_RANK = {"": 0, "planned": 1, "solicited": 2, "declined": 3, "received": 4,
         "leveled": 5, "awarded": 6}


def item_key(schedule: str, item_number: str) -> str:
    return f"{schedule.strip()}::{item_number.strip()}"


def _bump(cells: dict, vendor: str, status: str) -> None:
    if _RANK[status] > _RANK.get(cells.get(vendor, ""), 0):
        cells[vendor] = status


def build_coverage(records: list[SolicitationRecord], packages: list[dict],
                   quotes: list[dict] = (), allocations: list[dict] = (),
                   leveled: list[str] = ()) -> dict:
    leveled_set = {name.strip().casefold() for name in leveled}
    out_packages = []
    # Vendors join case-insensitively (journal vs BM export spellings);
    # first-seen spelling is the display name in every output.
    vendor_names: dict[str, str] = {}

    def vkey(name: str) -> str:
        key = name.strip().casefold()
        vendor_names.setdefault(key, name.strip())
        return key

    # cells[pkg_name][item_key][vendor_key] = status
    cells: dict[str, dict[str, dict[str, str]]] = {}
    pkg_items: dict[str, list[str]] = {}
    for pkg in packages:
        keys = [item_key(i.get("schedule", ""), i.get("item_number", ""))
                for i in pkg.get("items", [])]
        pkg_items[pkg["name"].strip().casefold()] = keys
        cells[pkg["name"].strip().casefold()] = {k: {} for k in keys}

    # 1. journal: planned / solicited (=sent) / declined
    for rec in current_records(records).values():
        pkey = rec.work_package["name"].strip().casefold()
        if pkey not in cells:
            continue
        status = {"planned": "planned", "sent": "solicited",
                  "declined": "declined"}[rec.status]
        keys = ([item_key(i.get("schedule", ""), i.get("item_number", ""))
                 for i in rec.items] or pkg_items[pkey])
        for k in keys:
            if k in cells[pkey]:
                _bump(cells[pkey][k], vkey(rec.vendor["org_name"]), status)

    # 2. quotes: received (package-scope covers every package item)
    for q in quotes:
        vendor = vkey(q.get("vendor_name", ""))
        if q.get("schedule") is not None and q.get("item_number") is not None:
            k = item_key(q["schedule"], q["item_number"])
            for pkey, items in cells.items():
                if k in items:
                    _bump(items[k], vendor, "received")
        else:
            pkey = (q.get("work_package_name") or "").strip().casefold()
            for k in cells.get(pkey, {}):
                _bump(cells[pkey][k], vendor, "received")

    # 3. leveled: received cells in a leveled package are leveled
    for pkey in cells:
        if pkey in leveled_set:
            for k, vendors in cells[pkey].items():
                for vendor, status in vendors.items():
                    if status == "received":
                        vendors[vendor] = "leveled"

    # 4. allocations: awarded
    for a in allocations:
        k = item_key(a.get("schedule", ""), a.get("item_number", ""))
        for pkey, items in cells.items():
            if k in items:
                _bump(items[k], vkey(a.get("vendor_name", "")), "awarded")

    # assemble output + gaps
    gap_items = []
    for pkg in packages:
        pkey = pkg["name"].strip().casefold()
        items_out = []
        for it in pkg.get("items", []):
            k = item_key(it.get("schedule", ""), it.get("item_number", ""))
            vendor_cells = {vendor_names[vk]: s
                            for vk, s in cells[pkey][k].items()}
            best = max(vendor_cells.values(), key=lambda s: _RANK[s], default="")
            items_out.append({"key": k,
                              "description": it.get("description", ""),
                              "cells": vendor_cells, "best": best})
            if (pkg.get("strategy", "") != "self_perform"
                    and _RANK[best] < _RANK["solicited"]):
                gap_items.append({"key": k, "package": pkg["name"],
                                  "description": it.get("description", "")})
        out_packages.append({"name": pkg["name"],
                             "strategy": pkg.get("strategy", ""),
                             "leveled": pkey in leveled_set,
                             "items": items_out})

    # vendor summary from the journal + quotes (keyed like the cells)
    summary: dict[str, dict] = {}

    def srow(name: str) -> dict:
        key = vkey(name)
        return summary.setdefault(key, {"vendor": vendor_names[key],
                                        "solicited": 0, "received": 0,
                                        "declined": 0})

    for rec in current_records(records).values():
        v = srow(rec.vendor["org_name"])
        if rec.status == "sent":
            v["solicited"] += 1
        elif rec.status == "declined":
            v["declined"] += 1
    for q in quotes:
        srow(q.get("vendor_name", ""))["received"] += 1

    return {"packages": out_packages, "gap_items": gap_items,
            "vendor_summary": sorted(summary.values(),
                                     key=lambda v: v["vendor"].casefold())}


def render_coverage_md(cov: dict) -> str:
    lines = ["# Quote-Space Coverage", ""]
    if cov["gap_items"]:
        lines += ["## Coverage gaps — items with NO vendor solicited", ""]
        for g in cov["gap_items"]:
            lines.append(f"- **{g['key']}** {g['description']} ({g['package']})")
        lines.append("")
    for pkg in cov["packages"]:
        vendors = sorted({v for i in pkg["items"] for v in i["cells"]},
                         key=str.casefold)
        tag = " (leveled)" if pkg["leveled"] else ""
        lines += [f"## {pkg['name']}{tag}", ""]
        if not vendors:
            lines += ["_No vendors solicited._", ""]
            continue
        lines.append("| Item | Description | "
                     + " | ".join(md_cell(v) for v in vendors) + " |")
        lines.append("|---|---|" + "---|" * len(vendors))
        for item in pkg["items"]:
            row = [item["key"], item["description"]]
            row += [item["cells"].get(v, "") for v in vendors]
            lines.append("| " + " | ".join(md_cell(c) for c in row) + " |")
        lines.append("")
    if cov["vendor_summary"]:
        lines += ["## Vendors", "",
                  "| Vendor | Solicited | Received | Declined |", "|---|---|---|---|"]
        for v in cov["vendor_summary"]:
            lines.append(f"| {md_cell(v['vendor'])} | {v['solicited']} "
                         f"| {v['received']} | {v['declined']} |")
        lines.append("")
    return "\n".join(lines)
