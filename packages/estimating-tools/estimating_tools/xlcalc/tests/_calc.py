"""Evaluate small in-memory books for the xlcalc tests."""
from __future__ import annotations

from openpyxl import Workbook

from estimating_tools.xlcalc.book import Book
from estimating_tools.xlcalc.evaluate import evaluate


def results(cells: dict, sheets: dict | None = None) -> dict:
    """Evaluate a book whose first sheet (``Sheet``) holds ``cells``
    (``{"A1": value or "=formula"}``) and whose other sheets are
    ``sheets`` (``{title: cells}``). Returns ``{"Sheet!A1": result}``."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet"
    for ref, v in cells.items():
        ws[ref] = v
    for title, more in (sheets or {}).items():
        other = wb.create_sheet(title)
        for ref, v in more.items():
            other[ref] = v
    out = {}
    for (sheet, row, col), v in evaluate(Book.from_workbook(wb)).items():
        out[f"{sheet}!{wb[sheet].cell(row, col).coordinate}"] = v
    return out


def calc(formula: str, **cells):
    """The value of ``formula`` placed in Z99, over ``cells`` (``A1=3``)."""
    return results({**cells, "Z99": formula})["Sheet!Z99"]
