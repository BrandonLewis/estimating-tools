"""Shift the row numbers in one formula's references the way Excel does when
whole rows are inserted into, or deleted from, one sheet (engine spec,
"Patch and refresh": the writer inserts rows and "shifts the references the
insertion moves").

A reference into the edited sheet moves: an unqualified one in a formula
that lives on that sheet (``own``), and one qualified with its name
wherever it lives. On an insert every row number at or below the insertion
point moves down by the count; each end of a range moves on its own, so a
range that spans the point grows. On a delete a single-cell reference to a
deleted row becomes ``#REF!`` (with its sheet prefix, as Excel writes it); a
range loses the deleted rows and becomes ``#REF!`` only when nothing of it is
left. ``$`` anchors never stop a shift. A range that ends on Excel's last row
keeps that end (``A6:A1048576`` stays open-ended); a single cell pushed past
the last row, or a range whose top would be, becomes ``#REF!``. Column
letters are read in any case; text that is not a cell on the sheet's grid
(a name such as ``XYZ1``) is not a reference. Whole-column references,
defined names, structured (table) references, references into other sheets
and into other workbooks are left alone.

The formula is tokenized with openpyxl's ``Tokenizer`` -- the same tokens
``Translator`` rewrites -- so text inside a string literal is never read as
a reference. The result is rebuilt from the original text between the
tokens, so spaces and line breaks survive, and a formula no reference of
which moves comes back unchanged. A three-dimensional reference
(``Sheet1:Sheet3!A1``) whose span includes the edited sheet cannot be
shifted for one sheet and is refused, as is one whose span cannot be
resolved against ``sheets`` (the workbook's sheet order), and a formula the
tokenizer cannot read (``RefsError``). A 3-D span that leaves the edited
sheet out is not touched. Bodies are formula text without the leading
``=``, as a sheet's ``<f>`` element holds it."""
from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.formula.tokenizer import Token, Tokenizer, TokenizerError

__all__ = ["Delete", "Insert", "RefsError", "could_mention", "delete", "insert", "mentions",
           "relative_rows", "span", "sqref_delete", "sqref_insert"]

#: Excel's last row and column.
MAX_ROW = 1048576
MAX_COL = 16384

_COL = r"\$?[A-Za-z]{1,3}\$?"
_CELL = re.compile(rf"^({_COL})(\d+)$")
_AREA = re.compile(rf"^({_COL})(\d+):({_COL})(\d+)$")
_ROWS = re.compile(r"^(\$?)(\d+):(\$?)(\d+)$")
#: Chained ranges (``A5:A5:A7``): Excel reads the first two as an area and
#: each further one as a cell.
_CHAIN = re.compile(rf"^{_COL}\d+(?::{_COL}\d+){{2,}}$")
#: A function token that begins with a range's first cell (``A1:INDEX(``):
#: the tokenizer folds the cell into the function's token.
_FUNC_REF = re.compile(
    r"^((?:(?:'(?:[^']|'')+'|[A-Za-z0-9_.]+)!)?\$?[A-Za-z]{1,3}\$?\d+):(.+\()$")
_SPACE = " \t\r\n"
_DIGITS = re.compile(r"\d+")
#: Text that may be a 3-D prefix (``Jan:Mar!``, ``'Sheet 1:Sheet 3'!``).
_MAYBE_3D = re.compile(r"(?:'(?:[^']|'')*:(?:[^']|'')*'|[\w.]+:[\w.]+)!")


class RefsError(ValueError):
    """A formula whose references cannot be shifted; nothing is written."""


@dataclass(frozen=True)
class Insert:
    """``count`` rows inserted above row ``at``."""
    at: int
    count: int

    @property
    def edge(self) -> int:
        """The first row this insert can move."""
        return self.at

    def rows(self, lo: int, hi: int, area: bool = False):
        """Where rows ``lo..hi`` end up: ``(lo, hi)``, or None when they
        would leave the sheet (a single cell past the last row, or an area
        whose top would be; an area's bottom stops at the last row)."""
        lo2 = lo + self.count if lo >= self.at else lo
        hi2 = hi + self.count if hi >= self.at else hi
        if lo2 > MAX_ROW:
            return None
        if hi2 > MAX_ROW:
            if not area:
                return None
            hi2 = MAX_ROW
        return lo2, hi2


