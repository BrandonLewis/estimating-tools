"""Which cells are inputs, how each is read, and which cells hold formulas.

The input cells are the contract's writable fields (``contract.FIELDS``) at
the columns the book's declaration binds them to (``Sheet.fields``): what
the writer styles ``input_*`` is what the declaration binds. Each is read
into BidSheet.ai's own spelling before any diff: coded inputs are matched
case-insensitively against the contract's choices (``contract.CHOICES``),
numbers become ``Decimal``.

The formula cells are the declaration's too (``Sheet.formulas``): a
constant in one, or a cleared one, refuses the read (the book would price
differently from BidSheet.ai). Known limit: a formula replaced by a
*different* formula passes. The check asks only that the cell still holds a
formula; comparing formula text would be fragile, since Excel rewrites
relative references whenever rows are inserted, deleted or copied.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from estimating_tools.exchange import contract
from estimating_tools.exchange.reader.errors import REBUILD, Problem
from estimating_tools.exchange.reader.scan import is_blank, is_formula, untouched_row


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


def inputs_for_decl(decl, sheet, kind, *, stepped=False):
    """The bound inputs of ``kind`` on ``sheet``: the contract's writable
    fields for the kind, each at the column the declaration binds it to, in
    the contract table's field order (the declaration's own order is lost
    when the stamp sorts keys). A stepped activity loses the fields the
    contract marks stepless-only."""
    bound = decl.sheets[sheet].fields.get(kind, {})
    found = []
    for name, spec in contract.FIELDS.get(kind, {}).items():
        letter = bound.get(name)
        if letter is None:
            continue
        found.append(Input(letter, name, spec.reader, clear=spec.clear, attr=spec.attr))
    if stepped:
        drop = contract.STEPLESS_ONLY.get(kind, ())
        found = [i for i in found if i.field not in drop]
    return tuple(found)


def inputs_for(book, sheet, kind, *, stepped=False):
    return inputs_for_decl(book.decl, sheet, kind, stepped=stepped)


def estimate_inputs(book) -> dict:
    """The estimate's inputs by name (the flat sheet's named rows declared
    ``input``), each read as a number from the value column, in the
    contract's ESTIMATE field order; empty without a flat sheet or named
    rows. ``Book.estimate_inputs`` caches this per book."""
    flat = next((s for s in book.decl.sheets.values() if s.role == "flat"), None)
    named = flat.named_rows if flat is not None else None
    if named is None:
        return {}
    bound = {n for n, r in named.rows.items() if r.input}
    return {n: Input(named.value_column, n, "number")
            for n in contract.FIELDS["ESTIMATE"] if n in bound}


def heading(book, sheet, letter):
    """What a problem calls a cell: the declaration's heading for a visible
    column, else the letter."""
    return book.decl.sheets[sheet].columns.get(letter, letter)


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
    if inp.reader in ("number", "count", "summed"):
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
    if inp.reader == "summed":
        # The workbook sums these with SUMIF, which skips text: a "4" would
        # count as zero in the book and as four in BidSheet.ai.
        number, error = parse_number(value)
        if error is None and isinstance(value, str) and not is_blank(value):
            return None, f"{value!r} is text -- type the duration as a number"
        return number, error
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
    choices = contract.CHOICES[inp.reader]
    blank = contract.BLANK_CHOICE.get(inp.reader)
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


def untouched(book, line, kind, *, stepped=False) -> bool:
    """Nothing is typed on ``line``: a row inserted (an Estimate Navigator
    prototype, or a copy of one) and never filled. Every input cell of
    ``kind`` is blank, and so is every other visible cell bar formulas
    (``scan.untouched_row``): a value typed anywhere visible makes the row
    touched, and the new row's requirements then apply."""
    ws = book.ws(line.sheet)
    return (untouched_row(book.decl, ws, line.row, line.sheet, kind)
            and all(is_blank(ws[f"{inp.letter}{line.row}"].value)
                    for inp in inputs_for(book, line.sheet, kind, stepped=stepped)))


def read_line(book, line, kind, *, stepped=False) -> Read:
    """Read ``line``'s inputs as a row of ``kind``. Cached on the line by
    ``(kind, stepped)``: a typed row may be read as more than one kind, and
    an activity with and without its Shifts input."""
    reads, key = _reads(line), (kind, stepped)
    if key in reads:
        return reads[key]
    ws, tab = book.ws(line.sheet), book.tab(line.sheet)
    result = Read()
    for inp in inputs_for(book, line.sheet, kind, stepped=stepped):
        value, error = read_value(inp, ws[f"{inp.letter}{line.row}"])
        if error:
            result.problems.append(Problem(
                tab, line.row, inp.letter,
                message(heading(book, line.sheet, inp.letter), error)))
            result.bad.add(inp.field)
        result.values[inp.field] = value
    reads[key] = result
    return result


def read_estimate_input(book, line) -> Read:
    """An ESTIMATE / BID_INPUT row: its one value, named by ``line.name``."""
    reads, key = _reads(line), ("estimate", line.name)
    if key in reads:
        return reads[key]
    inp = book.estimate_inputs[line.name]
    value, error = read_value(inp, book.ws(line.sheet)[f"{inp.letter}{line.row}"])
    result = Read(values={inp.field: value})
    if error:
        result.problems.append(Problem(book.tab(line.sheet), line.row, inp.letter,
                                       message(line.name, error)))
    reads[key] = result
    return result


