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
from estimating_tools.exchange.reader.scan import is_blank, is_formula, untouched_row, written


@dataclass(frozen=True)
class Input:
    """One bound input: ``field``, read by ``reader``, from the row's cell
    ``letter`` -- or from a binding form (``declaration.Binding``): the
    row's ``cells``, or the ``rows_column`` of its block's ``rows`` rows,
    joined by ``sep``; the rate the row's name picks (``from_rate``); a
    defined name's cell (``by_name``). ``clear``: BidSheet.ai accepts a
    cleared (null) value for this field (its "Explicit clears" list).
    ``attr``: the baseline attribute when it is not named like the field.
    ``spellings``: ``(book text, contract value)`` pairs for a coded field."""
    letter: str | None
    field: str
    reader: str
    clear: bool = False
    attr: str | None = None
    cells: tuple = ()
    rows: str | None = None
    rows_column: str | None = None
    sep: str | None = None
    from_rate: str | None = None
    by_name: str | None = None
    spellings: tuple = ()

    @property
    def base_attr(self):
        return self.attr or self.field

    @property
    def letters(self) -> tuple:
        """The cells of the row itself this input reads."""
        return (self.letter,) if self.letter is not None else self.cells


def form_of(line, kind) -> str:
    """The name ``line``'s inputs are declared under when it is read as a
    row of ``kind``: its form when it is tagged as one (fieldbook's CREW),
    else ``kind`` (a typed row; a pack without ``kinds:``)."""
    form = getattr(line, "form", None)
    return form if form and line.kind == kind else kind


def inputs_for_decl(decl, sheet, kind, *, stepped=False, form=None):
    """The bound inputs of ``kind`` (under ``form``, its tagged name) on
    ``sheet``: the contract's writable fields for the kind, each as the
    declaration binds it, in the contract table's field order (the
    declaration's own order is lost when the stamp sorts keys). A stepped
    activity loses the fields the contract marks stepless-only."""
    sh = decl.sheets[sheet]
    found = []
    for name, spec in contract.FIELDS.get(kind, {}).items():
        b = sh.binding(form or kind, name)
        if b is None:
            continue
        rows = b.rows is not None
        found.append(Input(None if rows else b.column, name, spec.reader, clear=spec.clear,
                           attr=spec.attr, cells=b.cells, rows=b.rows,
                           rows_column=b.column if rows else None, sep=b.sep,
                           from_rate=b.from_rate, by_name=b.by_name,
                           spellings=tuple(sorted((sh.spellings.get(name) or {}).items()))))
    if stepped:
        drop = contract.STEPLESS_ONLY.get(kind, ())
        found = [i for i in found if i.field not in drop]
    return tuple(found)


def inputs_for(book, sheet, kind, *, stepped=False, form=None):
    return inputs_for_decl(book.decl, sheet, kind, stepped=stepped, form=form)


def unbound(book, sheet, kind, form=None) -> tuple:
    """The contract's writable fields of ``kind`` that ``sheet`` binds to no
    column, in the contract's order. The book has no cell for them, so it
    cannot have changed them (#439, partial bindings)."""
    bound = book.decl.sheets[sheet].fields.get(form or kind, {})
    return tuple(name for name in contract.FIELDS.get(kind, {}) if name not in bound)


def carried(book, sheet, kind, source, form=None) -> dict:
    """What a copy (or a cut) of ``source``, a baseline row of ``kind``,
    takes from it for the fields ``sheet`` does not bind: the source's own
    values -- so the copy equals its source in what the book does not show.

    A blank value of a ``clear`` field is carried too, as the source holds
    it (None for a number; "" for a text or time unit, the model's blank and
    what a cleared cell of that field sends in an update), so the create
    does not depend on BidSheet.ai's create default for it. A blank value
    of any other field is left out: BidSheet.ai takes no null for it
    (``diff`` refuses such a clear), so the create's default stands."""
    out = {}
    for name in unbound(book, sheet, kind, form):
        spec = contract.FIELDS[kind][name]
        value = getattr(source, spec.attr or name, None)
        if spec.clear or (value is not None and value != ""):
            out[name] = value
    return out


