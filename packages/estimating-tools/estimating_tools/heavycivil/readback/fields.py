"""Which cells are inputs, how each is read, and which cells hold formulas.

The input cells are exactly the cells the writer styles ``input_*``
(``sheets/cost_report.py``, ``sheets/crews.py``, ``sheets/bid_form.py``).
Each is read into BidSheet.ai's own spelling before any diff: coded inputs
are matched case-insensitively against the writer's validation lists
(``cost_report.LISTS``, ``bid_form.SCOPES``), numbers become ``Decimal``.

The formula cells are the writer's too: a constant in one, or a cleared
one, refuses the read (the book would price differently from BidSheet.ai).
Known limit: a formula replaced by a *different* formula passes. The check
asks only that the cell still holds a formula; comparing formula text would
be fragile, since Excel rewrites relative references whenever rows are
inserted, deleted or copied.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from estimating_tools.heavycivil import columns as C
from estimating_tools.heavycivil.columns import BF, CR, CW
from estimating_tools.heavycivil.readback.errors import REBUILD, Problem
from estimating_tools.heavycivil.readback.scan import is_blank
from estimating_tools.heavycivil.sheets.bid_form import SCOPES
from estimating_tools.heavycivil.sheets.cost_report import LISTS


@dataclass(frozen=True)
class Input:
    """One input cell: ``letter`` holds ``field``, read by ``reader``.
    ``clear``: BidSheet.ai accepts a cleared (null) value for this field
    (its "Explicit clears" list). ``attr``: the baseline attribute when it
    is not named like the field."""
    letter: str
    field: str
    reader: str
    clear: bool = False
    attr: str | None = None

    @property
    def base_attr(self):
        return self.attr or self.field


#: Inputs by (sheet, kind). ACTIVITY ``duration_shifts`` is an input only on
#: an activity without steps (``inputs_for``).
INPUTS = {
    ("cost_report", "ITEM"): (
        Input(CR.QTY, "quantity_override", "number", clear=True),
        Input(CR.UCOST, "estimated_unit_price", "number"),
    ),
    ("cost_report", "ELEMENT_QTY"): (
        Input(CR.QTY, "override_value", "number", clear=True, attr="override"),
    ),
    ("cost_report", "ACTIVITY"): (
        Input(CR.DESC, "name", "name"),
        Input(CR.PROD, "production_rate", "number"),
        Input(CR.PUNIT, "production_unit", "unit"),
        Input(CR.HPS, "hours_per_shift", "number"),
        Input(CR.CFACT, "crew_factor", "number"),
        Input(CR.SHIFTS, "duration_shifts", "number"),
        Input(CR.COUNT, "count", "count"),
    ),
    ("cost_report", "STEP"): (
        Input(CR.DESC, "name", "name"),
        Input(CR.QTY, "duration", "number"),
        Input(CR.UNIT, "duration_unit", "step_unit"),
    ),
    ("cost_report", "RESOURCE"): (
        Input(CR.DESC, "name", "name"),
        Input(CR.QTY, "quantity", "number"),
        Input(CR.UNIT, "unit", "text", clear=True),
        Input(CR.UCOST, "unit_cost", "number"),
        Input(CR.PROD, "time_value", "number", clear=True),
        Input(CR.PUNIT, "time_unit", "time_unit", clear=True),
        Input(CR.TYPE, "component_type", "type"),
        Input(CR.BASIS, "labor_cost_basis", "basis"),
        Input(CR.BURD, "burden_percentage", "number", clear=True),
        Input(CR.BINC, "includes_burden", "flag"),
    ),
    ("crews", "MEMBER"): (
        Input(CW.CODE, "classification", "name"),
        Input(CW.COUNT, "count", "number"),
        Input(CW.OVERRIDE, "hourly_rate_override", "number", clear=True),
    ),
    ("bid_form", "ITEM_BID"): (
        Input(BF.SCOPE, "scope", "scope"),
        Input(BF.OVERRIDE, "bid_unit_price_override", "number", clear=True),
    ),
}

#: The Bid Form's estimate inputs, found by name (``BF.INPUT``), value in C.
ESTIMATE_INPUTS = {name: Input(BF.VALUE, name, "number") for name in BF.INPUTS}

#: Coded readers -> (choices, what blank reads as).
_CODES = {
    "unit": (LISTS["unit"], None),
    "step_unit": (LISTS["unit"], "DAYS"),
    "time_unit": (LISTS["unit"], ""),
    "type": (LISTS["type"], None),
    "basis": (LISTS["basis"], None),
    "flag": (LISTS["flag"], None),
    "scope": (SCOPES, None),
}

_HEADINGS = {key: {c.letter: c.heading for c in cols} for key, cols in C.SHEETS.items()}


def heading(sheet, letter):
    return _HEADINGS.get(sheet, {}).get(letter, letter)


def inputs_for(sheet, kind, *, stepped=False):
    found = INPUTS.get((sheet, kind), ())
    if kind == "ACTIVITY" and stepped:
        found = tuple(i for i in found if i.field != "duration_shifts")
    return found


def is_formula(cell) -> bool:
    return cell.data_type == "f"


def _g15(number) -> str:
    return f"{float(number):.15g}"


def number_equal(book, base) -> bool:
    """Equal as numbers. A cell comes back from Excel as a float, so a
    baseline figure that a float cannot hold exactly (or float noise such as
    0.1 + 0.2) still compares equal: to 15 significant digits, the precision
    a double always holds."""
    if book is None or base is None:
        return book is None and base is None
    return book == base or _g15(book) == _g15(base)


def _trim(value) -> str:
    return (value or "").strip()


def same(inp, book, base) -> bool:
    if inp.reader in ("number", "count"):
        return number_equal(book, None if base is None else Decimal(str(base)))
    if inp.reader in ("name", "text", "time_unit", "unit"):
        # None and "" alike: the baseline may carry "" (the server field is
        # blank=True) where a blank cell reads as None.
        return _trim(book) == _trim(base)
    return book == base


#: A number cell Excel shows as a percent: the estimator typed "15%", and
#: Excel stored 0.15.
PERCENT = "holds percent points -- type 15, not 15%"


def _is_percent_format(number_format) -> bool:
    """A ``%`` outside quotes and not escaped: Excel scales the value by 100
    (``0%``). A quoted ``"%"`` or ``\\%`` is literal text and does not."""
    quoted, escaped = False, False
    for ch in number_format or "":
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif ch == "%" and not quoted:
            return True
    return False


def message(label, error) -> str:
    """A cell's problem text: ``Burden % holds percent points ...`` or
    ``Burden %: 'abc' is not a number``."""
    return f"{label} {error}" if error == PERCENT else f"{label}: {error}"


def parse_number(value):
    """``(Decimal | None, error | None)``. Text numbers may carry thousands
    commas and a leading ``$``."""
    if is_blank(value):
        return None, None
    if isinstance(value, bool):
        return None, f"{value!r} is not a number"
    if isinstance(value, (datetime.date, datetime.time, datetime.timedelta)):
        return None, "a date is not a number"
    if isinstance(value, float):
        number = Decimal(f"{value:.15g}")
    elif isinstance(value, int):
        number = Decimal(value)
    else:
        text = str(value).strip().replace(",", "")
        if text.startswith("$"):
            text = text[1:].strip()
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None, f"{value!r} is not a number"
    if not number.is_finite():
        return None, f"{value!r} is not a number"
    return number, None


def read_value(inp, cell):
    """``(value, error | None)`` for one input cell, in BidSheet.ai's spelling."""
    if is_formula(cell):
        return None, "this input holds a formula -- type a value instead"
    value = cell.value
    if inp.reader == "number":
        if not is_blank(value) and _is_percent_format(cell.number_format):
            return None, PERCENT
        return parse_number(value)
    if inp.reader == "count":
        number, error = parse_number(value)
        if error or number is None:
            return number, error
        if number != number.to_integral_value():
            return None, f"{value!r} is not a whole number"
        return int(number), None
    if inp.reader == "name":
        return (None if is_blank(value) else str(value).strip()), None
    if inp.reader == "text":
        return ("" if is_blank(value) else str(value).strip()), None
    choices, blank = _CODES[inp.reader]
    if is_blank(value):
        return blank, None
    text = str(value).strip()
    match = next((c for c in choices if c.casefold() == text.casefold()), None)
    if match is None:
        return None, f"{value!r} is not one of {', '.join(choices)}"
    if inp.reader == "flag":
        return match == "Y", None
    return match, None


