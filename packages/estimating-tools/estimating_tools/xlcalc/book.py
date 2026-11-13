"""The cells the evaluator reads: formulas, constants, sheet heights and
defined names, loaded from a saved book in formula mode (openpyxl expands
shared formulas into each cell)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.datetime import to_excel

from estimating_tools.xlcalc.parse import FormulaError, Ref, ref_or_name
from estimating_tools.xlcalc.values import ERRORS


@dataclass
class Book:
    """``formulas`` and ``constants`` map ``(sheet, row, col)`` to a formula
    (its text, or None for an array or data-table formula, which is not
    evaluated) and to a constant value. ``names`` maps a defined name, upper
    case, to its ``Ref`` (``(sheet, NAME)`` for a sheet-scoped one); names
    that are not plain references are left out."""
    sheets: list = field(default_factory=list)
    formulas: dict = field(default_factory=dict)
    constants: dict = field(default_factory=dict)
    heights: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)
    hidden: set = field(default_factory=set)        # titles of hidden sheets

    @classmethod
    def load(cls, path) -> "Book":
        # A file object, not the name: openpyxl refuses a name whose
        # extension is not .xlsx, and builders cache temporary copies.
        with open(Path(path), "rb") as fh:
            wb = load_workbook(fh, data_only=False)
            try:
                return cls.from_workbook(wb)
            finally:
                wb.close()

    @classmethod
    def from_workbook(cls, wb) -> "Book":
        book = cls()
        for ws in wb.worksheets:
            title = ws.title
            book.sheets.append(title)
            if ws.sheet_state != "visible":
                book.hidden.add(title)
            book.heights[title] = ws.max_row
            for row in ws.iter_rows():
                for c in row:
                    v = c.value
                    if v is None:
                        continue
                    key = (title, c.row, c.column)
                    if c.data_type == "f":
                        book.formulas[key] = v if isinstance(v, str) else None
                    elif c.data_type == "e":
                        book.constants[key] = ERRORS.get(str(v), ERRORS["#VALUE!"])
                    elif isinstance(v, bool) or isinstance(v, str):
                        book.constants[key] = v
                    elif isinstance(v, (int, float)):
                        book.constants[key] = float(v)
                    elif isinstance(v, (dt.datetime, dt.date, dt.time)):
                        book.constants[key] = float(to_excel(v, epoch=wb.epoch))
            for name, dn in ws.defined_names.items():
                ref = _plain_ref(dn.attr_text)
                if ref is not None:
                    book.names[(title, name.upper())] = ref
        for name, dn in wb.defined_names.items():
            ref = _plain_ref(dn.attr_text)
            if ref is not None:
                book.names[name.upper()] = ref
        return book

    def height(self, sheet: str) -> int:
        return max(self.heights.get(sheet, 1), 1)


def _plain_ref(text):
    try:
        node = ref_or_name(text or "")
    except FormulaError:
        return None
    return node if isinstance(node, Ref) and node.sheet is not None else None