def bound_or_kept(values, kept, kind, name):
    """``values[name]`` when the sheet binds ``name`` (``read_line`` reads
    only the bound fields), else ``kept``'s own value -- the baseline row
    the line is, or the one it was copied from; None for neither (#439).
    ``kept``'s value is read through the contract's ``attr`` for ``kind``'s
    field, as ``diff`` and ``carried`` read it."""
    if name in values:
        return values[name]
    if kept is None:
        return None
    return getattr(kept, contract.FIELDS[kind][name].attr or name)


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
    # The book's own spelling of a choice (fieldbook's "Subcontract").
    text = next((v for k, v in inp.spellings if k.casefold() == text.casefold()), text)
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
    ``kind`` is blank or holds its row's written text (fieldbook's DAYS on
    a crew row), and so is every other visible cell bar formulas
    (``scan.untouched_row``): a value typed anywhere visible makes the row
    touched, and the new row's requirements then apply."""
    ws, form = book.ws(line.sheet), form_of(line, kind)
    fixed = written(book.decl, line.sheet, form)

    def blank(letter):
        value = ws[f"{letter}{line.row}"].value
        return is_blank(value) or (letter in fixed and str(value).strip() == fixed[letter])

    return (untouched_row(book.decl, ws, line.row, line.sheet, form)
            and all(blank(letter)
                    for inp in inputs_for(book, line.sheet, kind, stepped=stepped, form=form)
                    for letter in inp.letters))


FORMULA_INPUT = "this input holds a formula -- type a value instead"
NO_RATE = ("no rate named {name!r} on the Rates sheet -- pick one from the dropdown, or add "
           "a local rate row")
NO_RATE_TYPED = ("local rate {name!r} has no Rate typed (its breakdown is not read) -- type "
                 "its Rate")


def _joined(ws, cells, sep):
    """``(text, error, (row, column))``: ``cells`` (``(row, letter)`` each)
    read as text, the blank ones skipped, joined by ``sep``."""
    parts = []
    for row, letter in cells:
        cell = ws[f"{letter}{row}"]
        if is_formula(cell):
            return None, FORMULA_INPUT, (row, letter)
        if not is_blank(cell.value):
            parts.append(str(cell.value).strip())
    return sep.join(parts), None, None


def read_input(book, line, inp):
    """``(value, error, (tab, row, column))``: one input of ``line`` -- a
    cell of the row, cells or block rows joined, or a defined name's cell
    -- in BidSheet.ai's spelling. ``from_rate`` inputs are ``read_line``'s."""
    ws, tab = book.ws(line.sheet), book.tab(line.sheet)
    if inp.letter is not None:
        value, error = read_value(inp, ws[f"{inp.letter}{line.row}"])
        return value, error, (tab, line.row, inp.letter)
    if inp.cells or inp.rows is not None:
        if inp.cells:
            cells = [(line.row, letter) for letter in inp.cells]
        else:
            rows = line.occ.joined.get(inp.rows, ()) if line.occ is not None else ()
            cells = [(x.row, inp.rows_column) for x in rows]
        value, error, at = _joined(ws, cells, inp.sep)
        if error:
            return None, error, (tab, *at)
        return value, None, (tab, line.row, inp.cells[0] if inp.cells else None)
    found = book.named_cell(inp.by_name)
    if found is None:
        return None, f"the defined name {inp.by_name} is gone -- {REBUILD}", (tab, line.row,
                                                                               None)
    named_ws, coord = found
    cell = named_ws[coord]
    value, error = read_value(inp, cell)
    return value, error, (named_ws.title, cell.row, cell.column_letter)


