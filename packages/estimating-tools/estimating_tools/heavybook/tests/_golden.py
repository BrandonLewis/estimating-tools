"""Every value of a HeavyBook workbook keyed by row identity, so two builds
that lay rows out differently -- the code build and the template build --
compare cell for cell (``fixtures/golden/values.json``, captured from the
code build in step 4 before its writers retired).

A row's identity is its kind and id tags (``KIND:id``; a marker by its
owner, an element quantity by element and key, a share by activity, item
and element), ``TEXT:<first text>`` for a row with no kind tag, ``@<row>``
above a sheet's first data row and on the sheets laid out by address
(Rates, the calendar); a repeated identity gets ``#2``, ``#3`` in order.
Values are as cached (``data_only``): numbers as floats, dates as Excel
serials, blank and "" alike."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.datetime import to_excel

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "values.json"
#: tab -> (first data row, kind column, id column); None: by address.
SHEETS = {"Cost Report": (5, "W", "X"), "Crews": (5, "K", "L"), "Bid Form": (13, "J", "K"),
          "Recap": (5, "O", "P"), "Schedule": (5, "G", "H"), "Flat": (5, "J", "K"),
          "Checks": (5, "J", "K"), "Allocation": (2, "O", "P"), "Rates": None, "_cal": None}
#: Hidden columns where the code build wrote 0 for a missing number and the
#: template leaves the cell blank (Schedule J: an activity's duration_days).
BLANK_IS_ZERO = {("Schedule", "J")}
#: (tab, row kind, column) the code build wrote and the template build does
#: not, on purpose: an element quantity's parent tag (``Z``), where the code
#: build stored the item it pays -- the contract's identity table gives
#: ELEMENT_QTY no parent, and nothing reads it (step 4, Task 25).
NOT_KEPT = {("Cost Report", "ELEMENT_QTY", "Z")}


def _plain(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return float(to_excel(v))
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    return float(v)


def _identity(ws, tab, r, spec):
    first, kind_col, id_col = spec
    if r < first:
        return f"@{r}"
    kind = ws[f"{kind_col}{r}"].value
    if not kind:
        text = next((ws.cell(r, c).value for c in range(1, 4)
                     if isinstance(ws.cell(r, c).value, str) and ws.cell(r, c).value), None)
        return f"TEXT:{text}" if text else None
    ident = ws[f"{id_col}{r}"].value
    if tab == "Cost Report" and kind in ("STEPS", "START", "END"):
        ident = ws[f"Z{r}"].value
    elif tab == "Cost Report" and kind == "ELEMENT_QTY":
        ident = f"{ident}:{ws[f'AD{r}'].value}"
    elif tab == "Crews" and kind in ("NOTE", "CREW_END"):
        ident = ws[f"N{r}"].value
    if isinstance(ident, float) and ident.is_integer():
        ident = int(ident)
    return f"{kind}:{'' if ident is None else ident}"


def identities(path, row_ids=None) -> dict:
    """``{tab: {identity: {column: value}}}`` for the book at ``path``;
    ``row_ids`` (``{tab: {row: identity}}``) names rows a sheet's tags do not
    (the code build's Checks and ``_shares`` rows)."""
    wb = load_workbook(path, data_only=True)
    out = {}
    for tab, spec in SHEETS.items():
        source = "_shares" if tab == "Allocation" and "_shares" in wb.sheetnames else tab
        if source not in wb.sheetnames:
            continue
        ws, sheet, seen = wb[source], {}, {}
        given = (row_ids or {}).get(tab, {})
        for r in range(1, ws.max_row + 1):
            ident = given.get(r) or (f"@{r}" if spec is None else _identity(ws, tab, r, spec))
            if ident is None:
                continue
            seen[ident] = seen.get(ident, 0) + 1
            if seen[ident] > 1:
                ident = f"{ident}#{seen[ident]}"
            cells = {c.column_letter: _plain(c.value) for c in ws[r] if c.value not in (None, "")}
            if cells:
                sheet[ident] = cells
        out[tab] = sheet
    return out


def same(a, b) -> bool:
    if a in (None, "") and b in (None, ""):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def _kind(ident):
    return ident.split(":", 1)[0]


def output_columns(golden: dict) -> dict:
    """``{(tab, row kind): columns}`` the code build wrote a value in, in any
    row of that kind (an ``@<row>`` row is a kind of its own). The golden
    records only cells that held a value, so these are the code build's
    output columns, and a recorded row's cell in one of them with no
    recorded value was blank there."""
    out = {}
    for tab, rows in golden.items():
        for ident, cells in rows.items():
            out.setdefault((tab, _kind(ident)), set()).update(cells)
    return out


def differences(golden: dict, book: dict) -> list:
    """Every golden cell the book does not hold the same value in. A golden
    row also expects blank in each of its kind's output columns it records
    no value for (so a price on an excluded item is a difference); columns
    the code build never wrote for that kind (the template's helper
    columns) are not compared."""
    out = []
    columns = output_columns(golden)
    for tab, rows in golden.items():
        for ident, recorded in rows.items():
            have = book.get(tab, {}).get(ident, {})
            kind = _kind(ident)
            cells = dict.fromkeys(sorted(columns[(tab, kind)]))
            cells.update(recorded)
            for col, want in cells.items():
                if (tab, kind, col) in NOT_KEPT:
                    continue
                got = have.get(col)
                if (tab, col) in BLANK_IS_ZERO and want == 0.0 and got in (None, ""):
                    continue
                if not same(want, got):
                    out.append(f"{tab} {ident} {col}: golden {want!r}, book {got!r}")
    return out


def load() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))
