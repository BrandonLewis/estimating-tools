"""Helpers every HeavyCivil sheet writer shares."""
from __future__ import annotations

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils import column_index_from_string

from estimating_tools.estimate_spec.build import StyleFactory
from estimating_tools.heavycivil import columns as C
from estimating_tools.heavycivil.formulas import Formula
from estimating_tools.heavycivil.layout import HEADER_ROW


def export_multiplier(wb, activity):
    """The activity's count times every ancestor's, as exported (the Cost
    Report's live multiplier AA starts equal to it)."""
    m, node = 1, activity
    while node is not None:
        m *= node.count
        node = wb.activity(node.parent_id) if node.parent_id is not None else None
    return m


def factory(style):
    return StyleFactory(style.tokens)


def set_value(cell, value):
    """Store ``value`` in ``cell``. Only a :class:`~formulas.Formula` is a
    formula: openpyxl makes any string starting with "=" one (and "#N/A"
    and the like error cells), so every other string -- payload text, which
    may start with "=" -- is pinned to text. Control characters XML cannot
    carry are dropped from text."""
    if isinstance(value, Formula):
        cell.value = value
    elif isinstance(value, str):
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)
        cell.data_type = "s"
    else:
        cell.value = value


def put(ws, sf, addr, value, style_name=None):
    """Write one cell (see :func:`set_value`): a Decimal stays exact (openpyxl
    writes it as a number), None writes nothing but may still style the
    cell."""
    cell = ws[addr]
    if value is not None:
        set_value(cell, value)
    if style_name:
        sf.apply(cell, style_name)
    return cell


def setup_sheet(ws, sf, style, sheet_key, *, title, subtitle, header_row=HEADER_ROW):
    conf = style.sheets[sheet_key]
    ws.sheet_properties.tabColor = conf.get("tab_color")
    put(ws, sf, "A1", title, "title")
    put(ws, sf, "A2", subtitle, "subtitle")
    for col in C.SHEETS[sheet_key]:
        merged = style.column(sheet_key, col.key)
        put(ws, sf, f"{col.letter}{header_row}", merged["heading"], "head")
        dim = ws.column_dimensions[col.letter]
        if merged.get("width"):
            dim.width = merged["width"]
        if col.hidden or merged.get("show") is False:
            dim.hidden = True
    apply_freeze_and_print(ws, conf)


def apply_freeze_and_print(ws, conf):
    """A sheet's ``freeze`` and ``print`` style settings (title rows only if set)."""
    if conf.get("freeze"):
        ws.freeze_panes = conf["freeze"]
    printing = conf.get("print") or {}
    ws.page_setup.orientation = printing.get("orientation", "landscape")
    if printing.get("fit_width"):
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
    if printing.get("title_rows"):
        ws.print_title_rows = printing["title_rows"]


def last_column_letter(sheet_key):
    return max(C.SHEETS[sheet_key], key=lambda c: column_index_from_string(c.letter)).letter