def _from_rate(inp, picked, typed, where):
    """``(value, error, where)``: the kind or the rate of ``picked``, the
    rate the row's name ``typed`` picks; nothing for a blank name."""
    if typed is None:
        return None, None, where
    if picked is None:
        return None, NO_RATE.format(name=typed), where
    if inp.from_rate == "kind":
        return picked.kind, None, where
    number, error = parse_number(picked.rate)
    if error is not None or number is None:
        return None, NO_RATE_TYPED.format(name=picked.name), where
    return number, None, where


def read_line(book, line, kind, *, stepped=False) -> Read:
    """Read ``line``'s inputs as a row of ``kind``. Cached on the line by
    ``(kind, stepped)``: a typed row may be read as more than one kind, and
    an activity with and without its Shifts input. A row whose rate its
    name picks (``from_rate``) reads its name first (the contract's field
    order puts it first), then the rate's kind and rate; its name is read
    without a local rate's suffix."""
    reads, key = _reads(line), (kind, stepped)
    if key in reads:
        return reads[key]
    result = Read()
    inputs = inputs_for(book, line.sheet, kind, stepped=stepped, form=form_of(line, kind))
    picks = any(inp.from_rate for inp in inputs)
    picked, typed, name_at = None, None, (book.tab(line.sheet), line.row, None)
    for inp in inputs:
        if inp.from_rate:
            value, error, where = _from_rate(inp, picked, typed, name_at)
        else:
            value, error, where = read_input(book, line, inp)
            if picks and inp.field == "name" and error is None and value is not None:
                typed, name_at = value, where
                picked = book.rate_table.find(value)
                value = book.rate_table.plain_name(value, picked)
        if error:
            tab, row, letter = where
            label = (heading(book, line.sheet, letter) if letter and tab == book.tab(line.sheet)
                     else inp.field.replace("_", " "))
            result.problems.append(Problem(tab, row, letter, message(label, error)))
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
    (before, after)}``. A clear BidSheet.ai cannot take is a problem. The
    fields a row's name picks from the rates sheet (``from_rate``) are not
    compared when the name is blank or unreadable: the name's own problem
    is the row's one problem (they are not marked ``bad``, which would stop
    a new row's create from naming what it lacks)."""
    read = read_line(book, line, kind, stepped=stepped)
    inputs = inputs_for(book, line.sheet, kind, stepped=stepped, form=form_of(line, kind))
    no_name = read.values.get("name") is None or "name" in read.bad
    changes = {}
    for inp in inputs:
        if inp.field not in read.values or inp.field in read.bad:
            continue
        if inp.from_rate and no_name:
            continue
        after = read.values[inp.field]
        before = getattr(base, inp.base_attr)
        if same(inp, after, before):
            continue
        if after is None and not inp.clear:
            letter = (inp.letters or (None,))[0]
            label = heading(book, line.sheet, letter) if letter else inp.field.replace("_", " ")
            problems.add(book.tab(line.sheet), line.row, letter,
                         f"{label} can't be cleared -- type a value")
            continue
        changes[inp.field] = (before, after)
    return changes


def equal_to_base(book, line, kind, base, *, stepped=False) -> bool:
    """Every input of ``line`` reads cleanly and equals ``base``."""
    read = read_line(book, line, kind, stepped=stepped)
    if not read.ok:
        return False
    return all(same(inp, read.values[inp.field], getattr(base, inp.base_attr))
               for inp in inputs_for(book, line.sheet, kind, stepped=stepped,
                                     form=form_of(line, kind)))


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
    for letter, attr, label in export_values(book, line.sheet, line.form or line.kind):
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
    form = line.form or line.kind
    cols = tuple(sheet.formulas.get(form, ())) + tuple(sheet.formulas.get("*", ()))
    if line.kind == "ITEM":
        item = book.model.item(line.id)
        if item is None or item.scope != "excluded":
            cols += tuple(sheet.formulas.get(f"{form}.included", ()))
    if line.kind == "ACTIVITY" and line.occ is not None and line.occ.has_steps_marker:
        cols += tuple(sheet.formulas.get(f"{form}.stepped", ()))
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
