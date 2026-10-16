"""Excel formula builders for live-formula calculator workbooks (#202).

Pure string plumbing — no openpyxl, no org data. The two workhorses are the
PERT estimate ``=(low+4*likely+high)/6`` and the override guard
``=IF(override="", shipped, override)`` that lets an estimator flex a shipped
rate on bid day without re-running Python.
"""
from __future__ import annotations

import re
from typing import Union

_ColRef = Union[str, int]

# A sheet name Excel accepts unquoted: starts with a letter/underscore, then
# letters/digits/underscore/period. Anything else (spaces, apostrophes, …)
# must be single-quoted with internal apostrophes doubled.
_SIMPLE_SHEET = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _col_letter(column: _ColRef) -> str:
    if isinstance(column, int):
        from openpyxl.utils import get_column_letter
        return get_column_letter(column)
    return column


def _quote_sheet(sheet: str) -> str:
    if _SIMPLE_SHEET.match(sheet):
        return sheet
    return "'" + sheet.replace("'", "''") + "'"


def cell_ref(sheet: str | None, column: _ColRef, row: int, *,
             abs_col: bool = True, abs_row: bool = True) -> str:
    """An A1 cell reference, absolute by default: ``RATES!$B$4``.

    ``sheet=None`` omits the sheet qualifier; ``column`` may be a letter or a
    1-based index.
    """
    col = _col_letter(column)
    ref = f"{'$' if abs_col else ''}{col}{'$' if abs_row else ''}{row}"
    return f"{_quote_sheet(sheet)}!{ref}" if sheet else ref


def pert(low: str, likely: str, high: str) -> str:
    """PERT expected value ``=(low + 4*likely + high) / 6`` over cell refs."""
    return f"=({low}+4*{likely}+{high})/6"


def override(shipped: str, override_cell: str) -> str:
    """Use ``shipped`` unless an ``override_cell`` value was typed in.

    ``=IF(override="", shipped, override)`` — the override-column primitive
    that moves a shipped rate without editing the shipped cell.
    """
    return f'=IF({override_cell}="",{shipped},{override_cell})'
