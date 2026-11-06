"""HeavyBook's own part of a new baseline (``Pack.refresh_extras``), for a
patch after an apply and for a refresh: what the generic engine cannot know
about this layout.

- The Checks sheet: its "Exported from ... at ..." line, and the BidSheet.ai
  column of every Checks row the book has, matched against the figures a
  build from the fresh read model would write (``sheets.checks.figure_rows``)
  by the row its Excel formula reads (the Cost Report, Crews or Bid Form row
  and that row's kind and id), and by the row's kind, code, description and
  measure where no formula says (an as-of-export row). Lines share names
  across activities (a "Laborer" line in several), so the text alone never
  decides between rows that read alike: such a row is left as it is, with a
  note. A row with no figure now, and figures with no row, are notes: rows
  are never added or removed here.
- The cost shares: the ``_shares`` sheet holds each activity's share of each
  item as a constant fraction, so a change in the shares (an element
  quantity, an activity's elements or spread) is a change the book cannot
  take in place -- structural, for a refresh. A patch reports it as a note.

Known limit: the Cost Report's hidden figures a build computes from the
export stay as built -- an activity's cost and man-hours at export
(``AB``/``AC``), and for an activity whose crew is not on the Crews sheet its
labour and man-hours per shift (``AH``/``AI``), which price that activity. No
declaration can say how to recompute them; a rebuild does.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal

from openpyxl.utils.datetime import to_excel

from estimating_tools.exchange.reader.fields import number_equal, parse_number
from estimating_tools.exchange.types import RefreshExtras
from estimating_tools.exchange.reader.scan import norm_id
from estimating_tools.heavybook.columns import BF, CK, CR, CW
from estimating_tools.heavybook.layout import FIRST_ROW

__all__ = ["SHARES_CHANGED", "extras"]

SHARES_CHANGED = ("the cost shares between items changed in BidSheet.ai (an element quantity, "
                  "or an activity's elements or spread): the _shares sheet holds them as of "
                  "the build -- apply this book's edits, then rebuild it from BidSheet.ai")


def _shares(wb) -> list:
    return sorted((s.activity_id, s.item_id, s.element_id or 0, s.fraction) for s in wb.shares)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _cell(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(str(value))
    return value


#: Per sheet key, the hidden kind and id columns of the rows a Checks
#: formula reads, and the kinds ``checks.figure_rows`` names as targets.
_TARGET_CELLS = {"cost_report": (CR.KIND, CR.ID, ("ITEM", "ACTIVITY", "RESOURCE", "ELEMENT_QTY")),
                 "crews": (CW.KIND, CW.ID, ("CREW",)),
                 "bid_form": (BF.KIND, BF.ID, ("ITEM_BID",))}


def _target(book, formula):
    """``(tab, row kind, identity)`` of the row a book's Checks formula reads
    (as ``checks.figure_rows`` names it), or None."""
    from estimating_tools.heavybook.sheets.checks import referenced

    where = referenced(formula)
    if where is None:
        return None
    tab, row = where
    key = next((k for k in _TARGET_CELLS if k in book.decl.sheets and book.tab(k) == tab), None)
    if key is None or tab not in book.wb.sheetnames:
        return None
    kind_col, id_col, kinds = _TARGET_CELLS[key]
    ws = book.wb[tab]
    kind = _text(ws[f"{kind_col}{row}"].value)
    if kind not in kinds:
        return None
    ident = norm_id(ws[f"{id_col}{row}"].value)
    if kind == "ELEMENT_QTY":
        ident = (ident, _text(ws[f"{CR.KEY}{row}"].value))
    return tab, kind, ident


def _choose(entries, target, alike):
    """The figure entry for a book row: the one reading the same row
    (``target``), else the only one with the row's text when no other book
    row reads alike; None when there is none, or no telling which."""
    if target is not None and any(e[1] is not None for e in entries):
        found = [e for e in entries if e[1] == target]
        return found[0] if len(found) == 1 else None
    if len(entries) == 1 and alike == 1:
        return entries[0]
    return None


def extras(book, fresh, *, exported_at) -> RefreshExtras:
    """``book`` is the reader's opened book, ``fresh`` the parsed fresh read
    model; see the module docstring."""
    from estimating_tools.heavybook import style as hb_style
    from estimating_tools.heavybook.sheets import checks

    structural, notes, recalc = [], [], False
    if _shares(book.model) != _shares(fresh):
        structural.append(SHARES_CHANGED)
    table = (book.decl.navigator.get("tables") or {}).get("checks") or {}
    tab = table.get("sheet")
    if not tab or tab not in book.wb.sheetnames:
        return RefreshExtras(structural=structural, notes=notes)
    ws = book.wb[tab]
    out = {"A2": (f"Exported from {book.stamp.host} -- estimate {fresh.estimate.name} "
                  f"(#{fresh.estimate.id}) at {exported_at}")}
    try:
        entries = [(key, target, value, n) for n, (key, target, value)
                   in enumerate(checks.figure_rows(fresh, hb_style.load_style()))]
    except Exception as exc:  # noqa: BLE001 -- the figures inform; they never block a write
        notes.append(f"{tab}: the BidSheet.ai figures were not refreshed ({exc})")
        return RefreshExtras(cells={tab: out}, structural=structural, notes=notes)
    by_key = {}
    for entry in entries:
        by_key.setdefault(entry[0], []).append(entry)
    rows = []
    for r in range(FIRST_ROW, ws.max_row + 1):
        kind, measure = _text(ws[f"{CK.KIND}{r}"].value), _text(ws[f"{CK.MEASURE}{r}"].value)
        if not kind or not measure:
            continue                           # the warnings below the table, spacing
        key = (kind, _text(ws[f"{CK.CODE}{r}"].value), _text(ws[f"{CK.DESC}{r}"].value),
               measure)
        rows.append((r, key, _target(book, ws[f"{CK.EXCEL}{r}"].value)))
    alike = Counter(key for _r, key, _t in rows)
    used, undecided = set(), Counter()
    for r, key, target in rows:
        kind, measure = key[0], key[3]
        found = by_key.get(key, [])
        entry = _choose(found, target, alike[key])
        if entry is None:
            if found and target is None:
                undecided[key] += 1
                notes.append(f"{tab} row {r}: {kind} {key[2]!r} {measure} reads like another "
                             "row here, so its BidSheet.ai figure is left as built until a "
                             "rebuild")
            else:
                notes.append(f"{tab} row {r}: {kind} {key[2]!r} {measure} has no figure in "
                             "BidSheet.ai's estimate now; the row shows the build's until a "
                             "rebuild")
            continue
        used.add(entry[3])
        cell = ws[f"{CK.BIDSHEET}{r}"]
        if cell.data_type == "f":
            continue
        value = entry[2]
        current = cell.value
        if isinstance(current, (date, datetime)):
            current = to_excel(current)        # a finish date: the build wrote its serial
        number, error = parse_number(current)
        if error is None and number_equal(number, None if value is None
                                          else Decimal(str(value))):
            continue
        out[f"{CK.BIDSHEET}{r}"] = _cell(value)
        recalc = True
    left = Counter(e[0] for e in entries if e[3] not in used)
    missing = sum(max(0, n - undecided[key]) for key, n in left.items())
    if missing:
        notes.append(f"{tab}: {missing} figure(s) BidSheet.ai has now have no row; a rebuild "
                     "adds them")
    return RefreshExtras(cells={tab: out}, structural=structural, notes=notes, recalc=recalc)
