"""The Rates sheet is read-only: every row must still match the baseline.

A crew member without a rate override takes its library rate from this sheet
by lookup (``formulas.member_library_rate``), so a typed rate would reprice
the book's crews while BidSheet.ai kept the library rate. Any changed, added,
deleted or reordered Rates row refuses the read; the cure is a member's Rate
override on the Crews sheet, which is stored on this estimate only.

The sheet is the declaration's ``rates`` sheet: its ``columns_by_key`` name
the id, name, unit and rate columns, its ``sections`` each kind's title. A
declaration without one has nothing to check.

Cells are compared the way ``fields`` compares inputs, so an unedited sheet
never refuses: numbers to 15 significant digits (Excel's float noise), text
trimmed, blank and "" alike, ids as ``norm_id`` reads them. Fully blank rows
are skipped (the writer leaves one after each section), and so is the
headings row under each title unless a rate was typed over it. Each section
title counts once, in the writer's order; a repeated title is a changed row,
and a missing or misplaced one is one problem rather than one per row.

A tagged rates sheet (fieldbook's: a ``ref`` tag) is read by its RATE rows
only -- each must still be its baseline library rate, and every library
rate of a shown kind must have one; its untagged rows are the book's local
rates and are not read here. ``table`` reads both kinds of row for the crew
rows that pick a rate by name (``fields``' ``from_rate``).
"""
from __future__ import annotations

from dataclasses import dataclass

from estimating_tools.exchange import contract
from estimating_tools.exchange.reader.fields import number_equal, parse_number
from estimating_tools.exchange.reader.scan import is_blank, norm_id

READ_ONLY = ("library rates are read-only: set the member's Rate override on the "
             "Crews sheet instead")

#: A tagged rates sheet's library rows.
TAGGED_READ_ONLY = "library rates are read-only -- add a local rate row instead"


@dataclass(frozen=True)
class RateRow:
    """One rate of a tagged rates sheet: a library row (``tagged``, its
    link ``labor:<id>``) or a local one; ``kind`` the contract rate kind its
    Kind cell names (None when it names none); ``rate`` the rate cell's value."""
    row: int
    name: str
    kind: str | None
    rate: object
    tagged: bool
    link: str | None


class RateTable:
    """A tagged rates sheet's rates, as a crew row's name picks one: the
    first whose name equals it, ignoring case -- Excel's VLOOKUP."""

    def __init__(self, key, rows, suffix):
        self.key, self.rows, self.suffix = key, list(rows), suffix

    def find(self, name):
        if name is None:
            return None
        wanted = str(name).strip().casefold()
        return next((r for r in self.rows if r.name.casefold() == wanted), None)

    def plain_name(self, name, picked):
        """``name`` as BidSheet.ai holds it: the declared suffix dropped when
        the rate it picks is a local one (a local rate a library rate shares
        a name with is shown suffixed, decision 6 of the delivery-1 plan)."""
        if (self.suffix and picked is not None and not picked.tagged
                and name.endswith(self.suffix)):
            return name[: -len(self.suffix)]
        return name

#: The declaration's column keys, in the order a row's cells are compared.
_KEYS = ("id", "name", "unit", "rate")


def _rates_sheet(decl):
    """``(key, Sheet)`` of the declaration's rates sheet, or ``(None, None)``."""
    return next(((k, s) for k, s in decl.sheets.items() if s.role == "rates"), (None, None))


def _text(value) -> str:
    return "" if is_blank(value) else str(value).strip()


def _matches(cells, rate) -> bool:
    rid, name, unit, value = cells
    number, error = parse_number(value)
    return (norm_id(rid) == norm_id(rate.id) and _text(name) == _text(rate.name)
            and _text(unit) == _text(rate.unit)
            and error is None and number_equal(number, rate.rate))


def _title(cells, kind_by_title):
    """The section kind a title row names, or None."""
    title = _text(cells[0])
    if title in kind_by_title and all(is_blank(c) for c in cells[1:]):
        return kind_by_title[title]
    return None


def _looks_like_rate(cells) -> bool:
    """An int id and a numeric rate: never the headings row under a title."""
    number, error = parse_number(cells[3])
    return isinstance(norm_id(cells[0]), int) and error is None and number is not None


def _rows(ws, letters):
    for r in range(1, ws.max_row + 1):
        cells = tuple(ws[f"{col}{r}"].value for col in letters)
        if not all(is_blank(c) for c in cells):
            yield r, cells


def rate_rows(book) -> dict:
    """``{(rate kind, id): row}`` of the declaration's rates sheet, read the
    way ``check`` reads it (section titles, then rows with an int id and a
    numeric rate); empty when the declaration has no rates sheet."""
    key, sheet = _rates_sheet(book.decl)
    if sheet is None:
        return {}
    letters = tuple(sheet.columns_by_key[k] for k in _KEYS)
    kind_by_title = {title: kind for kind, title in sheet.sections.items()}
    out, kind = {}, None
    for r, cells in _rows(book.ws(key), letters):
        title = _title(cells, kind_by_title)
        if title:
            kind = title
            continue
        if kind and _looks_like_rate(cells):
            out[(kind, norm_id(cells[0]))] = r
    return out


def _is_tagged(sheet) -> bool:
    return sheet is not None and sheet.tag("ref") is not None


