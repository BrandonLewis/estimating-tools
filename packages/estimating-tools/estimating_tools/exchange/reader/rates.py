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
"""
from __future__ import annotations

from estimating_tools.exchange import contract
from estimating_tools.exchange.reader.fields import number_equal, parse_number
from estimating_tools.exchange.reader.scan import is_blank, norm_id

READ_ONLY = ("library rates are read-only: set the member's Rate override on the "
             "Crews sheet instead")

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


def check(book, problems):
    key, sheet = _rates_sheet(book.decl)
    if sheet is None:
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
