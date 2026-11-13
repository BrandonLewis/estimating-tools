"""#439: a declaration that binds only part of a kind's writable fields.
A growable kind binds what a new row is created from
(``contract.CREATE_NEEDS``), or the loader refuses it; every other field may
be left unbound, and the reader never reaches for its cell. A copy (or a
cut) takes an unbound field from its source -- the book cannot have
changed what it has no cell for -- a new step takes a blank unit's reading,
and a crew roster keeps each member's unbound values. The test pack is
``_template``'s mini-book, which binds no resource ``unit`` or time, no
step ``duration_unit`` and no activity production."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.template import TemplatePack
from estimating_tools.exchange.tests import _template as T
from estimating_tools.heavybook.tests import _readback as H

AT = "2026-11-07T09:00:00Z"


def _book(tmp_path, change=None, doc=None):
    decl = copy.deepcopy(T.DECLARATION)
    if change is not None:
        change(decl)
    pack = TemplatePack(T.make(tmp_path / "pack", declaration=decl))
    book = tmp_path / "book.xlsx"
    pack.build(doc or H.fixture_doc(), book, options={"exported_at": AT})
    return pack, book


def _row(ws, kind, ident, *, kind_col=T.KIND, id_col=T.ID):
    return next(r for r in range(1, ws.max_row + 1)
                if ws[f"{kind_col}{r}"].value == kind and ws[f"{id_col}{r}"].value == ident)


def _ops(pack, book):
    result = pack.read(book)
    assert result.problems == []
    return result.change_set.ops


# -- the loader ------------------------------------------------------------------

@pytest.mark.parametrize("kind, field", [("RESOURCE", "component_type"), ("STEP", "duration"),
                                         ("MEMBER", "classification"), ("MEMBER", "count")])
def test_a_growable_kind_binds_what_a_new_row_is_made_from(kind, field):
    doc = copy.deepcopy(T.DECLARATION)
    sheet = "crews" if kind == "MEMBER" else "estimate"
    del doc["sheets"][sheet]["fields"][kind][field]
    with pytest.raises(D.DeclarationError,
                       match=rf"sheets\.{sheet}\.fields\.{kind}: a growable kind needs its "
                             rf"{field} bound"):
        D.load(doc)


def test_a_fixed_block_may_leave_them_unbound():
    """No row of a fixed block's kind is ever created, so nothing needs them."""
    doc = copy.deepcopy(T.DECLARATION)
    est = doc["sheets"]["estimate"]
    est["blocks"]["resources"]["fixed"] = True
    del est["fields"]["RESOURCE"]["component_type"]
    D.load(doc)


# -- the reader ------------------------------------------------------------------

def test_a_copied_line_takes_what_the_sheet_does_not_bind_from_its_source(tmp_path):
    """Resource 3 (Foreman) is priced for 4 hours, which the mini-book shows
    nowhere: its copy is the same line, not one at BidSheet.ai's defaults."""
    pack, book = _book(tmp_path)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    row = _row(ws, "RESOURCE", 3)
    H.insert_copies(ws, row, row, row + 1)
    H.save_book(wb, book)
    (op,) = _ops(pack, book)
    assert op["op"] == "resource.create"
    assert op["fields"] == {"activity_id": 2, "name": "Foreman", "quantity": "1",
                            "unit_cost": "300", "component_type": "labor", "unit": "",
                            "time_value": "4", "time_unit": "HOURS",
                            "labor_cost_basis": "production", "burden_percentage": None,
                            "includes_burden": False, "sort_order": 0}


def test_a_copied_activity_takes_its_unbound_production_from_its_source(tmp_path):
    pack, book = _book(tmp_path)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    first = _row(ws, "ACTIVITY", 2)                       # Walls: 1.5/day, crew factor 1.1
    last = next(r for r in range(first, ws.max_row + 1) if ws[f"{T.KIND}{r}"].value == "END")
    H.insert_copies(ws, first, last, last + 1)
    H.save_book(wb, book)
    create = next(op for op in _ops(pack, book) if op["op"] == "activity.create")
    assert create["fields"] == {"estimate_item_id": 1, "name": "Walls",
                                "assembly_type": "GENERIC", "count": 2,
                                "production_rate": "1.5", "production_unit": "DAYS",
                                "hours_per_shift": "8", "crew_factor": "1.1",
                                "sort_order": 1}


def _hours_step_doc():
    doc = H.fixture_doc()
    step = next(a for a in doc["activities"] if a["id"] == 4)["steps"][0]
    step["duration_unit"] = "HOURS"
    return doc


def test_a_copied_step_keeps_its_sources_unit_and_a_typed_one_reads_a_blank_unit(tmp_path):
    pack, book = _book(tmp_path, doc=_hours_step_doc())
    wb = H.open_book(book)
    ws = wb[T.TAB]
    row = _row(ws, "STEP", 1)
    H.insert_copies(ws, row, row, row + 1)                # a copy of Set out (HOURS)
    H.type_row(ws, row + 2, {"B": "Strip", "C": 1})       # typed above START
    H.save_book(wb, book)
    adds = [op["fields"] for op in _ops(pack, book) if op["op"] == "step.add"]
    assert adds == [
        {"activity_id": 4, "name": "Set out", "duration": "2", "duration_unit": "HOURS"},
        {"activity_id": 4, "name": "Strip", "duration": "1", "duration_unit": "DAYS"}]


