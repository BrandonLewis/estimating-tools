"""Helpers for the read-back tests: build the fixture book, edit it the way
Excel would (insert, copy, cut, delete rows), save, read it back."""
from __future__ import annotations

import json
import types
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.formula.translate import Translator

from estimating_tools.heavybook.columns import CR, CW

FIXTURE = Path(__file__).parent / "fixtures" / "workbook.json"
CR_TAB, CW_TAB, BF_TAB, RT_TAB = "Cost Report", "Crews", "Bid Form", "Rates"


_SML = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _without_cached_values(part: bytes) -> bytes:
    root = ET.fromstring(part)
    for c in root.iter(f"{_SML}c"):
        if c.find(f"{_SML}f") is not None:
            for v in c.findall(f"{_SML}v"):
                c.remove(v)
            c.attrib.pop("t", None)
    return ET.tostring(root)


def changed_beyond_cached_values(before: dict, after: dict) -> set:
    """Parts that differ between two packages (``{name: bytes}``) in more
    than the cached values of formula cells, which every save and patch
    rewrites (#370)."""
    changed = set()
    for name in before:
        if before[name] == after.get(name):
            continue
        if name.startswith("xl/worksheets/") and name.endswith(".xml") and name in after                 and _without_cached_values(before[name]) == _without_cached_values(after[name]):
            continue
        changed.add(name)
    return changed


def fixture_doc():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


#: Fixture fields newer than the committed regression books, which are an
#: earlier release's output, committed untouched: the read gained these in
#: BidSheet.ai #1622, after those books were built.
FIXTURE_FIELDS_SINCE_OLD_BOOKS = {("estimate", "project", "display_project_id"),
                                  ("estimate", "project", "project_reference")}


def _has_path(doc: dict, path: tuple) -> bool:
    *parents, leaf = path
    for key in parents:
        doc = doc[key]
    return leaf in doc


def fixture_doc_as_of_old_books():
    """The fixture without ``FIXTURE_FIELDS_SINCE_OLD_BOOKS``."""
    doc = fixture_doc()
    for path in FIXTURE_FIELDS_SINCE_OLD_BOOKS:
        *parents, leaf = path
        node = doc
        for key in parents:
            node = node[key]
        del node[leaf]
    return doc


def assert_old_book_doc(doc: dict) -> None:
    """An old book's baseline is the fixture as of its release: it lacks the
    newer fields (so the exception hides nothing) and equals the rest."""
    for path in FIXTURE_FIELDS_SINCE_OLD_BOOKS:
        assert not _has_path(doc, path), path
    assert doc == fixture_doc_as_of_old_books()


def linked_doc():
    """The fixture with resource 1 (CAT 336) linked to equipment rate 7."""
    doc = fixture_doc()
    doc["rates"]["equipment"].append({"id": 7, "name": "CAT 336", "unit": "HR",
                                      "rate": "185.00"})
    for res in doc["resources"]:
        if res["id"] == 1:
            res["equipment_rate_id"] = 7
    return doc


def edge_doc():
    """The fixture with two activities whose crews the export does not carry
    (one library-crew activity priced per shift, one with no shifts), a
    BidSheet.ai warning, an element quantity paying no item, and one bid
    total over every schedule that is not marked primary."""
    doc = fixture_doc()
    for a in doc["activities"]:
        if a["id"] == 5:
            a["warnings"] = ["No production rate"]
        if a["id"] == 6:
            a["crew_id"] = 99
        if a["id"] == 7:
            a.update(crew_id=98, duration_shifts=None)
    doc["elements"][1]["quantities"][0]["pay_item_id"] = None
    doc["estimate"]["bid_totals"] = [
        {"amount": "100.00", "display_order": 0, "id": 3, "includes_unscheduled": False,
         "is_primary": False, "name": "All schedules", "schedule_ids": None}]
    return doc


def implicit_doc():
    """The fixture with no bid total definitions: the implicit total."""
    doc = fixture_doc()
    doc["estimate"]["bid_totals"] = []
    return doc


