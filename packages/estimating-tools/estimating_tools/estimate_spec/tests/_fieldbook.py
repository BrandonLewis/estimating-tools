"""Helpers for the fieldbook pack's tests: load it, build its example, find rows by tag."""
from __future__ import annotations

import copy
import re

import yaml
from openpyxl.formula.translate import Translator

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.readback.values import _REF, _STRING

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


def _qualifier(prefix: str) -> str:
    """`'2 - 8IN MAIN'!` -> `2 - 8IN MAIN`; `Rates!` -> `Rates`."""
    name = prefix[:-1]
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def _shift_sheet_refs(formula: str, sheet: str, own: bool, at_row: int, delta: int) -> str:
    """Shift every row >= `at_row` by `delta` in each reference INTO `sheet`
    -- unqualified ones when the formula lives on `sheet` (`own`), and ones
    qualified with `sheet`'s name wherever it lives -- leaving references
    into any other sheet alone, both endpoints of a range included. What
    Excel does to every formula in the book when rows are inserted."""
    def row(n: str) -> str:
        return str(int(n) + delta) if int(n) >= at_row else n

    def move(m):
        if not (_qualifier(m.group(1)) == sheet if m.group(1) else own):
            return m.group(0)
        out = (m.group(1) or "") + m.group(2) + row(m.group(3))
        return out if m.group(4) is None else f"{out}:{m.group(4)}{row(m.group(5))}"

    parts = _STRING.split(formula)
    return "".join(p if i % 2 else _REF.sub(move, p) for i, p in enumerate(parts))


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
    #    from the sheet as it stands now, before anything physically moves):
    #    its own references into this sheet, and -- on every other sheet --
    #    references qualified with this sheet's name (a Cost Summary's
    #    `='2 - 8IN MAIN'!$K$13`), as Excel moves them. A reference into
    #    another sheet (`'Rates'!$A$5:$H$12`, both endpoints) stays put.
    adjusted = {}
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=max_col):
        for cell in row:
            v = cell.value
            if isinstance(v, str) and v.startswith("="):
                adjusted[(cell.row, cell.column)] = _shift_sheet_refs(v, ws.title, True, at_row, 1)
    for other in ws.parent.worksheets:
        if other is ws:
            continue
        for row in other.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v.startswith("="):
                    cell.value = _shift_sheet_refs(v, ws.title, False, at_row, 1)
    # 2. The new row's own content: a copy of `copy_from_row`, with every
    #    relative reference shifted by the same delta as the paste (the
    #    row's own self-refs, and its R-column chain ref to the row above
    #    it, move together -- that is what "copy down" means in Excel) and
    #    every absolute reference left untouched -- including a CROSS-SHEET
    #    one (a crew row's VLOOKUP into 'Rates'!$A$5:$H$12, its shift-hours
    #    'Rates'!$B$2). An insert shifts anchored references too, so step
    #    1's rule is the wrong tool for a paste. `Translator` (what Excel itself does on
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
    # Merged ranges, the same way: one entirely below `at_row` moves down
    # with it; one that straddles `at_row` grows to include the new row
    # (Excel's own behaviour on an insert in the middle of a merge); one
    # entirely above is untouched. Unmerged now (so every cell below is a
    # plain, writable Cell again) and re-merged only once every value is
    # back in place -- openpyxl never adjusts `merged_cells` on its own.
    new_ranges = []
    for rng in list(ws.merged_cells.ranges):
        min_row, max_row, min_col, rmax_col = rng.min_row, rng.max_row, rng.min_col, rng.max_col
        ws.unmerge_cells(start_row=min_row, start_column=min_col,
                         end_row=max_row, end_column=rmax_col)
        if min_row >= at_row:
            new_ranges.append((min_row + 1, min_col, max_row + 1, rmax_col))
        elif max_row >= at_row:
            new_ranges.append((min_row, min_col, max_row + 1, rmax_col))
        else:
            new_ranges.append((min_row, min_col, max_row, rmax_col))
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
    # 6. Restore every merge at its new extent.
    for (r1, c1, r2, c2) in new_ranges:
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def copy_rows(ws, first: int, last: int, to: int) -> None:
    """Copy rows first..last to start at row `to`, as Excel's copy/paste does:
    values and styles travel, relative references shift with the paste
    (`Translator`), absolute and cross-sheet references stay as written."""
    for offset, src_row in enumerate(range(first, last + 1)):
        for src in ws[src_row]:
            dst = ws.cell(to + offset, src.column)
            value = src.value
            if isinstance(value, str) and value.startswith("="):
                value = Translator(value, origin=src.coordinate).translate_formula(dst.coordinate)
            dst.value = value
            if src.has_style:
                dst._style = copy.copy(src._style)


def simulate_delete_row(ws, row: int) -> None:
    """Simulate Excel's "delete row": every same-sheet reference below `row`
    moves up one, and a reference TO the deleted row becomes `#REF!` -- so the
    row below a deleted task row loses its code chain (`=R{row}` -> `=#REF!`),
    exactly as it does in Excel. openpyxl's `delete_rows` moves the cells but
    never rewrites formula text, and never touches `merged_cells` at all --
    both are done here: a merged range below `row` moves up with it, and one
    that spanned only the deleted row disappears."""
    def repl(m):
        n = int(m.group(2))
        if n == row:
            return "#REF!"
        return f"{m.group(1)}{n - 1 if n > row else n}"
    adjusted = {}
    for line in ws.iter_rows(min_row=1, max_row=ws.max_row):
        for cell in line:
            v = cell.value
            if isinstance(v, str) and v.startswith("=") and cell.row != row:
                adjusted[(cell.row, cell.column)] = _CELL_REF.sub(repl, v)
    new_ranges = []
    for rng in list(ws.merged_cells.ranges):
        min_row, max_row, min_col, max_col = rng.min_row, rng.max_row, rng.min_col, rng.max_col
        ws.unmerge_cells(start_row=min_row, start_column=min_col,
                         end_row=max_row, end_column=max_col)
        if min_row <= row <= max_row:
            if min_row != max_row:                        # else: spanned only the deleted row
                new_ranges.append((min_row, min_col, max_row - 1, max_col))
        elif min_row > row:
            new_ranges.append((min_row - 1, min_col, max_row - 1, max_col))
        else:
            new_ranges.append((min_row, min_col, max_row, max_col))
    ws.delete_rows(row, 1)
    for (r, c), formula in adjusted.items():
        ws.cell(r - 1 if r > row else r, c).value = formula
    for (r1, c1, r2, c2) in new_ranges:
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def check_statuses(wb, ev) -> dict:
    """{(rule, item): status} for every check row on the Checks sheet, evaluated."""
    ws = wb["Checks"]
    return {(ws[f"A{r}"].value, ws[f"C{r}"].value): ev[f"Checks!F{r}"]
            for r in range(1, ws.max_row + 1) if isinstance(ws[f"A{r}"].value, int)}
