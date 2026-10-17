"""Helpers for the fieldbook pack's tests: load it, build its example, find rows by tag."""
from __future__ import annotations

import copy
import re

import yaml
from openpyxl.formula.translate import Translator

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp

FIELDBOOK_DIR = fp.ENGINE_DIR / "packs" / "fieldbook"
EXAMPLE = FIELDBOOK_DIR / "examples" / "demo-pipeline.estimate.yaml"
#: Item sheets' hidden tag/helper columns: kind, code, ok-flag, flag.
KIND, CODE, OK, FLAG = "Q", "R", "S", "T"

#: A bare (same-sheet) cell/range reference: not preceded by `!` (a
#: cross-sheet qualifier) or a word/quote character (so it never matches
#: inside a longer token). Matches "$G$1", "L23", etc.
_CELL_REF = re.compile(r"(?<![!'A-Za-z0-9_])(\$?[A-Z]{1,3}\$?)(\d+)")


def fieldbook_pack():
    return fp.load_pack(FIELDBOOK_DIR)


def example_spec() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def build(spec: dict | None = None):
    """Build `spec` (default: the pack's example) with the fieldbook pack."""
    return B.generate(copy.deepcopy(spec or example_spec()), fieldbook_pack())


def rows_of_kind(ws, kind: str) -> list[int]:
    """Row numbers whose hidden kind tag equals `kind`, top to bottom."""
    return [r for r in range(1, ws.max_row + 1) if ws[f"{KIND}{r}"].value == kind]


def task_block(ws, code: str) -> dict:
    """{kind: [rows]} for the task block whose header shows `code`."""
    (head,) = [r for r in rows_of_kind(ws, "TASK") if ws[f"A{r}"].value == code]
    block = {"TASK": [head]}
    r = head + 1
    while ws[f"{KIND}{r}"].value not in ("TASK", None):
        block.setdefault(ws[f"{KIND}{r}"].value, []).append(r)
        r += 1
    return block


def _shift_formula_rows(formula: str, at_row: int, delta: int) -> str:
    """Shift every bare (same-sheet) row reference >= `at_row` by `delta` --
    what Excel does to every OTHER formula on a sheet when a row is
    inserted at `at_row`. A cross-sheet reference (`'Rates'!$A$5`) is never
    touched: `_CELL_REF` refuses to match right after a `!`."""
    def repl(m):
        col, row = m.group(1), int(m.group(2))
        return f"{col}{row + delta if row >= at_row else row}"
    return _CELL_REF.sub(repl, formula)


def simulate_insert_copied_row(ws, at_row: int, copy_from_row: int) -> None:
    """Simulate Excel's "insert copied cells": copy `copy_from_row`'s row
    into a new row at `at_row` (pushing `at_row` and everything below it
    down by one), adjusting every same-sheet formula on the sheet the way
    Excel adjusts them on a real row insert -- openpyxl's `insert_rows`
    moves cell values/styles but never rewrites formula text, so that part
    is done here by hand, the way the Tasks 5-7 reviewer's own check did.

    A range whose last row is `at_row` (e.g. a subtotal's `X{head}:X{end}`,
    where `{end}` sits exactly at `at_row`) grows to include the new row,
    because each endpoint shifts independently by the same "row >= at_row"
    rule Excel applies to every reference.
    """
    max_col = ws.max_column
    # 1. What every cell's formula should read AFTER the insert (computed
    #    from the sheet as it stands now, before anything physically moves).
    adjusted = {}
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=max_col):
        for cell in row:
            v = cell.value
            if isinstance(v, str) and v.startswith("="):
                adjusted[(cell.row, cell.column)] = _shift_formula_rows(v, at_row, 1)
    # 2. The new row's own content: a copy of `copy_from_row`, with every
    #    relative reference shifted by the same delta as the paste (the
    #    row's own self-refs, and its R-column chain ref to the row above
    #    it, move together -- that is what "copy down" means in Excel) and
    #    every absolute reference left untouched -- including a CROSS-SHEET
    #    one (a crew row's VLOOKUP into 'Rates'!$A$5:$H$12, its shift-hours
    #    'Rates'!$B$2). `_shift_formula_rows` is the wrong tool here: its
    #    same-sheet-only guard refuses a reference immediately preceded by
    #    '!', but a `$COL$ROW` reference's own leading '$' sits between the
    #    '!' and the match, so it shifts the SECOND endpoint of a range
    #    (and even a lone absolute cell) anyway -- real damage, not a
    #    same-sheet false negative. `Translator` (what Excel itself does on
    #    copy/paste, and what `_copy_rows` in test_fieldbook_eval.py already
    #    uses for a plain copy) shifts only the relative part of each
    #    reference and leaves every `$`-anchored and cross-sheet reference
    #    exactly as written.
    copied = {}
    for c in range(1, max_col + 1):
        src_cell = ws.cell(copy_from_row, c)
        v = src_cell.value
        if isinstance(v, str) and v.startswith("="):
            dst_coord = ws.cell(at_row, c).coordinate
            v = Translator(v, origin=src_cell.coordinate).translate_formula(dst_coord)
        copied[c] = v
    # 3. Physically shift rows >= at_row down by one (values + styles).
    ws.insert_rows(at_row, amount=1)
    # 4. Write back each cell's adjusted formula at its (possibly shifted)
    #    new coordinate.
    for (row, col), formula in adjusted.items():
        new_row = row + 1 if row >= at_row else row
        ws.cell(new_row, col).value = formula
    # 5. Drop the copied row into the row the insert just vacated.
    for c, v in copied.items():
        ws.cell(at_row, c).value = v
