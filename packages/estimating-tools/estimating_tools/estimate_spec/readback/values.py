"""Cell values <-> spec values: what counts as unchanged, and how a typed cell reads.

The builder writes every text value through `build.coerce_cell_value` (so an item number
"2" lands as the number 2 and a date string as a date). A spec field is
unchanged when its cell still holds what the builder wrote for it -- that is
the comparison here, so a no-op read-back changes nothing.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from estimating_tools.estimate_spec.build import coerce_cell_value

#: A formula an input cell may hold and the spec may keep: arithmetic on
#: literals only (`=640*1.1`). Anything naming a cell or function refers to
#: the workbook's layout, which a rebuild moves.
_PURE_FORMULA = re.compile(r"=[0-9.\s+\-*/()^%]+")

#: A cell or range reference in a formula -- `$B$8`, `B6:B7`,
#: `'Rates'!$A$5:$H$12` -- with its optional sheet qualifier (group 1), the
#: first endpoint's column and row (2, 3) and a range's second endpoint (4,
#: 5). The whole qualified range is one match, so its second endpoint is
#: never mistaken for a same-sheet reference. Never matched inside a longer
#: token (`LOG10(`, a name). Modelled on build.py's `_CELL_REF_RE`.
_REF = re.compile(
    r"(?<![A-Za-z0-9_.$'!:])"
    r"((?:'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"(\$?[A-Z]{1,3}\$?)(\d+)"
    r"(?::(\$?[A-Z]{1,3}\$?)(\d+))?"
    r"(?![A-Za-z0-9_(.!])")
#: A string literal, kept as is (its text is not a reference).
_STRING = re.compile(r'("(?:[^"]|"")*")')

#: `YYYY-MM-DD` -- what a date field's `old` spec value looks like.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

#: Sentinel: "no baseline cell was supplied" -- distinct from a baseline that
#: is itself blank/None. Only `same_number`'s placeholder branch reads it.
NO_BASELINE = object()


def blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def tidy(v):
    """A whole float as an int (Excel stores 42 and 42.0 alike)."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


def as_text(v) -> str:
    """A cell (or spec) value as the text it shows."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def excel_date(v):
    """The datetime an Excel date serial stands for (a date cell that lost its
    number format reads back as the plain number), else None."""
    if not is_number(v):
        return None
    from openpyxl.utils.datetime import from_excel
    try:
        return from_excel(v)
    except (ValueError, OverflowError):
        return None


def same_text(cell, old) -> bool:
    """Does `cell` still hold what the builder wrote for the text `old`?"""
    if blank(old):
        return blank(cell)
    if isinstance(old, str) and _ISO_DATE.fullmatch(old.strip()):
        # A date serial is still the same day as the ISO date it represents,
        # not a different, unreadable value.
        day = excel_date(cell)
        if day is not None:
            return as_text(day) == old.strip()
    return cell == coerce_cell_value(str(old)) or as_text(cell) == str(old)


def remap_rows(formula, rows: dict):
    """`formula` with every same-sheet row number moved through `rows`
    ({baseline row: edited row}) -- what Excel did to it when rows were
    inserted or deleted above it. `$` anchors are kept as written (Excel
    moves anchored references on an insert all the same); a reference into
    another sheet is left alone. None when a referenced row has no
    counterpart in the edited sheet (it was deleted): the formula cannot be
    said to be unchanged. Anything not a formula string comes back as is."""
    if not (isinstance(formula, str) and formula.startswith("=")):
        return formula
    missing = False

    def row(n: str) -> str:
        nonlocal missing
        moved = rows.get(int(n))
        missing = missing or moved is None
        return n if moved is None else str(moved)

    def move(m):
        if m.group(1):                   # another sheet's cells: rows here do not move them
            return m.group(0)
        out = m.group(2) + row(m.group(3))
        return out if m.group(4) is None else f"{out}:{m.group(4)}{row(m.group(5))}"

    parts = _STRING.split(formula)       # odd indexes are string literals
    out = "".join(p if i % 2 else _REF.sub(move, p) for i, p in enumerate(parts))
    return None if missing else out


def same_number(cell, old, *, baseline=NO_BASELINE) -> bool:
    """Does `cell` still hold what the builder wrote for the number or formula `old`?

    `old` may be a formula the spec keeps literally (kept as typed, e.g.
    `=640*1.1`), or a placeholder (``={ref:...}``) the builder resolves to a
    real formula when it writes the cell. For a placeholder, "unchanged"
    means the cell still matches that resolved value -- `baseline`, the same
    cell read from a fresh build of the unedited spec -- never just "any
    formula is fine": without a baseline to compare against, a formula there
    is always read as a change, the same as any other formula input.
    """
    if isinstance(cell, str) and cell.startswith("="):
        if isinstance(old, str) and "{" in old:
            return baseline is not NO_BASELINE and cell == baseline
        return cell == old
    if is_number(cell) and is_number(old):
        return abs(cell - old) < 1e-9
    return blank(cell) and old is None


def read_number(cell, *, formula_ok: bool = True):
    """(value, None) for a usable number, else (None, why not)."""
    if blank(cell):
        return None, "is blank"
    if is_number(cell):
        return tidy(cell), None
    if isinstance(cell, str):
        s = cell.strip()
        if s.startswith("="):
            if formula_ok and _PURE_FORMULA.fullmatch(s):
                return s, None
            return None, f"holds the formula {s!r} -- type a number"
        try:
            return tidy(float(s.replace(",", ""))), None
        except ValueError:
            pass
    if isinstance(cell, (date, datetime)):
        return None, f"is {as_text(cell)!r}, not a number"
    return None, f"is {cell!r}, not a number"


def fmt(v) -> str:
    """A value as the report shows it."""
    if v is None or v == "":
        return "(blank)"
    if is_number(v):
        v = tidy(v)
        return f"{v:,}" if isinstance(v, int) else f"{v:,.10g}"
    return str(v)