def table(book):
    """The declaration's tagged rates sheet as a ``RateTable``, or None.
    A row is a rate when it carries a name and either the RATE tag or a
    Kind a section names; the heading row, the shift row and the
    insert-above marker carry neither."""
    key, sheet = _rates_sheet(book.decl)
    if not _is_tagged(sheet):
        return None
    ws, cols = book.ws(key), sheet.columns_by_key
    kind_col, ref_col = sheet.tag("kind"), sheet.tag("ref")
    by_title = {title.casefold(): kind for kind, title in sheet.sections.items()}
    rows = []
    for r in range(sheet.first_row, ws.max_row + 1):
        name = ws[f"{cols['name']}{r}"].value
        kind = by_title.get(_text(ws[f"{cols['kind']}{r}"].value).casefold())
        tagged = _text(ws[f"{kind_col}{r}"].value) == contract.RATE_ROW
        if is_blank(name) or (kind is None and not tagged):
            continue
        link = (_text(ws[f"{ref_col}{r}"].value) or None) if tagged else None
        rows.append(RateRow(r, _text(name), kind, ws[f"{cols['rate']}{r}"].value, tagged, link))
    return RateTable(key, rows, sheet.local_suffix)


def _check_tagged(book, key, sheet, problems):
    """Each RATE row is still its baseline library rate -- name, kind and
    rate -- named once; each library rate of a shown kind has its row. The
    order is not checked: a crew row picks its rate by name."""
    tab = book.tab(key)
    expected = {rate.link: rate for kind in sheet.sections
                for rate in book.model.rates_by_kind(kind)}
    seen = set()
    for row in table(book).rows:
        if not row.tagged:
            continue
        rate = expected.get(row.link)
        if rate is None or row.link in seen:
            problems.add(tab, row.row, None, f"this library rate row was added -- "
                                             f"{TAGGED_READ_ONLY}")
            continue
        # Seen before it is compared: a changed row is one problem, not
        # also a deleted rate.
        seen.add(row.link)
        number, error = parse_number(row.rate)
        if (row.name != _text(rate.name) or row.kind != rate.kind or error is not None
                or not number_equal(number, rate.rate)):
            problems.add(tab, row.row, None, f"this library rate row was changed -- "
                                             f"{TAGGED_READ_ONLY}")
    for link, rate in expected.items():
        if link not in seen:
            problems.add(tab, None, None, f"{rate.kind} rate {rate.id} ({rate.name}) was "
                                          f"deleted -- {TAGGED_READ_ONLY}")


def check(book, problems):
    key, sheet = _rates_sheet(book.decl)
    if sheet is None:
        return
    if _is_tagged(sheet):
        _check_tagged(book, key, sheet, problems)
        return
    letters = tuple(sheet.columns_by_key[k] for k in _KEYS)
    # The sections in the contract's rate-kind order (the writer lays them
    # out that way; the stamp sorts the declaration's keys), the kinds the
    # declaration does not list left out.
    kinds = [k for k in contract.RATE_KINDS if k in sheet.sections]
    kind_by_title = {sheet.sections[k]: k for k in kinds}
    ws, tab = book.ws(key), book.tab(key)
    rows = list(_rows(ws, letters))
    # A missing or misplaced section title: one problem, not one per row under it.
    titles = []
    for _r, cells in rows:
        kind = _title(cells, kind_by_title)
        if kind and kind not in titles:
            titles.append(kind)
    if titles != kinds:
        for kind in kinds:
            if kind not in titles or titles.index(kind) != kinds.index(kind):
                problems.add(tab, None, None, f"the {kind} section title was changed or "
                                              f"deleted -- {READ_ONLY}")
                break
        return
    expected = {kind: list(book.model.rates_by_kind(kind)) for kind in kinds}
    index = {kind: {rate.id: n for n, rate in enumerate(left)}
             for kind, left in expected.items()}
    seen = {kind: [] for kind in kinds}     # (row, baseline index) of matched rows
    kind, heading_next, entered = None, False, set()
    for r, cells in rows:
        title = _title(cells, kind_by_title)
        if title and title not in entered:    # a repeated title is a changed row
            kind, heading_next = title, True
            entered.add(title)
            continue
        if heading_next:
            heading_next = False
            # The headings row under a title (labels; their text follows the
            # build's style). A rate typed over it, or a deleted headings row
            # that brought a rate row up, is read as a rate row.
            if not _looks_like_rate(cells):
                continue
        rate = next((x for x in expected.get(kind, ()) if _matches(cells, x)), None)
        if rate is None:
            problems.add(tab, r, None, f"this rate row was changed or added -- {READ_ONLY}")
            continue
        expected[kind].remove(rate)
        seen[kind].append((r, index[kind][rate.id]))
    for kind, matched in seen.items():
        order = [n for _row, n in matched]
        if order != sorted(order):
            row = next(matched[k][0] for k in range(1, len(order))
                       if order[k] < order[k - 1])
            problems.add(tab, row, None, f"the {kind} rate rows were reordered -- {READ_ONLY}")
    for kind, left in expected.items():
        for rate in left:
            problems.add(tab, None, None,
                         f"{kind} rate {rate.id} ({rate.name}) was deleted -- {READ_ONLY}")