@dataclass(frozen=True)
class Delete:
    """``count`` rows deleted from row ``first`` down."""
    first: int
    count: int

    @property
    def last(self) -> int:
        return self.first + self.count - 1

    @property
    def edge(self) -> int:
        """The first row this delete can move."""
        return self.first

    def rows(self, lo: int, hi: int, area: bool = False):
        """Where rows ``lo..hi`` end up: ``(lo, hi)``, or None when every one
        of them is deleted. An area that ends on the last row keeps that
        end, as Excel's does."""
        first, last, n = self.first, self.last, self.count
        if first <= lo and hi <= last:
            return None
        lo2 = lo if lo < first else (first if lo <= last else lo - n)
        hi2 = hi if hi < first else (first - 1 if hi <= last else hi - n)
        if area and hi == MAX_ROW:
            hi2 = MAX_ROW
        return lo2, hi2


def _unquote(prefix: str) -> str:
    """``'It''s'!`` -> ``It's``; ``Rates!`` -> ``Rates``."""
    name = prefix[:-1]
    if len(name) >= 2 and name.startswith("'") and name.endswith("'"):
        name = name[1:-1].replace("''", "'")
    return name


def _split(value: str):
    """``(prefix, ref)``: the sheet prefix up to and including the last ``!``
    outside quotes ('' when there is none), and the rest."""
    quote, cut = False, -1
    for i, ch in enumerate(value):
        if ch == "'":
            quote = not quote
        elif ch == "!" and not quote:
            cut = i
    if cut < 0:
        return "", value
    return value[:cut + 1], value[cut + 1:]


def _external(prefix: str) -> bool:
    return prefix.startswith("[") or "]" in prefix


def _span_3d(prefix: str):
    """``(first, last)`` sheet names of a 3-D prefix (``Jan:Mar!`` or
    ``'Sheet 1:Sheet 3'!``), else None. A sheet name cannot hold a colon."""
    name = _unquote(prefix)
    if ":" not in name:
        return None
    first, _sep, last = name.partition(":")
    return first, last


def _targets(prefix: str, sheet: str, own: bool, value: str, sheets) -> bool:
    if not prefix:
        return own
    if _external(prefix):
        return False                                  # another workbook
    got = _span_3d(prefix)
    if got is not None:
        order = [s.casefold() for s in sheets or ()]
        a, b = (n.casefold() for n in got)
        if a not in order or b not in order or sheet.casefold() not in order:
            raise RefsError(f"the 3-D reference {value} cannot be resolved against the "
                            "workbook's sheets, so it cannot be moved for one sheet")
        lo, hi = sorted((order.index(a), order.index(b)))
        if lo <= order.index(sheet.casefold()) <= hi:
            raise RefsError(f"the 3-D reference {value} reads {sheet} and cannot be moved for "
                            "one sheet")
        return False
    return _unquote(prefix).casefold() == sheet.casefold()


def _col_ok(letters: str) -> bool:
    n = 0
    for ch in letters.replace("$", "").upper():
        n = n * 26 + ord(ch) - 64
    return n <= MAX_COL


def _row_ok(row: str) -> bool:
    return 1 <= int(row) <= MAX_ROW


def _cell_text(m, move):
    """A single cell (``_CELL`` match) after ``move``; None when gone."""
    if not (_col_ok(m.group(1)) and _row_ok(m.group(2))):
        return False                                  # a name, not a cell
    got = move.rows(int(m.group(2)), int(m.group(2)))
    return None if got is None else f"{m.group(1)}{got[0]}"


def _area_text(m, move, cols=True):
    """An area (``_AREA``) or row range (``_ROWS``) after ``move``."""
    if cols and not (_col_ok(m.group(1)) and _col_ok(m.group(3))):
        return False
    if not (_row_ok(m.group(2)) and _row_ok(m.group(4))):
        return False
    got = move.rows(int(m.group(2)), int(m.group(4)), area=True)
    return None if got is None else f"{m.group(1)}{got[0]}:{m.group(3)}{got[1]}"