FIRST_ROW = 5
AT = "2026-10-20T09:00:00Z"


def build_book(doc, path):
    """Build ``doc`` with the heavybook pack (the template fill) and save it
    to ``path``; returns ``path``."""
    from estimating_tools.heavybook import pack as hb_pack

    hb_pack.pack().build(doc, Path(path), options={"exported_at": AT, "host": "www.bidsheet.ai"})
    return Path(path)


def build_wb(doc, tmp_path, name="built.xlsx"):
    """The built book, opened (formulas, not values)."""
    return load_workbook(build_book(doc, Path(tmp_path) / name))


TEMPLATES = "_templates"          # the template's prototype rows (hidden)


def evaluate(book, tmp_path, name="eval.xlsx") -> dict:
    """``{"Sheet!A1": value}`` for an openpyxl book, computed by xlcalc (the
    engine every build caches its values with). An Excel error is its text
    (``"#REF!"``). A formula xlcalc cannot evaluate raises ``AssertionError``
    naming the cell -- a None would read as 0 through the tests' number
    helpers and pass an assertion vacuously -- except on ``_templates``,
    whose prototype rows read their own blank id tags (None there)."""
    from estimating_tools.xlcalc.book import Book
    from estimating_tools.xlcalc.evaluate import Failed, evaluate as xl
    from estimating_tools.xlcalc.values import Err

    path = Path(tmp_path) / name
    book.save(path)
    results = xl(Book.load(path))
    out = {}
    for ws in load_workbook(path).worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = results.get((ws.title, c.row, c.column), c.value)
                if isinstance(v, Err):
                    v = v.code
                if isinstance(v, Failed):
                    if ws.title != TEMPLATES:
                        raise AssertionError(f"xlcalc could not evaluate {ws.title}!"
                                             f"{c.coordinate} ({c.value}): {v.reason}")
                    v = None
                out[f"{ws.title}!{c.coordinate}"] = v
    return out


class _At:
    def __init__(self, row):
        self.row = row


def plan_of(book):
    """The Cost Report's, Crews' and Bid Form's rows by id, under the names
    the code build's layout plan gave them (``plan.activity_rows[id].row``,
    ``plan.resource_span[id]`` ...), read from the book's tags."""
    p = types.SimpleNamespace(item_rows={}, activity_rows={}, resource_rows={}, step_rows={},
                              quantity_rows={}, resource_span={}, step_span={}, crew_rows={},
                              member_rows={}, crew_span={}, bid_rows={})
    cr = book[CR_TAB]
    current = steps = start = None
    for r in range(FIRST_ROW, cr.max_row + 1):
        kind, ident = cr[f"{CR.KIND}{r}"].value, cr[f"{CR.ID}{r}"].value
        if kind == "ITEM":
            p.item_rows[ident] = _At(r)
        elif kind == "ACTIVITY":
            p.activity_rows[ident], current, steps = _At(r), ident, None
        elif kind == "RESOURCE":
            p.resource_rows[ident] = _At(r)
        elif kind == "STEP":
            p.step_rows[ident] = _At(r)
        elif kind == "ELEMENT_QTY":
            p.quantity_rows[(ident, cr[f"{CR.KEY}{r}"].value)] = _At(r)
        elif kind == "STEPS":
            steps = r
        elif kind == "START":
            start = r
            if steps is not None:
                p.step_span[current] = (steps, r)
        elif kind == "END":
            p.resource_span[current] = (start, r)
    cw = book[CW_TAB]
    crew = None
    for r in range(FIRST_ROW, cw.max_row + 1):
        kind, ident = cw[f"{CW.KIND}{r}"].value, cw[f"{CW.ID}{r}"].value
        if kind == "CREW":
            p.crew_rows[ident], crew = _At(r), (ident, r)
        elif kind == "MEMBER":
            p.member_rows[ident] = _At(r)
        elif kind == "CREW_END" and crew is not None:
            p.crew_span[crew[0]] = (crew[1], r)
    bf = book[BF_TAB]
    for r in range(1, bf.max_row + 1):
        if bf[f"J{r}"].value == "ITEM_BID":
            p.bid_rows[bf[f"K{r}"].value] = _At(r)
    return p


