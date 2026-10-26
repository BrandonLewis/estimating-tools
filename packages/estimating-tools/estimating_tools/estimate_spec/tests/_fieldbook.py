"""Helpers for the fieldbook pack's tests: load it, build its example, find rows by tag."""
from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path

import yaml
from openpyxl.formula.translate import Translator

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.readback.values import _REF, _STRING
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine

FIELDBOOK_DIR = fp.ENGINE_DIR / "packs" / "fieldbook"
#: A pack that `extends: fieldbook` (read-back accepts it) and one outside that lineage.
DERIVED = fp.ENGINE_DIR / "tests" / "fixtures" / "packs" / "derived_demo"
LEGACY = fp.ENGINE_DIR / "tests" / "fixtures" / "packs" / "legacy_demo"
EXAMPLE = FIELDBOOK_DIR / "examples" / "demo-pipeline.estimate.yaml"
#: Item sheets' hidden tag/helper columns: kind, code, ok-flag, flag.
KIND, CODE, OK, FLAG = "Q", "R", "S", "T"

def fieldbook_pack():
    return fp.load_pack(FIELDBOOK_DIR)


#: The name of the throwaway fieldbook fork `derived_pack_dir` writes.
DERIVED_NAME = "derived_fieldbook"
#: The fork's visible difference in the grid: the Cost Summary's column-A
#: head (fieldbook's "Item"), on a fixed-shape book sheet read-back compares
#: against its baseline -- a baseline built with fieldbook instead of the
#: fork would see column A differ and skip the sheet with a notice.
DERIVED_ITEM_HEAD = "Bid item"


def _fork_item_head(units) -> None:
    head = units["cost_summary_head"]["rows"][1]["cells"]["A"]
    assert head["value"] == "Item"
    head["value"] = DERIVED_ITEM_HEAD


def derived_pack_dir(tmp_path, *, name: str = DERIVED_NAME, derived_from="fieldbook",
                     keep_layout_map: bool = False, format_edit=None, units_edit=None,
                     replace: dict | None = None) -> Path:
    """A minimal org-style fork of fieldbook under a fresh directory in `tmp_path`.

    A copy of the bundled pack renamed `name`, declaring `derived_from`
    (omitted when None), with two harmless differences -- an extra seed rate
    trade, and the Cost Summary's item head reading DERIVED_ITEM_HEAD -- and,
    unless `keep_layout_map`, no `layout_map:` of its own (it inherits
    fieldbook's). `format_edit(meta)` / `units_edit(units)` mutate the parsed
    format.yaml / units.yaml `units:` mapping before it is written;
    `replace` is {old: new} text replaced in units.yaml and recipes.yaml first.
    """
    root = Path(tempfile.mkdtemp(dir=tmp_path)) / "pack"
    shutil.copytree(FIELDBOOK_DIR, root)
    for old, new in (replace or {}).items():
        for doc in ("units.yaml", "recipes.yaml"):
            path = root / doc
            path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    manifest = root / "format.yaml"
    meta = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    meta["name"] = name
    if derived_from is not None:
        meta["derived_from"] = derived_from
    if not keep_layout_map:
        meta.pop("layout_map", None)
    if format_edit:
        format_edit(meta)
    manifest.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    seed_path = root / "seed.yaml"
    seed = yaml.safe_load(seed_path.read_text(encoding="utf-8"))
    seed["rate_table_trades"].append("Truck Driver")
    seed_path.write_text(yaml.safe_dump(seed, sort_keys=False), encoding="utf-8")
    units_path = root / "units.yaml"
    doc = yaml.safe_load(units_path.read_text(encoding="utf-8"))
    _fork_item_head(doc["units"])
    if units_edit:
        units_edit(doc["units"])
    units_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return root


def example_spec() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


#: The two example packages (Task 12's demo-packages example, in code).
PACKAGES = [
    {"name": "Hauling", "kind": "subcontract", "strategy": "sub_out", "items": ["2"],
     "selected": "Dirt Movers", "conditions": ["Fuel surcharge", "Dump fees"]},
    {"name": "Valves", "kind": "subcontract", "strategy": "hybrid", "items": ["3"],
     "selected": "ARR"},
]

#: The three example quotes: a priced line with a surcharge and conditions, a
#: lump sum with no lines, and a priced line on the Valves package.
QUOTES = [
    CanonicalQuote(
        vendor_name="Dirt Movers", work_package_name="Hauling", quote_date="2026-10-20",
        surcharge=0.04, conditions={"Fuel surcharge": "4% of invoice", "Dump fees": "included"},
        lines=[QuoteLine(schedule_name="Base", item_number="2", unit_price=16.5,
                         line_name="Haul, import + export")]),
    CanonicalQuote(vendor_name="Bulk Haul Co", work_package_name="Hauling", amount=8740),
    CanonicalQuote(
        vendor_name="Valve Pros", work_package_name="Valves",
        lines=[QuoteLine(schedule_name="Base", item_number="3", unit_price=900,
                         line_name="Valve boxes (subcontract)")]),
]