@dataclass
class Read:
    """A row's inputs read: ``values`` by field (None for blank), and a
    problem per unreadable cell."""
    values: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    #: Fields whose cell could not be read (each has a problem).
    bad: set = field(default_factory=set)

    @property
    def ok(self):
        return not self.problems


def _reads(line) -> dict:
    """``line``'s cache of reads, keyed by how the row was read."""
    if line.read is None:
        line.read = {}
    return line.read


def read_line(book, line, kind, *, stepped=False) -> Read:
    """Read ``line``'s inputs as a row of ``kind``. Cached on the line by
    ``(kind, stepped)``: a typed row may be read as more than one kind, and
    an activity with and without its Shifts input."""
    reads, key = _reads(line), (kind, stepped)
    if key in reads:
        return reads[key]
    ws, tab = book.ws(line.sheet), book.tab(line.sheet)
    result = Read()
    for inp in inputs_for(line.sheet, kind, stepped=stepped):
        value, error = read_value(inp, ws[f"{inp.letter}{line.row}"])
        if error:
            result.problems.append(Problem(
                tab, line.row, inp.letter, message(heading(line.sheet, inp.letter), error)))
            result.bad.add(inp.field)
        result.values[inp.field] = value
    reads[key] = result
    return result


def read_estimate_input(book, line) -> Read:
    """An ESTIMATE / BID_INPUT row: its one value, named by ``line.name``."""
    reads, key = _reads(line), ("estimate", line.name)
    if key in reads:
        return reads[key]
    inp = ESTIMATE_INPUTS[line.name]
    value, error = read_value(inp, book.ws("bid_form")[f"{inp.letter}{line.row}"])
    result = Read(values={inp.field: value})
    if error:
        result.problems.append(Problem(book.tab("bid_form"), line.row, inp.letter,
                                       message(line.name, error)))
    reads[key] = result
    return result


