"""Full-fidelity workbook snapshot for golden tests (fieldbook phase 1).

Captures everything a format pack controls: sheet order, every valued or
styled cell's value and full style (font incl. underline/strike/vertAlign,
fill incl. bgColor, border incl. per-side color, alignment incl.
wrap/indent/shrink/rotation, cell protection locked+hidden), merges, column
widths, hidden columns, row heights, freeze panes, sheet visibility state, sheet protection
(as a dict of its settings), data validations, conditional formats (rule
type/operator/formula/priority/stopIfTrue plus a dxf summary of
font/fill/numFmt), and workbook-level defined names -- as plain JSON, so an
engine change that alters any of it for a pack that did not opt in fails
loudly.

Reads cells from ``ws._cells`` rather than ``ws.iter_rows()`` so taking a
snapshot never mutates the workbook (``iter_rows()`` backfills every cell in
the sheet's bounding rectangle with blank ``Cell`` objects as a side effect).
"""
from __future__ import annotations

import json


def _color(c):
    if c is None:
        return None
    if c.type == "rgb":
        return c.rgb
    return f"{c.type}:{c.value}"


def _cell(c):
    f, fl, b, a, p = c.font, c.fill, c.border, c.alignment, c.protection
    v = c.value
    return {
        "v": v if v is None or isinstance(v, (int, float, str, bool)) else str(v),
        "font": [f.name, f.sz, bool(f.b), bool(f.i), _color(f.color), f.u, bool(f.strike), f.vertAlign],
        "fill": [fl.fill_type, _color(fl.fgColor), _color(fl.bgColor)] if fl.fill_type else None,
        "border": {side: [s.style, _color(s.color)]
                   for side in ("left", "right", "top", "bottom")
                   for s in (getattr(b, side),)
                   if s is not None and s.style},
        "nf": c.number_format,
        "align": [a.horizontal, a.vertical, a.wrapText, a.indent, a.shrinkToFit, a.textRotation],
        "locked": p.locked,
        "hidden": p.hidden,
    }


def _dxf(d):
    if d is None:
        return None
    font = [bool(d.font.b), bool(d.font.i), _color(d.font.color)] if d.font else None
    fill = [_color(d.fill.fgColor), _color(d.fill.bgColor)] if d.fill else None
    num_fmt = d.numFmt.formatCode if d.numFmt else None
    return {"font": font, "fill": fill, "numFmt": num_fmt}


def _conditional(ws):
    entries = []
    for cf in ws.conditional_formatting:
        rules = [[r.type, r.operator, list(r.formula or []), r.priority, r.stopIfTrue, _dxf(r.dxf)]
                 for r in cf.rules]
        entries.append([str(cf.sqref), rules])
    # Sort by JSON text rather than Python comparison: entries contain dicts
    # (the dxf summaries), which have no natural ordering, so a plain
    # `sorted()` can raise on a tie in the leading fields.
    return sorted(entries, key=lambda e: json.dumps(e, sort_keys=True, default=str))


def _protection(p):
    return {
        "sheet": bool(p.sheet),
        "password_set": bool(p.password or p.hashValue),
        "formatCells": bool(p.formatCells),
        "formatColumns": bool(p.formatColumns),
        "formatRows": bool(p.formatRows),
        "insertRows": bool(p.insertRows),
        "deleteRows": bool(p.deleteRows),
        "selectLockedCells": bool(p.selectLockedCells),
        "selectUnlockedCells": bool(p.selectUnlockedCells),
    }


def _data_validations(ws):
    return sorted(
        [str(dv.sqref), dv.type, dv.formula1]
        for dv in ws.data_validations.dataValidation
    )


def snapshot(wb) -> dict:
    out = {
        "order": list(wb.sheetnames),
        "sheets": {},
        "defined_names": {name: dn.value for name, dn in sorted(wb.defined_names.items())},
    }
    for ws in wb.worksheets:
        cells = {c.coordinate: _cell(c)
                 for _, c in sorted(ws._cells.items())
                 if c.value is not None or c.has_style}
        out["sheets"][ws.title] = {
            "cells": cells,
            "merges": sorted(str(r) for r in ws.merged_cells.ranges),
            "widths": {k: d.width for k, d in sorted(ws.column_dimensions.items()) if d.width is not None},
            "hidden_columns": sorted(k for k, d in ws.column_dimensions.items() if d.hidden),
            "row_heights": {r: d.height for r, d in sorted(ws.row_dimensions.items()) if d.height is not None},
            "conditional": _conditional(ws),
            "protected": bool(ws.protection.sheet),
            "protection": _protection(ws.protection),
            "data_validations": _data_validations(ws),
            "freeze_panes": ws.freeze_panes,
            "sheet_state": ws.sheet_state,
        }
    return out
