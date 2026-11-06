"""Helpers for the read-back tests: build the fixture book, edit it the way
Excel would (insert, copy, cut, delete rows), save, read it back."""
from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from openpyxl.formula.translate import Translator

from estimating_tools.heavybook import build, style
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


def linked_doc():
    """The fixture with resource 1 (CAT 336) linked to equipment rate 7."""
    doc = fixture_doc()
    doc["rates"]["equipment"].append({"id": 7, "name": "CAT 336", "unit": "HR",
                                      "rate": "185.00"})
    for res in doc["resources"]:
        if res["id"] == 1:
            res["equipment_rate_id"] = 7
    return doc


def build_book(doc, path):
    """Build ``doc`` and save it to ``path``; returns ``path``."""
    book = build.build(doc, style=style.load_style(), exported_at="2026-10-20T09:00:00Z",
                       host="www.bidsheet.ai")
    build.save(book, path)
    return Path(path)


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


def insert_copies(ws, first, last, before):
    """Insert copies of rows ``first..last`` above row ``before`` (Excel's
    "Insert Copied Cells"). Returns the first inserted row. ``before`` may
    fall inside ``first..last``: Excel copies the range as it was, so each
    source row below the insert is read from where the insert pushed it."""
    n = last - first + 1
    ws.insert_rows(before, n)
    for k in range(n):
        src = first + k
        copy_row(ws, src + n if src >= before else src, before + k)
    return before


def cut_rows(ws, first, last, before):
    """Move rows ``first..last`` above row ``before`` (Excel's "Insert Cut
    Cells"). Returns the row the block now starts on."""
    n = last - first + 1
    insert_copies(ws, first, last, before)
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