def test_a_roster_keeps_the_members_unbound_rate_overrides(tmp_path):
    """The roster op replaces every member: one the sheet shows no override
    for keeps BidSheet.ai's (Laborer, 50) rather than losing it."""
    def no_override(decl):
        del decl["sheets"]["crews"]["fields"]["MEMBER"]["hourly_rate_override"]
    pack, book = _book(tmp_path, no_override)
    wb = H.open_book(book)
    cw = wb[T.CREWS]
    cw[f"C{_row(cw, 'MEMBER', 2, kind_col='K', id_col='L')}"] = 2   # OPER: 1 -> 2
    H.save_book(wb, book)
    (op,) = _ops(pack, book)
    assert op["op"] == "crew.update_members"
    assert [(m["classification"], m["count"], m["hourly_rate_override"])
            for m in op["fields"]["members"]] == [("Laborer", "2", "50"), ("OPER", "2", None)]


def test_a_reclassified_member_keeps_its_unbound_override_and_says_so(tmp_path):
    """The book changes Laborer (override 50, not shown) to OPER: the
    override is kept -- dropping it would change BidSheet.ai unseen -- and a
    note says it now rides on another trade, to be checked."""
    def no_override(decl):
        del decl["sheets"]["crews"]["fields"]["MEMBER"]["hourly_rate_override"]
    pack, book = _book(tmp_path, no_override)
    wb = H.open_book(book)
    cw = wb[T.CREWS]
    row = _row(cw, 'MEMBER', 1, kind_col='K', id_col='L')
    cw[f"A{row}"] = "OPER"
    H.save_book(wb, book)
    result = pack.read(book)
    assert result.problems == []
    (op,) = result.change_set.ops
    assert [(m["classification"], m["labor_rate_id"], m["hourly_rate_override"])
            for m in op["fields"]["members"]] == [("OPER", 1, "50"), ("OPER", 1, None)]
    assert any(f"row {row}:" in note and "member 'Laborer' is now 'OPER'" in note
               and "its rate override (50/hr, not shown in this book) is kept" in note
               and "check it in BidSheet.ai" in note
               for note in result.change_set.notes)


def test_a_reclassified_member_with_its_override_shown_has_no_such_note(tmp_path):
    pack, book = _book(tmp_path)
    wb = H.open_book(book)
    cw = wb[T.CREWS]
    cw[f"A{_row(cw, 'MEMBER', 1, kind_col='K', id_col='L')}"] = "OPER"
    H.save_book(wb, book)
    result = pack.read(book)
    assert result.problems == []
    assert not any("not shown in this book) is kept" in n for n in result.change_set.notes)


def test_a_copied_line_carries_its_sources_blank_clearable_fields(tmp_path):
    """Resource 1 (CAT 336) has no unit, time or burden, none of which the
    mini-book binds: the create says so explicitly (the source's own blank
    values) rather than leaving them to BidSheet.ai's create defaults."""
    pack, book = _book(tmp_path)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    row = _row(ws, "RESOURCE", 1)
    H.insert_copies(ws, row, row, row + 1)
    H.save_book(wb, book)
    (op,) = _ops(pack, book)
    assert op["op"] == "resource.create"
    fields = op["fields"]
    assert {k: fields[k] for k in ("unit", "time_value", "time_unit", "burden_percentage")} == {
        "unit": "", "time_value": None, "time_unit": "", "burden_percentage": None}


def test_a_linked_copy_keeps_its_link_over_fields_the_sheet_does_not_bind(tmp_path):
    """Rule 11 (#459) compares the bound inputs bar the quantity: an unbound
    field (here CAT 336's 2 hours and 10% burden, which the mini-book shows
    nowhere) is carried from the source, so it cannot differ."""
    doc = H.linked_doc()
    for res in doc["resources"]:
        if res["id"] == 1:
            res.update(time_value="2", time_unit="HOURS", burden_percentage="10")
    pack, book = _book(tmp_path, doc=doc)
    wb = H.open_book(book)
    ws = wb[T.TAB]
    row = _row(ws, "RESOURCE", 1)
    H.insert_copies(ws, row, row, row + 1)
    ws[f"C{row + 1}"] = 40
    H.save_book(wb, book)
    (op,) = _ops(pack, book)
    assert op["op"] == "resource.create"
    assert op["fields"]["equipment_rate_id"] == 7
    assert {k: op["fields"][k] for k in ("quantity", "time_value", "burden_percentage")} == {
        "quantity": "40", "time_value": "2", "burden_percentage": "10"}


def test_an_unbound_field_is_kept_through_its_baseline_attribute():
    """``bound_or_kept`` reads a kept row's value through the contract's
    per-field ``attr``, as ``diff`` and ``carried`` do: ELEMENT_QTY's
    ``override_value`` lives on the baseline as ``override``."""
    from types import SimpleNamespace

    from estimating_tools.exchange.reader import fields as F
    kept = SimpleNamespace(override=12, classification="OPER")
    assert F.bound_or_kept({}, kept, "ELEMENT_QTY", "override_value") == 12
    assert F.bound_or_kept({"override_value": 3}, kept, "ELEMENT_QTY", "override_value") == 3
    assert F.bound_or_kept({}, kept, "MEMBER", "classification") == "OPER"
    assert F.bound_or_kept({}, None, "MEMBER", "classification") is None