def diff(book, line, kind, base, problems, *, stepped=False) -> dict:
    """The fields of an existing row that differ from ``base``: ``{field:
    (before, after)}``. A clear BidSheet.ai cannot take is a problem."""
    read = read_line(book, line, kind, stepped=stepped)
    changes = {}
    for inp in inputs_for(line.sheet, kind, stepped=stepped):
        if inp.field not in read.values or inp.field in read.bad:
            continue
        after = read.values[inp.field]
        before = getattr(base, inp.base_attr)
        if same(inp, after, before):
            continue
        if after is None and not inp.clear:
            problems.add(book.tab(line.sheet), line.row, inp.letter,
                         f"{heading(line.sheet, inp.letter)} can't be cleared -- type a value")
            continue
        changes[inp.field] = (before, after)
    return changes


def equal_to_base(book, line, kind, base, *, stepped=False) -> bool:
    """Every input of ``line`` reads cleanly and equals ``base``."""
    read = read_line(book, line, kind, stepped=stepped)
    if not read.ok:
        return False
    return all(same(inp, read.values[inp.field], getattr(base, inp.base_attr))
               for inp in inputs_for(line.sheet, kind, stepped=stepped))


# -- export values a formula reads ------------------------------------------------

#: Cells the writer shows as export values (no apply op writes them) that
#: the book's formulas read: an edit would reprice the book while
#: BidSheet.ai kept the figure, so any change refuses the read. By (sheet,
#: kind): (letter, baseline attribute, what the problem calls it). The
#: crew's hours/shift and factor feed every crew-priced activity's labour
#: and man-hours; the bid quantity, the item's bid unit price and total; the
#: derived quantity, the element quantity's effective figure.
EXPORT_VALUES = {
    ("crews", "CREW"): ((CW.HPS, "hours_per_shift", "the crew's hours/shift"),
                        (CW.CFACT, "crew_factor", "the crew factor")),
    ("bid_form", "ITEM_BID"): ((BF.QTY, "schedule_quantity", "the bid quantity"),),
    ("cost_report", "ELEMENT_QTY"): ((CR.UCOST, "derived", "the derived quantity"),),
}