def _moved(ref: str, move):
    """``ref`` (no sheet prefix) after ``move``: its text, None for a
    reference that is gone (``#REF!``), or False when it is not a cell,
    area, row range or chain of them."""
    m = _CELL.match(ref)
    if m:
        return _cell_text(m, move)
    m = _AREA.match(ref)
    if m:
        return _area_text(m, move)
    m = _ROWS.match(ref)
    if m:
        return _area_text(m, move, cols=False)
    if _CHAIN.match(ref):
        parts = ref.split(":")
        head = _area_text(_AREA.match(f"{parts[0]}:{parts[1]}"), move)
        if head is False:
            return False
        out = ["#REF!" if head is None else head]
        for part in parts[2:]:
            got = _cell_text(_CELL.match(part), move)
            if got is False:
                return False
            out.append("#REF!" if got is None else got)
        return ":".join(out)
    return False


def _map_range(value: str, sheet: str, own: bool, move, sheets=()) -> str:
    lead = ""
    if value.startswith(":"):                         # the far end of ``INDEX(...):A5``
        lead, value = ":", value[1:]
    prefix, ref = _split(value)
    if not _targets(prefix, sheet, own, value, sheets):
        return lead + value
    text = _moved(ref, move)
    if text is False:
        return lead + value                           # a column range, a name, #REF!
    return lead + prefix + ("#REF!" if text is None else text)


def _below(body: str, edge: int) -> bool:
    """True when every number in ``body`` is above row ``edge``: no
    reference in it can move, so it need not be tokenized."""
    digits = _DIGITS.findall(body)
    return not digits or max(map(int, digits)) < edge


def _rewrite(body: str, sheet: str, own: bool, move, sheets=()) -> str:
    if _below(body, move.edge):
        return body
    try:
        tokens = Tokenizer("=" + body).items
    except TokenizerError as exc:
        raise RefsError(f"cannot read the formula ={body}: {exc}") from None
    pieces = []
    for t in tokens:
        if t.type == Token.WSPACE:
            pieces.append((None, None))
            continue
        core = t.value.lstrip(_SPACE)
        new = core
        if t.type == Token.OPERAND and t.subtype == Token.RANGE:
            new = _map_range(core, sheet, own, move, sheets)
        elif t.type == Token.FUNC and t.subtype == Token.OPEN:
            m = _FUNC_REF.match(core)
            if m is not None:
                new = _map_range(m.group(1), sheet, own, move, sheets) + ":" + m.group(2)
        pieces.append((core, new))
    if all(core == new for core, new in pieces):
        return body
    return _splice(body, pieces)


def _splice(body: str, pieces) -> str:
    """The original ``body`` with each token's text replaced by its new text,
    keeping whatever lay between the tokens (spaces, line breaks) as it
    was."""
    out, at = [], 0
    for core, new in pieces:
        start = at
        while at < len(body) and body[at] in _SPACE:
            at += 1
        out.append(body[start:at])
        if core is None:
            continue
        if not body.startswith(core, at):
            # The tokenizer changed the text; fall back to its tokens.
            return "".join(n for c, n in pieces if c is not None)
        out.append(new)
        at += len(core)
    out.append(body[at:])
    return "".join(out)


def insert(body: str, *, sheet: str, own: bool, at: int, count: int, sheets=()) -> str:
    """``body`` after ``count`` rows were inserted above row ``at`` of
    ``sheet``. ``sheets``: the workbook's sheet titles in order, which
    resolve a 3-D reference's span."""
    return _rewrite(body, sheet, own, Insert(at, count), sheets)


def delete(body: str, *, sheet: str, own: bool, first: int, count: int, sheets=()) -> tuple:
    """``(text, lost)``: ``body`` after rows ``first..first+count-1`` of
    ``sheet`` were deleted, and whether a reference became ``#REF!``."""
    text = _rewrite(body, sheet, own, Delete(first, count), sheets)
    return text, text.upper().count("#REF!") > body.upper().count("#REF!")


