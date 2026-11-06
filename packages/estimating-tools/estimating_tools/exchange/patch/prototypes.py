"""A typed row becomes a row of its kind (its prototype's cells), and a
created row's blank inputs take what the server filled in. The prototype is
the declaration's (``Declaration.prototypes``: a kind's lower-case name to a
workbook-scoped defined name over whole rows)."""
from __future__ import annotations

from decimal import Decimal

from openpyxl.formula.translate import Translator

from estimating_tools.exchange import writer
from estimating_tools.exchange.patch.cells import REBUILD
from estimating_tools.exchange.reader import fields as F
from estimating_tools.exchange.reader.scan import is_blank, is_formula

__all__ = ["fill_inputs", "prototype_rows", "spelled", "type_row"]


def spelled(value, inp=None):
    """A payload value as the build writes it into a cell. A Decimal becomes
    an int when it is whole, else ``float(str(d))``: the read compares
    numbers to 15 significant digits (``fields.number_equal``), which a
    double always holds, so the row reads back equal. A flag input (``inp``)
    is ``Y``/``N``; None stays None; text stays text."""
    if inp is not None and inp.reader == "flag":
        return "Y" if value else "N"
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(str(value))
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)


def prototype_rows(book, kind):
    """``(worksheet, first, last)``: the rows of ``kind``'s prototype (the
    declaration's ``prototypes`` entry, resolved through the book's defined
    names), or None when the book has none."""
    name = book.decl.prototypes.get(kind.lower())
    if name is None:
        return None
    try:
        text = book.wb.defined_names[name].attr_text
        sheet, rows = text.rsplit("!", 1)
        sheet = sheet.strip("'").replace("''", "'")
        first, _sep, last = rows.replace("$", "").partition(":")
        return book.wb[sheet], int(first), int(last or first)
    except (KeyError, ValueError, AttributeError):
        return None


def type_row(cells, key, row, kind) -> set:
    """Make typed row ``row`` a ``kind`` row: its kind cell, and every cell its
    prototype carries -- formulas translated to the row, constants as they
    are -- into blank cells only. Input columns are never copied (a
    prototype's inputs are blank, and a constant there would read as an
    edit); nor are the row's stored tags (the patch writes those), but a
    derived tag's chain formula is copied like any other. Returns the
    letters queued. A missing prototype, or a value typed where the
    prototype has a formula, is a problem; the kind is written regardless,
    so the next read refuses rather than creating the row twice."""
    book, tab = cells.book, cells.book.tab(key)
    kind_col = book.kinds[key]["kind_cell"]
    queued = set()
    cells.put(key, row, kind_col, kind)
    queued.add(kind_col)
    source = prototype_rows(book, kind)
    if source is None:
        cells.problem(f"{tab} row {row}: the book has no {kind.lower()} prototype row, so "
                      f"the typed row has no formulas -- {REBUILD}")
        return queued
    proto_ws, proto_row, _last = source
    skip = {letter for name, letter in book.kinds[key]["kinds"].get(kind, {}).items()
            if not cells.derived(key, kind, name)} | {kind_col}
    skip |= {inp.letter for inp in F.inputs_for(book, key, kind)}
    ws = cells.ws(key)
    for src in proto_ws[proto_row]:
        letter = src.column_letter
        if letter in skip or is_blank(src.value):
            continue
        dst = ws[f"{letter}{row}"]
        if is_formula(dst):
            continue
        if not is_formula(src):
            if is_blank(dst.value):
                cells.put(key, row, letter, src.value)
                queued.add(letter)
            continue
        if not is_blank(dst.value) or not isinstance(src.value, str):
            cells.problem(f"{tab} row {row} column {letter}: a value is typed where a "
                          f"{kind.lower()} row has a formula -- clear it and copy the formula "
                          f"from a row of the same kind, or {REBUILD}")
            continue
        text = Translator(src.value, origin=f"{letter}{proto_row}").translate_formula(
            f"{letter}{row}")
        cells.put(key, row, letter, writer.Formula(text))
        queued.add(letter)
    return queued


def fill_inputs(cells, key, row, kind, obj, *, stepped=False):
    """A created row's blank inputs that the server filled with a value the
    blank cell does not read as (a new activity's Hrs/shift, a typed line's
    Labor basis): the server's value, as the build writes it."""
    if obj is None:
        return
    ws = cells.ws(key)
    for inp in F.inputs_for(cells.book, key, kind, stepped=stepped):
        cell = ws[f"{inp.letter}{row}"]
        if is_formula(cell) or not is_blank(cell.value):
            continue
        blank, _error = F.read_value(inp, cell)
        base = getattr(obj, inp.base_attr)
        if base is None or F.same(inp, blank, base):
            continue
        cells.put(key, row, inp.letter, spelled(base, inp))