def diff(book, line, kind, base, problems, *, stepped=False) -> dict:
    """The fields of an existing row that differ from ``base``: ``{field:
    (before, after)}``. A clear BidSheet.ai cannot take is a problem."""
    read = read_line(book, line, kind, stepped=stepped)
    changes = {}
    for inp in inputs_for(book, line.sheet, kind, stepped=stepped):
        if inp.field not in read.values or inp.field in read.bad:
            continue
        after = read.values[inp.field]
        before = getattr(base, inp.base_attr)
        if same(inp, after, before):
            continue
        if after is None and not inp.clear:
            problems.add(book.tab(line.sheet), line.row, inp.letter,
                         f"{heading(book, line.sheet, inp.letter)} can't be cleared -- "
                         "type a value")
            continue
        changes[inp.field] = (before, after)
    return changes


def equal_to_base(book, line, kind, base, *, stepped=False) -> bool:
    """Every input of ``line`` reads cleanly and equals ``base``."""
    read = read_line(book, line, kind, stepped=stepped)
    if not read.ok:
        return False
    return all(same(inp, read.values[inp.field], getattr(base, inp.base_attr))
               for inp in inputs_for(book, line.sheet, kind, stepped=stepped))


# -- export values a formula reads ------------------------------------------------

#: What a problem calls each export value the declaration binds
#: (``Sheet.export_values``: letter -> baseline attribute). The crew's
#: hours/shift and factor feed every crew-priced activity's labour and
#: man-hours; the bid quantity, the item's bid unit price and total; the
#: derived quantity, the element quantity's effective figure.
LABELS = {
    "hours_per_shift": "the crew's hours/shift",
    "crew_factor": "the crew factor",
    "schedule_quantity": "the bid quantity",
    "derived": "the derived quantity",
    "effective_hourly_rate": "a crew member's rate as of export",
}


def export_values(book, sheet, kind):
    """The cells of ``kind`` on ``sheet`` the writer shows as export values
    (no apply op writes them) that the book's formulas read: ``(letter,
    baseline attribute, label)`` each. An edit would reprice the book while
    BidSheet.ai kept the figure, so any change refuses the read."""
    bound = book.decl.sheets[sheet].export_values.get(kind, {})
    return [(letter, attr, LABELS.get(attr, attr)) for letter, attr in bound.items()]


READ_ONLY = "{label} is read-only in the workbook -- change it in BidSheet.ai"


def check_export_values(book, line, base, problems):
    """Each export value of ``line`` that a formula reads must still equal
    ``base``, compared the way inputs are (15 significant digits; blank and
    None alike). A formula, or anything that is not a number, is a change."""
    ws = book.ws(line.sheet)
    for letter, attr, label in export_values(book, line.sheet, line.kind):
        cell = ws[f"{letter}{line.row}"]
        number, error = (None, "formula") if is_formula(cell) else parse_number(cell.value)
        expected = getattr(base, attr)
        if error is None and number_equal(
                number, None if expected is None else Decimal(str(expected))):
            continue
        problems.add(book.tab(line.sheet), line.row, letter, READ_ONLY.format(label=label))


# -- formula cells ---------------------------------------------------------------

def formula_cells(book, line):
    """The letters of ``line``'s cells the build filled with formulas: the
    declaration's entries for the kind, for every row (``*``), and for the
    qualifiers that hold (``KIND.stepped``, ``KIND.included``); a named
    figure's value cell when the row is declared a formula."""
    if line.kind is None:
        return ()
    sheet = book.decl.sheets[line.sheet]
    cols = tuple(sheet.formulas.get(line.kind, ())) + tuple(sheet.formulas.get("*", ()))
    if line.kind == "ITEM":
        item = book.model.item(line.id)
        if item is None or item.scope != "excluded":
            cols += tuple(sheet.formulas.get("ITEM.included", ()))
    if line.kind == "ACTIVITY" and line.occ is not None and line.occ.has_steps_marker:
        cols += tuple(sheet.formulas.get("ACTIVITY.stepped", ()))
    named = sheet.named_rows
    # A name is read only for kinds whose tags include it: the row is the
    # named row only when its kind is the one the declaration names.
    if (named and line.name in named.rows and named.rows[line.name].kind == line.kind
            and named.rows[line.name].formula):
        cols += (named.value_column,)
    # A derived tag (the owner tag of a step, resource, marker, crew member
    # or banner) is a chain formula the build writes; the reader never reads
    # it, so a value typed over it would otherwise pass in silence. A book
    # whose tags are stored constants (layout 2: 0.1.95 and 0.1.96, upgraded
    # in memory by the pack) carries a declaration that derives none.
    cols += tuple(t.column for t in sheet.tags.values() if line.kind in t.derived)
    return cols


LOST_REF = f"a formula here lost its reference (#REF!) -- undo the delete, or {REBUILD}"


def check_formulas(book, s, problems):
    """A constant (or nothing) where the writer put a formula refuses the read,
    every such cell named. So does any formula on a scanned sheet that lost
    its reference (``#REF!``: Excel's mark for a deleted row it pointed at)."""
    for key, sheet in book.decl.sheets.items():
        if sheet.role not in ("blocks", "flat"):
            continue
        for row in book.ws(key).iter_rows():
            for cell in row:
                if is_formula(cell) and "#REF!" in str(cell.value).upper():
                    problems.add(book.tab(key), cell.row, cell.column_letter, LOST_REF)
    for line in s.all_lines():
        ws, visible = book.ws(line.sheet), book.decl.sheets[line.sheet].columns
        for letter in formula_cells(book, line):
            cell = ws[f"{letter}{line.row}"]
            if is_formula(cell):
                continue
            now = "was cleared" if is_blank(cell.value) else "now holds a value"
            # A hidden column has no heading an estimator would know it by:
            # the location prefix (sheet, row, column) already names the cell.
            what = (heading(book, line.sheet, letter) if letter in visible
                    else "a hidden helper cell")
            problems.add(book.tab(line.sheet), line.row, letter,
                         f"{what} held a formula and {now} -- undo the edit, or copy the "
                         "formula back from a row of the same kind")