def _could_mention(body: str, sheet: str) -> bool:
    low = body.casefold()
    if sheet.casefold() in low or sheet.replace("'", "''").casefold() in low:
        return True
    return _MAYBE_3D.search(body) is not None         # perhaps a 3-D span over it


def mentions(body: str, sheet: str) -> bool:
    """Does ``body`` hold a reference qualified with ``sheet``'s name, or a
    3-D reference that may span it?"""
    if not _could_mention(body, sheet):
        return False
    try:
        tokens = Tokenizer("=" + body).items
    except TokenizerError:
        return True                                   # let the rewrite refuse it
    for t in tokens:
        value = None
        if t.type == Token.OPERAND and t.subtype == Token.RANGE:
            value = t.value.lstrip(_SPACE).lstrip(":")
        elif t.type == Token.FUNC and t.subtype == Token.OPEN:
            m = _FUNC_REF.match(t.value.lstrip(_SPACE))
            value = m.group(1) if m else None
        if value is None:
            continue
        prefix, _ref = _split(value)
        if not prefix or _external(prefix):
            continue
        if _span_3d(prefix) is not None or _unquote(prefix).casefold() == sheet.casefold():
            return True
    return False


def could_mention(body: str, sheet: str) -> bool:
    """A cheap pre-check for ``mentions``: False only when ``body`` cannot
    name ``sheet`` at all, directly or through a 3-D span."""
    return _could_mention(body, sheet)


def relative_rows(body: str, sheet: str, home: bool) -> list:
    """``(into sheet, row)`` for every relative row number (no ``$``) in
    ``body``'s cell, area and row references. ``into sheet`` is whether the
    reference reads ``sheet``: an unqualified one does when the formula
    lives there (``home``). References into other workbooks and 3-D spans
    are skipped (the shift handles those). A formula the tokenizer cannot
    read gives ``[(True, 0)]``, which no caller treats as safe."""
    try:
        tokens = Tokenizer("=" + body).items
    except TokenizerError:
        return [(True, 0)]
    out = []
    for t in tokens:
        value = None
        if t.type == Token.OPERAND and t.subtype == Token.RANGE:
            value = t.value.lstrip(_SPACE).lstrip(":")
        elif t.type == Token.FUNC and t.subtype == Token.OPEN:
            m = _FUNC_REF.match(t.value.lstrip(_SPACE))
            value = m.group(1) if m else None
        if not value:
            continue
        prefix, ref = _split(value)
        if prefix and (_external(prefix) or _span_3d(prefix) is not None):
            continue
        into = home if not prefix else _unquote(prefix).casefold() == sheet.casefold()
        m = _ROWS.match(ref)
        if m:
            out += [(into, int(row)) for dollar, row in ((m.group(1), m.group(2)),
                                                        (m.group(3), m.group(4))) if not dollar]
            continue
        if not (_CELL.match(ref) or _AREA.match(ref) or _CHAIN.match(ref)):
            continue
        for part in ref.split(":"):
            cell = _CELL.match(part)
            if cell and _col_ok(cell.group(1)) and not cell.group(1).endswith("$"):
                out.append((into, int(cell.group(2))))
    return out


def span(ref: str):
    """``(first row, last row)`` of a cell, area or whole-row reference with no
    sheet prefix; None for anything else (a column range, a name)."""
    m = _CELL.match(ref or "")
    if m:
        return int(m.group(2)), int(m.group(2))
    m = _AREA.match(ref or "") or _ROWS.match(ref or "")
    if m:
        return int(m.group(2)), int(m.group(4))
    return None


def _sqref(text: str, move) -> str:
    out = []
    for part in (text or "").split():
        if span(part) is None:
            out.append(part)
            continue
        moved = _map_range(part, "", True, move)
        if moved != "#REF!":
            out.append(moved)
    return " ".join(out)


def sqref_insert(text: str, at: int, count: int) -> str:
    """A space-separated range list (``sqref``) after an insert."""
    return _sqref(text, Insert(at, count))


def sqref_delete(text: str, first: int, count: int) -> str:
    """A range list after a delete: ranges wholly deleted drop out; ``""``
    when nothing is left."""
    return _sqref(text, Delete(first, count))