READ_ONLY = "{label} is read-only in the workbook -- change it in BidSheet.ai"


def check_export_values(book, line, base, problems):
    """Each export value of ``line`` that a formula reads must still equal
    ``base``, compared the way inputs are (15 significant digits; blank and
    None alike). A formula, or anything that is not a number, is a change."""
    ws = book.ws(line.sheet)
    for letter, attr, label in EXPORT_VALUES.get((line.sheet, line.kind), ()):
        cell = ws[f"{letter}{line.row}"]
        number, error = (None, "formula") if is_formula(cell) else parse_number(cell.value)
        expected = getattr(base, attr)
        if error is None and number_equal(
                number, None if expected is None else Decimal(str(expected))):
            continue
        problems.add(book.tab(line.sheet), line.row, letter, READ_ONLY.format(label=label))


# -- formula cells ---------------------------------------------------------------

_SPLIT = tuple(col for _kind, col in CR.SPLIT)

#: The cells the writer fills with a formula, by (sheet, kind). Every Cost
#: Report row also carries the activity-row helper (``CR.ACT``).
FORMULAS = {
    ("cost_report", "ITEM"): _SPLIT + (CR.TOTAL, CR.H2, CR.H3),
    ("cost_report", "ELEMENT_QTY"): (CR.H2,),
    ("cost_report", "ACTIVITY"): (CR.MH, CR.LAB) + _SPLIT[1:] + (CR.TOTAL, CR.MULT),
    ("cost_report", "RESOURCE"): (CR.MH,) + _SPLIT + (CR.TOTAL, CR.H1, CR.H2),
    ("crews", "CREW"): (CW.HEADCOUNT, CW.RATE),
    ("crews", "MEMBER"): (CW.LIBRATE, CW.EFFECTIVE, CW.EXTENDED),
    ("bid_form", "ITEM_BID"): (BF.PRICE, BF.TOTAL, BF.COST, BF.PRICED, BF.PCOST),
    ("bid_form", "BID_TOTAL"): (BF.TOTAL,),
}

#: Bid Form figures that are formulas (the rest are as of export).
FORMULA_FIGURES = ("direct_cost", "markup_total", "bid_factor", "excluded_cost")


def formula_cells(book, line):
    """The letters of ``line``'s cells the writer made formulas."""
    if line.kind is None:
        return ()
    cols = FORMULAS.get((line.sheet, line.kind), ())
    if line.sheet == "cost_report":
        cols += (CR.ACT,)
        if line.kind == "ITEM":
            item = book.model.item(line.id)
            if item is None or item.scope != "excluded":
                cols += (CR.H4,)
        if line.kind == "ACTIVITY" and line.occ is not None and line.occ.has_steps_marker:
            cols += (CR.SHIFTS,)
    if line.sheet == "bid_form" and line.kind == "BID_FIGURE" and line.name in FORMULA_FIGURES:
        cols += (BF.VALUE,)
    return cols


LOST_REF = f"a formula here lost its reference (#REF!) -- undo the delete, or {REBUILD}"


def check_formulas(book, s, problems):
    """A constant (or nothing) where the writer put a formula refuses the read,
    every such cell named. So does any formula on a scanned sheet that lost
    its reference (``#REF!``: Excel's mark for a deleted row it pointed at)."""
    for key in ("cost_report", "crews", "bid_form"):
        for row in book.ws(key).iter_rows():
            for cell in row:
                if is_formula(cell) and "#REF!" in str(cell.value).upper():
                    problems.add(book.tab(key), cell.row, cell.column_letter, LOST_REF)
    for line in s.cost_report + s.crew_lines + s.bid_form:
        ws = book.ws(line.sheet)
        for letter in formula_cells(book, line):
            cell = ws[f"{letter}{line.row}"]
            if is_formula(cell):
                continue
            now = "was cleared" if is_blank(cell.value) else "now holds a value"
            problems.add(book.tab(line.sheet), line.row, letter,
                         f"{heading(line.sheet, letter)} held a formula and {now} -- undo "
                         "the edit, or copy the formula back from a row of the same kind")