def open_book(path):
    return load_workbook(path)


def save_book(wb, path):
    wb.save(path)
    return Path(path)


#: The owner kind of a sheet's blocks, by its kind column.
_OWNER_KIND = {CR.KIND: "ACTIVITY", CW.KIND: "CREW"}
#: Rows that end an owner's block on the Cost Report (an activity's rows
#: sit under an item).
_CONTAINERS = ("ITEM", "GROUP")


def find_row(ws, kind, ident=None, *, kind_col=CR.KIND, id_col=CR.ID, parent=None,
             parent_col=CR.PARENT, start=1):
    """The first row at or after ``start`` of ``kind`` (with id ``ident`` when
    given). With ``parent``, the row is found by position in the owner's
    block: the owner row (an ACTIVITY, a CREW) with id ``parent`` first,
    then the first ``kind`` row at or after it before the next owner row or
    a container row. (A block row's owner tag is a chain formula, so
    ``parent_col`` is not read.)"""
    if parent is None:
        for r in range(start, ws.max_row + 1):
            if ws[f"{kind_col}{r}"].value != kind:
                continue
            if ident is not None and ws[f"{id_col}{r}"].value != ident:
                continue
            return r
        raise LookupError(f"no {kind} row (id {ident})")
    owner_kind = _OWNER_KIND[kind_col]
    owner = next((r for r in range(start, ws.max_row + 1)
                  if ws[f"{kind_col}{r}"].value == owner_kind
                  and ws[f"{id_col}{r}"].value == parent), None)
    if owner is None:
        raise LookupError(f"no {owner_kind} row with id {parent} at or after row {start}")
    for r in range(owner, ws.max_row + 1):
        found = ws[f"{kind_col}{r}"].value
        if r > owner and (found == owner_kind or found in _CONTAINERS):
            break
        if found == kind and (ident is None or ws[f"{id_col}{r}"].value == ident):
            return r
    raise LookupError(f"no {kind} row (id {ident}) in {owner_kind} {parent}'s block "
                      f"(row {owner})")


def cr_row(ws, kind, ident=None, *, parent=None, start=1):
    return find_row(ws, kind, ident, parent=parent, start=start)


def cw_row(ws, kind, ident=None, *, parent=None):
    return find_row(ws, kind, ident, kind_col=CW.KIND, id_col=CW.ID, parent=parent,
                    parent_col=CW.CREW)


def block_end(ws, activity_id):
    """The END marker row of ``activity_id``'s first block."""
    return cr_row(ws, "END", parent=activity_id)


def owner_formula(row):
    """The Cost Report owner tag a step, resource or marker row holds."""
    return f"=INDEX(${CR.ID}:${CR.ID},MAX(${CR.ACT}{row},1))"


def crew_formula(row):
    """The Crews crew tag a member, banner or end row holds."""
    return f"=INDEX(${CW.ID}:${CW.ID},MAX(${CW.OWNER}{row},1))"


def crew_row_formula(row, header=4):
    """The hidden crew-row helper (``R``) every Crews data row holds."""
    return (f'=IF(${CW.KIND}{row}="CREW",ROW(),'
            f"MAX({CW.OWNER}${header}:{CW.OWNER}{row - 1}))")


def copy_row(ws, src, dst):
    """Copy row ``src`` onto row ``dst`` the way Excel's copy does: values as
    they are, formulas translated by the row offset."""
    for col in range(1, ws.max_column + 1):
        s, d = ws.cell(row=src, column=col), ws.cell(row=dst, column=col)
        if s.data_type == "f" and isinstance(s.value, str):
            d.value = Translator(s.value, origin=s.coordinate).translate_formula(d.coordinate)
        else:
            d.value = s.value
            if isinstance(s.value, str):
                d.data_type = s.data_type