def _line(spec: dict, item_no: str, slot: str, name: str) -> dict:
    (item,) = [i for i in spec["items"] if i["item_no"] == item_no]
    (block,) = [b for b in item["labor"] if b["slot"] == slot]
    (line,) = [ln for ln in block["lines"] if ln["name"] == name]
    return line


def packaged_spec() -> dict:
    """The example plus the Hauling and Valves packages: item 2 task 02's haul
    line prices Hauling; item 3 task 01 is self-perform and its valve-box line
    prices Valves."""
    spec = example_spec()
    spec["work_packages"] = copy.deepcopy(PACKAGES)
    _line(spec, "2", "02", "Haul, import + export")["package"] = "Hauling"
    (item3,) = [i for i in spec["items"] if i["item_no"] == "3"]
    item3["labor"][0]["carry"] = "self_perform"
    _line(spec, "3", "01", "Valve boxes (subcontract)")["package"] = "Valves"
    return spec


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


def paste_template_rows(wb, first: int, last: int, sheet: str, at: int) -> None:
    """Simulate Estimate Navigator's Insert. Insert `last-first+1` rows at `at` on
    `sheet` (Excel's insert, which shifts every same-sheet reference), then copy
    `_templates` rows first..last into them with Excel's copy: values and styles
    travel, and relative references shift with the paste."""
    ws, src = wb[sheet], wb["_templates"]
    count = last - first + 1
    for i in range(count):
        simulate_insert_copied_row(ws, at + i, at + i - 1)
    width = max(ws.max_column, src.max_column)
    for offset in range(count):
        for col in range(1, width + 1):
            s, d = src.cell(first + offset, col), ws.cell(at + offset, col)
            value = s.value
            if isinstance(value, str) and value.startswith("="):
                value = Translator(value, origin=s.coordinate).translate_formula(d.coordinate)
            d.value = value
            if s.has_style:
                d._style = copy.copy(s._style)


def _delete_sheet_refs(formula: str, sheet: str, own: bool, row: int) -> str:
    """What Excel does to the references INTO `sheet` (unqualified ones when
    the formula lives on it, and ones qualified with its name anywhere) when
    `row` is deleted: a row below moves up one; a single-cell reference to the
    row becomes `#REF!`; a range loses the row (an endpoint on it moves to the
    neighbouring row) and only a range that is the deleted row alone becomes
    `#REF!`. References into any other sheet are left alone."""
    def move(m):
        if not (_qualifier(m.group(1)) == sheet if m.group(1) else own):
            return m.group(0)
        qual = m.group(1) or ""
        if m.group(4) is None:
            n = int(m.group(3))
            if n == row:
                return "#REF!"
            return f"{qual}{m.group(2)}{n - 1 if n > row else n}"
        lo, hi = int(m.group(3)), int(m.group(5))
        if lo == hi == row:
            return "#REF!"
        lo = lo - 1 if lo > row else lo
        hi = hi - 1 if hi >= row else hi
        return f"{qual}{m.group(2)}{lo}:{m.group(4)}{hi}"

    parts = _STRING.split(formula)
    return "".join(p if i % 2 else _REF.sub(move, p) for i, p in enumerate(parts))


def simulate_delete_row(ws, row: int) -> None:
    """Simulate Excel's "delete row": every reference into this sheet (its own
    unqualified ones, and other sheets' ones qualified with its name) is
    rewritten by `_delete_sheet_refs` -- rows below move up, a range shrinks,
    and a single-cell reference TO the deleted row becomes `#REF!`, so the row
    below a deleted task row loses its code chain (`=R{row}` -> `=#REF!`),
    exactly as it does in Excel. References into other sheets are untouched.
    openpyxl's `delete_rows` moves the cells but never rewrites formula text,
    and never touches `merged_cells` at all -- both are done here: a merged
    range below `row` moves up with it, and one that spanned only the deleted
    row disappears."""
    adjusted = {}
    for line in ws.iter_rows(min_row=1, max_row=ws.max_row):
        for cell in line:
            v = cell.value
            if isinstance(v, str) and v.startswith("=") and cell.row != row:
                adjusted[(cell.row, cell.column)] = _delete_sheet_refs(v, ws.title, True, row)
    for other in ws.parent.worksheets:
        if other is ws:
            continue
        for line in other.iter_rows():
            for cell in line:
                v = cell.value
                if isinstance(v, str) and v.startswith("="):
                    cell.value = _delete_sheet_refs(v, ws.title, False, row)
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