def shift_references(wb, sheet, at, count):
    """Shift every reference into ``sheet`` at or below row ``at`` down by
    ``count``, as Excel's whole-row insert does: the formulas on every sheet
    and the defined names, through ``exchange.refs.insert`` -- the shifter the
    exchange writer's row ops use. openpyxl's ``insert_rows`` moves cells and
    never rewrites a formula, so without this a formula below the insert
    reads the rows it read before."""
    from openpyxl.worksheet.formula import ArrayFormula

    from estimating_tools.exchange import refs

    order = wb.sheetnames

    def moved(body, own):
        return refs.insert(body, sheet=sheet, own=own, at=at, count=count, sheets=order)

    for ws in wb.worksheets:
        own = ws.title == sheet
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, ArrayFormula):
                    v.text = "=" + moved(v.text.lstrip("="), own)
                elif c.data_type == "f" and isinstance(v, str) and v.startswith("="):
                    c.value = "=" + moved(v[1:], own)
    scopes = [wb.defined_names] + [ws.defined_names for ws in wb.worksheets]
    for names in scopes:
        for dn in names.values():
            if dn.attr_text:
                dn.attr_text = moved(dn.attr_text, False)


def insert_copies(ws, first, last, before):
    """Insert copies of rows ``first..last`` above row ``before`` (Excel's
    "Insert Copied Cells"). Returns the first inserted row. ``before`` may
    fall inside ``first..last``: Excel copies the range as it was, so each
    source row below the insert is read from where the insert pushed it.
    Every reference into the sheet below the insert shifts with it
    (``shift_references``), so a formula further down still reads its rows."""
    n = last - first + 1
    shift_references(ws.parent, ws.title, before, n)
    _insert_copies_unshifted(ws, first, last, before)
    return before


def _insert_copies_unshifted(ws, first, last, before):
    n = last - first + 1
    ws.insert_rows(before, n)
    for k in range(n):
        src = first + k
        copy_row(ws, src + n if src >= before else src, before + k)
    return before


def cut_rows(ws, first, last, before):
    """Move rows ``first..last`` above row ``before`` (Excel's "Insert Cut
    Cells"). Returns the row the block now starts on. References are not
    shifted: openpyxl's insert and delete move cells only, so a formula
    below both ends of the move reads its rows as before."""
    n = last - first + 1
    _insert_copies_unshifted(ws, first, last, before)
    if first >= before:
        first += n
    ws.delete_rows(first, n)
    return before if before < first else before - n


def type_row(ws, before, values):
    """Insert a blank row above ``before`` and type ``{letter: value}`` in it."""
    ws.insert_rows(before)
    for letter, value in values.items():
        ws[f"{letter}{before}"] = value
    return before


def read(path):
    """The generic reader with the HeavyBook pack, as the CLI reads."""
    from estimating_tools.exchange.reader import read_book
    from estimating_tools.heavybook.pack import pack
    return read_book(path, pack=pack())


def ops_named(cs, name):
    return [op for op in cs.ops if op["op"] == name]


def template_rows(wb, name):
    """``(first, last)``: the ``_templates`` rows the defined name ``name``
    (``hc.tpl.*``, a whole-row reference such as ``'_templates'!$9:$14``)
    covers."""
    first, last = wb.defined_names[name].attr_text.split("!")[1].replace("$", "").split(":")
    return int(first), int(last)


def insert_template(wb, name, sheet, at):
    """Estimate Navigator's Insert: the ``name`` prototype rows inserted at row
    ``at`` of ``sheet`` (a tab title), as the add-in does it -- a whole-row
    insert, then Excel's copy. Returns ``at``."""
    from estimating_tools.estimate_spec.tests._fieldbook import paste_template_rows

    first, last = template_rows(wb, name)
    paste_template_rows(wb, first, last, sheet, at)
    return at
