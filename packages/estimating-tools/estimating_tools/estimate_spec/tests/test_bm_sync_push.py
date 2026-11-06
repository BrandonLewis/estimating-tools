"""The push planner for packages and quotes (spec §1.2)."""
from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from estimating_tools.estimate_spec.bm_sync.export import BmExport
from estimating_tools.estimate_spec.bm_sync.plan_push import (
    DERIVED_AMOUNT_NOTE, line_payloads, plan_push, quote_amount)
from estimating_tools.estimate_spec.bm_sync.sidecar import QuoteSync, Sidecar
from estimating_tools.estimate_spec.package_frames import build_package_frames
from estimating_tools.estimate_spec.tests._bm_fixture import (
    _line, acme_rebar, bolt_rebar, export_builder, quote, spec_two_packages)
from estimating_tools.quotes.model import QuoteLine

NOW = "2026-10-29T15:10:00"
ACME_FILE = "acme-rebar--reinforcing-steel.json"


def one(items, **attrs):
    """The single item whose attributes equal `attrs`."""
    found = [i for i in items if all(getattr(i, k) == v for k, v in attrs.items())]
    assert len(found) == 1, f"{len(found)} matches for {attrs}: {items}"
    return found[0]


def q(vendor, package, lines, **header):
    """A quote whose lines are given as dicts (schedule 'Base')."""
    return quote(vendor, package, [QuoteLine(**{"schedule_name": "Base", **ln}) for ln in lines],
                 **header)


def basic_builder():
    return (export_builder().package("Reinforcing steel", 273, {"61": 7001})
            .package("Ready-mix concrete", 274, {"62": 7002}).organization(4722, "ACME REBAR"))


def basic_export(builder=None) -> BmExport:
    return BmExport.from_dict((builder or basic_builder()).build())


def push(quotes, ex=None, sc=None, **kw):
    files = [(name, quote_, f"sha-{name}") for name, quote_ in quotes]
    return plan_push(spec_two_packages(), files, ex or basic_export(), sc or Sidecar(),
                     spec_name="s", now=NOW, **kw)


def test_missing_package_is_created_and_items_assigned():
    ex = BmExport.from_dict(export_builder().package("Ready-mix concrete", 274, {"62": 7002}).build())
    plan = plan_push(spec_two_packages(), [], ex, Sidecar(), spec_name="s", now=NOW)
    kinds = [(o.kind, o.package) for o in plan.ops]
    assert ("ensure_package", "Reinforcing steel") in kinds and ("assign_items", "Reinforcing steel") in kinds
    assert plan.ops[0].tool == "create_work_package" and plan.ops[0].args["name"] == "Reinforcing steel"
    ensure = plan.ops[0]
    assert ensure.sidecar["packages.Reinforcing steel.work_package_id"] == "$.id"
    assign = one(plan.ops, kind="assign_items")
    assert assign.tool == "assign_items_to_package" and assign.after == ensure.id
    assert assign.args["work_package_id"] == {"$ref": ensure.id, "path": "$.id"}
    assert assign.args["item_numbers"] == ["61"]
    recalc = one(plan.ops, kind="recalc", package="Reinforcing steel")
    assert recalc.args == {"package_id": {"$ref": ensure.id, "path": "$.estimate_package_id"}}
    assert not [o for o in plan.ops if o.package == "Ready-mix concrete"]   # no writes, no recalc


def test_ids_start_at_p1_and_meta_is_filled():
    plan = push([(ACME_FILE, acme_rebar())])
    assert plan.ops[0].id == "p1" and plan.direction == "push" and plan.spec == "s"
    assert plan.meta == {"project_id": 1234, "estimate_id": 100,
                         "spec_choice": {"Reinforcing steel": {"selected": "ARR", "pinned": False, "picks": {}},
                                         "Ready-mix concrete": {"selected": "ARR", "pinned": False, "picks": {}}},
                         "file_sha": {ACME_FILE: f"sha-{ACME_FILE}"},
                         "package_ids": {"Reinforcing steel": {"work_package_id": 273, "estimate_package_id": 1273},
                                         "Ready-mix concrete": {"work_package_id": 274, "estimate_package_id": 1274}},
                         "bm_choice": {"Reinforcing steel": {"carry_mode": "automatic", "selected_quote_id": None,
                                                             "hand_items": []}}}
    assert push([(ACME_FILE, acme_rebar())]).ops[0].id == "p1"


def test_meta_carries_the_export_ids_of_existing_packages():
    """#421: a package that already exists in BidSheet.ai has no ensure op, so its ids
    travel in plan.meta for --apply to record."""
    plan = push([(ACME_FILE, acme_rebar())])
    assert plan.meta["package_ids"] == {
        "Reinforcing steel": {"work_package_id": 273, "estimate_package_id": 1273},
        "Ready-mix concrete": {"work_package_id": 274, "estimate_package_id": 1274}}


def test_meta_omits_ids_for_a_package_the_export_lacks():
    ex = BmExport.from_dict(export_builder().package("Ready-mix concrete", 274, {"62": 7002}).build())
    plan = plan_push(spec_two_packages(), [], ex, Sidecar(), spec_name="s", now=NOW)
    assert plan.meta["package_ids"] == {
        "Ready-mix concrete": {"work_package_id": 274, "estimate_package_id": 1274}}


def test_items_missing_from_an_existing_package_are_assigned():
    ex = basic_export(export_builder().package("Reinforcing steel", 273)
                      .package("Ready-mix concrete", 274, {"62": 7002}).organization(4722, "ACME REBAR"))
    plan = push([(ACME_FILE, acme_rebar())], ex)
    assign = one(plan.ops, kind="assign_items")
    assert assign.args == {"work_package_id": 273, "item_numbers": ["61"]}
    cl = one(plan.ops, kind="create_line")
    assert cl.args["work_package_item_id"] == {
        "$ref": assign.id, "path": "$.items[?item_number=='61'].work_package_item_id"}


def test_quote_for_unknown_package_is_refused():
    qt = q("Acme", "Striping", [{"item_number": "61", "unit_price": 1.0}])
    plan = plan_push(spec_two_packages(), [("acme--striping.json", qt, "x")], basic_export(), Sidecar(),
                     spec_name="s", now=NOW)
    assert [e for e in plan.entries if e.kind == "refused"][0].text == \
        "acme--striping.json: package 'Striping' is not in the spec's work_packages"
    assert not [o for o in plan.ops if o.kind.startswith("create_quote")]


def test_quote_on_an_item_outside_its_package_is_refused():
    qt = q("Acme Rebar", "Reinforcing steel", [{"item_number": "62", "unit_price": 1.0, "quantity": 1}])
    plan = push([(ACME_FILE, qt)])
    assert one(plan.entries, kind="refused").text == \
        f"{ACME_FILE}: item '62' is not in package 'Reinforcing steel'"
    assert not plan.ops


def test_new_quote_pushes_header_lines_and_notes():
    ex = BmExport.from_dict(export_builder().package("Reinforcing steel", 273, {"61": 7001})
                            .organization(4722, "ACME REBAR").build())
    plan = plan_push(spec_two_packages(), [(ACME_FILE, acme_rebar(), "sha")], ex, Sidecar(),
                     spec_name="s", now=NOW)
    cq = one(plan.ops, kind="create_quote")
    assert cq.tool == "create_work_package_quote" and cq.args["work_package_id"] == 273
    assert cq.args["vendor_id"] == 4722 and cq.args["vendor_name"] == "Acme Rebar"
    assert cq.args["amount"] == 1650.0 and cq.args["notes"].startswith(DERIVED_AMOUNT_NOTE)
    assert "Couplers included: yes" in cq.args["notes"] and "ref Q-100, dated 2026-10-27" in cq.args["notes"]
    assert cq.sidecar == {f"packages.Reinforcing steel.quotes.{ACME_FILE}.quote_id": "$.id",
                          f"packages.Reinforcing steel.quotes.{ACME_FILE}.revision": "$.revision"}
    cl = one(plan.ops, kind="create_line")
    assert cl.tool == "create_work_package_quote_line_item"
    assert cl.after == cq.id and cl.args["quote_id"] == {"$ref": cq.id, "path": "$.id"}
    assert cl.args["work_package_item_id"] == 7001 and cl.args["unit_price"] == 1.65 and cl.args["quantity"] == 1000
    assert cl.args["is_included"] is True and cl.args["is_alternate"] is False
    assert cl.sidecar == {f"packages.Reinforcing steel.quotes.{ACME_FILE}.lines.61": "$.id"}
    rebar = [o for o in plan.ops if o.package == "Reinforcing steel"]
    assert [o.kind for o in rebar] == ["create_quote", "create_line", "recalc"]
    assert rebar[-1].args == {"package_id": 1273}


def test_stated_amount_is_transcribed_not_derived():
    plan = push([("bolt-rebar--reinforcing-steel.json", bolt_rebar())])
    cq = one(plan.ops, kind="create_quote")
    assert cq.args["amount"] == 1720.0 and DERIVED_AMOUNT_NOTE not in cq.args.get("notes", "")
    cl = one(plan.ops, kind="create_line")
    assert cl.args["unit_price"] == 1.72 and cl.args["quantity"] == 1000 and "amount" not in cl.args


def test_header_amount_is_transcribed():
    qt = q("Acme Rebar", "Reinforcing steel", [], amount=5000.0)
    cq = one(push([(ACME_FILE, qt)]).ops, kind="create_quote")
    assert cq.args["amount"] == 5000.0 and "notes" not in cq.args


def test_quote_amount_helper():
    frames = build_package_frames(spec_two_packages(), [], spare_columns=0)
    assert quote_amount(acme_rebar(), frames) == (1650.0, True)
    assert quote_amount(bolt_rebar(), frames) == (1720.0, False)
    two = q("Acme Rebar", "Reinforcing steel", [
        {"item_number": "61", "line_name": "Rebar furnished and placed", "amount": 1000.0},
        {"item_number": "61", "line_name": "Couplers", "amount": 400.0, "is_alternate": True},
        {"item_number": "61", "line_name": "Couplers", "is_included": False}])
    assert quote_amount(two, frames) == (1000.0, True)   # no header amount: derived


def test_line_without_quantity_takes_the_spec_package_line_qty():
    qt = q("Acme", "Ready-mix concrete", [{"item_number": "62", "unit_price": 180.0}])   # line 146, item 139
    cl = one(push([("acme--ready-mix-concrete.json", qt)]).ops, kind="create_line")
    assert cl.args["quantity"] == 146 and cl.args["unit_price"] == 180.0


def test_two_priced_lines_on_one_item_push_one_line_with_amount():
    qt = q("Acme", "Reinforcing steel", [
        {"item_number": "61", "line_name": "Rebar furnished and placed", "unit_price": 1.65, "quantity": 1000},
        {"item_number": "61", "line_name": "Couplers", "unit_price": 12.0, "quantity": 40}])
    plan = push([("acme--reinforcing-steel.json", qt)])
    cl = one(plan.ops, kind="create_line")
    assert cl.args["amount"] == 2130.0 and "unit_price" not in cl.args and "quantity" not in cl.args
    cq = one(plan.ops, kind="create_quote")
    assert cq.args["amount"] == 2130.0 and cq.args["notes"].startswith(DERIVED_AMOUNT_NOTE)


def test_folded_lines_push_nothing_of_their_own():
    qt = q("Acme", "Reinforcing steel", [
        {"item_number": "61", "line_name": "Rebar furnished and placed", "unit_price": 1.65, "quantity": 1000},
        {"item_number": "61", "line_name": "Couplers", "folded_into": "Rebar furnished and placed"}])
    cl = one(push([("acme--reinforcing-steel.json", qt)]).ops, kind="create_line")
    assert cl.args["unit_price"] == 1.65 and cl.args["quantity"] == 1000


def test_unit_mismatch_pushes_amount_only():
    # QuoteLine has no unit field; the flag is the exclusion_notes prefix "unit <X> vs <Y>".
    qt = q("Acme", "Reinforcing steel", [{"item_number": "61", "unit_price": 3600.0, "quantity": 0.5,
                                          "exclusion_notes": "unit TON vs LB"}])
    cl = one(push([("acme--reinforcing-steel.json", qt)]).ops, kind="create_line")
    assert cl.args["amount"] == 1800.0 and "unit_price" not in cl.args and "quantity" not in cl.args
    assert cl.args["exclusion_notes"] == "unit TON vs LB"



@pytest.mark.parametrize("notes", ["unit 100 LB vs LB", "unit 100 LB vs LB; delivered only",
                                   "unit EA vs LIN FT"])
def test_a_unit_mismatch_with_a_multiword_unit_pushes_amount_only(notes):
    # The intake importer writes "unit <quote unit> vs <package unit>", and
    # either unit may contain spaces.
    qt = q("Acme", "Reinforcing steel", [{"item_number": "61", "unit_price": 165.0, "quantity": 10,
                                          "exclusion_notes": notes}])
    cl = one(push([("acme--reinforcing-steel.json", qt)]).ops, kind="create_line")
    assert cl.args["amount"] == 1650.0 and "unit_price" not in cl.args and "quantity" not in cl.args

def test_alternate_and_excluded_lines():
    alt_q = q("Acme", "Reinforcing steel", [{"item_number": "61", "unit_price": 1.65, "quantity": 1000,
                                             "is_alternate": True}])
    exc_q = q("Acme", "Ready-mix concrete", [{"item_number": "62", "is_included": False,
                                              "exclusion_notes": "no concrete"}])
    plan = push([("acme--reinforcing-steel.json", alt_q), ("acme--ready-mix-concrete.json", exc_q)])
    alt = one(plan.ops, kind="create_line", package="Reinforcing steel")
    exc = one(plan.ops, kind="create_line", package="Ready-mix concrete")
    assert alt.args["is_alternate"] is True and alt.args["is_included"] is False
    assert exc.args["is_included"] is False and exc.args["exclusion_notes"] == "no concrete"
    assert one(plan.ops, kind="create_quote", package="Reinforcing steel").args["amount"] == 0.0


def test_line_payloads_helper():
    frame = build_package_frames(spec_two_packages(), [], spare_columns=0)[0]
    ex = basic_export()
    assert line_payloads(acme_rebar(), frame, ex.package("Reinforcing steel")) == [
        {"item_number": "61", "work_package_item_id": 7001, "unit_price": 1.65, "quantity": 1000,
         "is_included": True, "is_alternate": False}]


def _synced(sha="sha-old", revision=1):
    sc = Sidecar()
    sc.package("Reinforcing steel").quotes[ACME_FILE] = QuoteSync(55, revision, 4722, sha, {"61": 901})
    return sc


def _export_with_quote(revision=1, quote_id=55):
    return basic_export(basic_builder().quote(
        "Reinforcing steel", quote_id, "Acme Rebar", 4722, revision=revision, amount=1650.0,
        lines=[{"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}]))


def test_unchanged_quote_plans_nothing_and_changed_one_revises():
    acme = acme_rebar()
    ex, sc = _export_with_quote(), _synced(sha="sha-acme")
    unchanged = plan_push(spec_two_packages(), [(ACME_FILE, acme, "sha-acme")], ex, sc,
                          spec_name="s", now=NOW)
    assert unchanged.is_empty and not unchanged.ops
    changed = replace(acme, lines=[replace(acme.lines[0], unit_price=1.60)])
    plan = plan_push(spec_two_packages(), [(ACME_FILE, changed, "sha-new")], ex, sc,
                     spec_name="s", now=NOW)
    rev = one(plan.ops, kind="create_revision")
    assert rev.tool == "create_quote_revision"
    assert rev.args == {"quote_id": 55, "copy_line_items": True, "amount": 1600.0,
                        "notes": one(push([(ACME_FILE, changed)]).ops, kind="create_quote").args["notes"]}
    assert rev.sidecar[f"packages.Reinforcing steel.quotes.{ACME_FILE}.quote_id"] == "$.id"
    assert rev.sidecar[f"packages.Reinforcing steel.quotes.{ACME_FILE}.revision"] == "$.revision"
    upd = one(plan.ops, kind="update_line")
    assert upd.tool == "update_work_package_quote_line_item"
    assert upd.after == rev.id and upd.args["unit_price"] == 1.60
    assert upd.args["line_item_id"] == {"$ref": rev.id, "path": "$.line_items[?item_number=='61'].id"}
    assert upd.sidecar == {f"packages.Reinforcing steel.quotes.{ACME_FILE}.lines.61": "$.id"}
    assert [o.kind for o in plan.ops] == ["create_revision", "update_line", "recalc"]


def test_changed_file_with_same_numbers_plans_nothing():
    ex = basic_export(basic_builder().quote(
        "Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0,
        lines=[{"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}]))
    notes = one(push([(ACME_FILE, acme_rebar())]).ops, kind="create_quote").args["notes"]
    ex.package("Reinforcing steel").quotes[0].notes = notes
    plan = plan_push(spec_two_packages(), [(ACME_FILE, acme_rebar(), "sha-new")], ex, _synced(),
                     spec_name="s", now=NOW)
    assert not plan.ops


def test_both_sides_moved_is_a_conflict_unless_forced():
    ex, sc = _export_with_quote(revision=2, quote_id=56), _synced()
    changed = replace(acme_rebar(), lines=[replace(acme_rebar().lines[0], unit_price=1.60)])
    files = [(ACME_FILE, changed, "sha-new")]
    plan = plan_push(spec_two_packages(), files, ex, sc, spec_name="s", now=NOW)
    assert one(plan.entries, kind="conflict").text == (
        f"{ACME_FILE}: the file changed since the last push and BidSheet.ai moved from "
        "revision 1 to revision 2; not pushed (force spec pushes it)")
    assert not plan.ops and not plan.is_empty
    forced = plan_push(spec_two_packages(), files, ex, sc, spec_name="s", now=NOW, force="spec")
    assert one(forced.ops, kind="create_revision").args["quote_id"] == 56


def test_only_bidsheet_moved_is_a_notice():
    plan = plan_push(spec_two_packages(), [(ACME_FILE, acme_rebar(), "sha-old")],
                     _export_with_quote(revision=2, quote_id=56), _synced(), spec_name="s", now=NOW)
    assert not plan.ops and plan.is_empty
    assert "revision 2" in one(plan.entries, kind="notice").text


def test_quote_without_a_sidecar_record_matches_by_vendor_not_duplicated():
    plan = push([(ACME_FILE, acme_rebar())], _export_with_quote())
    assert not [o for o in plan.ops if o.kind == "create_quote"]
    assert "quote 55" in one(plan.entries, kind="notice").text


def test_vendor_ambiguous_asks_and_absent_creates():
    ex = basic_export(basic_builder().organization(4723, "Acme Rebar "))
    plan = push([(ACME_FILE, acme_rebar())], ex)
    rv = one(plan.ops, kind="resolve_vendor")
    assert "4722" in rv.note and "4723" in rv.note
    cq = one(plan.ops, kind="create_quote")
    assert cq.args["vendor_id"] == {"$ref": rv.id, "path": "$.vendor_id"}

    plan = push([("bolt-rebar--reinforcing-steel.json", bolt_rebar())])
    cv = one(plan.ops, kind="create_vendor")
    assert cv.tool == "create_organization" and cv.args["name"] == "Bolt Rebar"
    cq = one(plan.ops, kind="create_quote")
    assert cq.args["vendor_id"] == {"$ref": cv.id, "path": "$.id"} and cq.after == cv.id


def test_reconcile_entry_prints_both_values():
    qt = q("Acme Rebar", "Reinforcing steel", [
        {"item_number": "61", "line_name": "Rebar furnished and placed", "unit_price": 1.65, "quantity": 1000}])
    entry = one(push([(ACME_FILE, qt)]).entries, kind="reconcile")
    assert entry.text == "Acme Rebar: BidSheet.ai value 1,650.00 = Sub Reinforcing steel carried subtotal 1,650.00"
    assert entry.package == "Reinforcing steel"


def test_reconcile_shows_a_difference_and_an_unbuildable_column():
    qt = q("Acme Rebar", "Reinforcing steel", [
        {"item_number": "61", "line_name": "Rebar furnished and placed", "unit_price": 1.65, "quantity": 900}])
    assert one(push([(ACME_FILE, qt)]).entries, kind="reconcile").text == \
        "Acme Rebar: BidSheet.ai value 1,485.00 ≠ Sub Reinforcing steel carried subtotal 1,650.00"
    text = one(push([(ACME_FILE, acme_rebar())]).entries, kind="reconcile").text
    assert text.startswith("Acme Rebar: BidSheet.ai value 1,650.00; Sub Reinforcing steel carried subtotal "
                           "not available (")


def _revised(file_quote, lines, notes=None):
    ex = basic_export(basic_builder().quote("Reinforcing steel", 55, "Acme Rebar", 4722,
                                            amount=1650.0, lines=lines))
    ex.package("Reinforcing steel").quotes[0].notes = notes
    return plan_push(spec_two_packages(), [(ACME_FILE, file_quote, "sha-new")], ex, _synced(),
                     spec_name="s", now=NOW)


def test_a_line_the_file_dropped_is_deleted_from_the_revision():
    lump = q("Acme Rebar", "Reinforcing steel", [], amount=1650.0)      # the only change: line 61 gone
    plan = _revised(lump, [{"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}])
    rev = one(plan.ops, kind="create_revision")
    dl = one(plan.ops, kind="delete_line")
    assert dl.tool == "delete_work_package_quote_line_item" and dl.after == rev.id
    assert dl.args == {"line_item_id": {"$ref": rev.id, "path": "$.line_items[?item_number=='61'].id"}}
    assert dl.note == "line 61 not in the quote file"
    assert f"packages.Reinforcing steel.quotes.{ACME_FILE}.lines.61" not in rev.sidecar
    assert [o.kind for o in plan.ops] == ["create_revision", "delete_line", "recalc"]


def test_a_line_the_file_added_is_created_on_the_revision():
    notes = one(push([(ACME_FILE, acme_rebar())]).ops, kind="create_quote").args["notes"]
    plan = _revised(acme_rebar(), [], notes=notes)
    rev = one(plan.ops, kind="create_revision")
    cl = one(plan.ops, kind="create_line")
    assert cl.after == rev.id and cl.args["quote_id"] == {"$ref": rev.id, "path": "$.id"}
    assert cl.args["work_package_item_id"] == 7001 and cl.args["unit_price"] == 1.65
    assert [o.kind for o in plan.ops] == ["create_revision", "create_line", "recalc"]


def test_an_amount_only_update_omits_the_unit_price_and_quantity():
    tons = q("Acme Rebar", "Reinforcing steel", [{"item_number": "61", "unit_price": 3600.0, "quantity": 0.5,
                                                 "exclusion_notes": "unit TON vs LB"}])
    plan = _revised(tons, [{"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}])
    upd = one(plan.ops, kind="update_line")
    assert set(upd.args) == {"line_item_id", "amount", "is_included", "is_alternate", "exclusion_notes"}
    assert upd.args["amount"] == 1800.0


# ---------- choice (spec §1.3) ----------

CHOICE_KINDS = {"carry", "allocate", "remove_allocation", "acknowledge"}
ACME_LINE = {"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}


def spec_with(**rebar):
    """The two-package spec with the Reinforcing steel package's keys overridden."""
    spec = copy.deepcopy(spec_two_packages())
    spec["work_packages"][0].update(rebar)
    return spec


def spec_rebar_61_62(**rebar):
    """Reinforcing steel lists items 61 and 62 (62 gains a line tagged with the package)."""
    spec = spec_with(items=["61", "62"], **rebar)
    item62 = next(i for i in spec["items"] if i["item_no"] == "62")
    item62["labor"][0]["lines"].append(
        _line("subcontract", "Dowels", 139, "CY", 4.0, "Reinforcing steel"))
    return spec


def rebar_builder(items=None, **pkg):
    return (export_builder().package("Reinforcing steel", 273, items or {"61": 7001}, **pkg)
            .package("Ready-mix concrete", 274, {"62": 7002}).organization(4722, "ACME REBAR"))


def push_spec(spec, quotes=(), ex=None, sc=None, **kw):
    files = [(name, quote_, f"sha-{name}") for name, quote_ in quotes]
    return plan_push(spec, files, ex or basic_export(), sc or Sidecar(), spec_name="s", now=NOW, **kw)


def choice_ops(plan):
    return [o for o in plan.ops if o.kind in CHOICE_KINDS]


def _pinned_on(quote_id, vendor, **pkg):
    return rebar_builder(carry_mode="pinned", selected_quote={"id": quote_id, "vendor_name": vendor}, **pkg)


def test_arr_unpinned_plans_nothing_when_bm_automatic():
    plan = push_spec(spec_two_packages(), ex=_export_with_quote())
    assert not [o for o in plan.ops if o.kind in {"carry", "allocate"}]
    assert "bm_choice" not in plan.meta or "Reinforcing steel" not in plan.meta["bm_choice"]


def test_arr_unpinned_returns_pinned_bm_to_automatic_only_when_spec_moved():
    ex = basic_export(_pinned_on(55, "Acme Rebar").quote(
        "Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE]))
    sc = Sidecar()
    sc.package("Reinforcing steel").spec_choice = {"selected": "Acme Rebar", "pinned": False, "picks": {}}
    plan = push_spec(spec_two_packages(), ex=ex, sc=sc)
    carry = one(plan.ops, kind="carry")
    assert carry.tool == "carry_work_package_quote"
    assert carry.args == {"work_package_id": 273, "quote_id": 0, "pin": False}

    sc.package("Reinforcing steel").spec_choice = {"selected": "ARR", "pinned": False, "picks": {}}
    assert not [o for o in push_spec(spec_two_packages(), ex=ex, sc=sc).ops if o.kind == "carry"]


def test_arr_pinned_is_self_perform():
    plan = push_spec(spec_with(pinned=True))
    carry = one(plan.ops, kind="carry")
    assert carry.args == {"work_package_id": 273, "quote_id": 0, "pin": True}
    assert carry.sidecar == {"packages.Reinforcing steel.bm_choice": "$"}
    assert plan.meta["bm_choice"]["Reinforcing steel"] == {
        "carry_mode": "pinned", "selected_quote_id": None, "hand_items": []}


def test_vendor_selected_carries_that_quote():
    plan = push_spec(spec_with(selected="Acme Rebar"), ex=_export_with_quote())
    carry = one(plan.ops, kind="carry")
    assert carry.args == {"work_package_id": 273, "quote_id": 55, "pin": True}
    assert "accept_alternate_line_ids" not in carry.args
    assert plan.meta["bm_choice"]["Reinforcing steel"] == {
        "carry_mode": "pinned", "selected_quote_id": 55, "hand_items": []}

    plan = push_spec(spec_with(selected="Acme Rebar"), [(ACME_FILE, acme_rebar())])
    cq = one(plan.ops, kind="create_quote")
    cl = one(plan.ops, kind="create_line")
    carry = one(plan.ops, kind="carry")
    assert carry.args["quote_id"] == {"$ref": cq.id, "path": "$.id"}
    assert carry.after == cl.id                  # the carry posts on the quote's lines
    assert [o.kind for o in plan.ops if o.package == "Reinforcing steel"] == \
        ["create_quote", "create_line", "carry", "recalc"]


def test_vendor_selected_on_a_revised_quote_carries_the_revision():
    changed = replace(acme_rebar(), lines=[replace(acme_rebar().lines[0], unit_price=1.60)])
    sc = _synced()
    plan = plan_push(spec_with(selected="Acme Rebar"), [(ACME_FILE, changed, "sha-new")],
                     _export_with_quote(), sc, spec_name="s", now=NOW)
    rev = one(plan.ops, kind="create_revision")
    carry = one(plan.ops, kind="carry")
    assert carry.args["quote_id"] == {"$ref": rev.id, "path": "$.id"}
    assert carry.after == one(plan.ops, kind="update_line").id   # after the revision's line ops


def test_vendor_selected_with_no_quote_is_refused():
    plan = push_spec(spec_with(selected="Nobody Rebar"))
    assert one(plan.entries, kind="refused").text == \
        "Reinforcing steel: selected 'Nobody Rebar' has no quote in BidSheet.ai or this push"
    assert not choice_ops(plan)


def _picks_export(**quote_kw):
    b = rebar_builder({"61": 7001, "62": 7003})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE], **quote_kw)
    b.quote("Reinforcing steel", 56, "Bolt Rebar", 4730, amount=556.0,
            lines=[{"item_number": "62", "line_id": 902, "unit_price": 4.0, "quantity": 139}],
            allocations=[{"allocation_id": 5001, "quote_line_item_id": 902, "allocation_type": "full"}])
    return b


def test_picks_go_by_hand():
    plan = push_spec(spec_rebar_61_62(picks={"61": "Acme Rebar"}), ex=basic_export(_picks_export()))
    alloc = one(plan.ops, kind="allocate")
    assert alloc.tool == "allocate_subcontractor"
    assert alloc.args == {"quote_line_item_id": 901, "allocation_type": "full"}
    rm = one(plan.ops, kind="remove_allocation")
    assert rm.tool == "remove_subcontractor_allocation" and rm.args == {"allocation_id": 5001}
    assert not [o for o in plan.ops if o.kind == "carry"]
    last = choice_ops(plan)[-1]
    assert last.sidecar == {"packages.Reinforcing steel.bm_choice": "$"}
    assert plan.meta["bm_choice"]["Reinforcing steel"] == {
        "carry_mode": "pinned", "selected_quote_id": None, "hand_items": ["61"]}


def test_picks_on_a_carried_package_clear_the_carry_then_allocate():
    b = _pinned_on(55, "Acme Rebar", items={"61": 7001, "62": 7003})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=2206.0,
            lines=[ACME_LINE, {"item_number": "62", "line_id": 902, "unit_price": 4.0, "quantity": 139}],
            allocations=[{"allocation_id": 5001, "quote_line_item_id": 901, "allocation_type": "full"},
                         {"allocation_id": 5002, "quote_line_item_id": 902, "allocation_type": "full"}])
    ex = basic_export(b)
    for picks, lines in (({"61": "Acme Rebar"}, [901]), ({"61": "Acme Rebar", "62": "Acme Rebar"}, [901, 902])):
        plan = push_spec(spec_rebar_61_62(picks=picks), ex=ex)
        ops = choice_ops(plan)
        assert ops[0].kind == "carry" and ops[0].args == {"work_package_id": 273, "quote_id": 0, "pin": True}
        assert [o.kind for o in ops[1:]] == ["allocate"] * len(lines)
        assert [o.args["quote_line_item_id"] for o in ops[1:]] == lines
        assert not [o for o in plan.ops if o.kind == "remove_allocation"]
        assert ops[-1].sidecar == {"packages.Reinforcing steel.bm_choice": "$"}


def test_picks_on_a_line_created_in_this_plan_reference_it():
    spec = spec_rebar_61_62(picks={"61": "Acme Rebar"})
    plan = push_spec(spec, [(ACME_FILE, acme_rebar())],
                     ex=basic_export(rebar_builder({"61": 7001, "62": 7003})))
    cl = one(plan.ops, kind="create_line")
    alloc = one(plan.ops, kind="allocate")
    assert alloc.args["quote_line_item_id"] == {"$ref": cl.id, "path": "$.id"} and alloc.after == cl.id


def test_forbidden_mix_refused():
    b = rebar_builder({"61": 7001, "62": 7003}).quote(
        "Reinforcing steel", 55, "Acme Rebar", 4722, amount=2206.0,
        lines=[ACME_LINE, {"item_number": "62", "line_id": 902, "unit_price": 4.0, "quantity": 139}],
        separate_acceptance_permitted=False, acceptance_notes="Lump sum only")
    plan = push_spec(spec_rebar_61_62(picks={"61": "Acme Rebar"}),
                     [("bolt-rebar--reinforcing-steel.json", bolt_rebar())], ex=basic_export(b))
    assert one(plan.entries, kind="refused").text == \
        "Reinforcing steel: Acme Rebar does not permit separate acceptance: Lump sum only"
    assert not [o for o in plan.ops if o.kind == "allocate"]
    assert one(plan.ops, kind="create_quote").args["vendor_name"] == "Bolt Rebar"


def test_carry_pick_and_carry_selected_are_notices():
    plan = push_spec(spec_with(selected="CARRY", carry={"61": 1.9}))
    assert "CARRY has no BidSheet.ai form" in one(plan.entries, kind="notice").text
    assert not choice_ops(plan)
    plan = push_spec(spec_rebar_61_62(picks={"61": "CARRY", "62": "Bolt Rebar"}, carry={"61": 1.9}),
                     ex=basic_export(_picks_export()))
    assert "CARRY has no BidSheet.ai form" in one(plan.entries, kind="notice").text
    assert not [o for o in plan.ops if o.kind in {"allocate", "remove_allocation"}]   # Bolt on 62 stands


def _conflict_case():
    b = _pinned_on(57, "Zed Rebar")
    for qid, vendor in ((55, "Acme Rebar"), (56, "Bolt Rebar"), (57, "Zed Rebar")):
        b.quote("Reinforcing steel", qid, vendor, None, amount=1650.0,
                lines=[{**ACME_LINE, "line_id": 900 + qid}])
    sc = Sidecar()
    sc.package("Reinforcing steel").spec_choice = {"selected": "Acme Rebar", "pinned": False, "picks": {}}
    sc.package("Reinforcing steel").bm_choice = {"carry_mode": "pinned", "selected_quote_id": 55,
                                                 "hand_items": []}
    return basic_export(b), sc


def test_conflict_both_sides_moved():
    ex, sc = _conflict_case()
    plan = push_spec(spec_with(selected="Bolt Rebar"), ex=ex, sc=sc)
    text = one(plan.entries, kind="conflict").text
    assert "spec: Bolt Rebar" in text and "BidSheet.ai: Zed Rebar (pinned)" in text
    assert text.startswith("Reinforcing steel: ")
    assert not [o for o in plan.ops if o.kind == "carry"] and not plan.is_empty
    forced = push_spec(spec_with(selected="Bolt Rebar"), ex=ex, sc=sc, force="spec")
    assert one(forced.ops, kind="carry").args["quote_id"] == 56


def test_only_one_side_moved_is_no_conflict():
    ex, sc = _conflict_case()
    plan = push_spec(spec_with(selected="Acme Rebar"), ex=ex, sc=sc)   # spec unchanged
    assert not [e for e in plan.entries if e.kind == "conflict"]
    assert one(plan.ops, kind="carry").args["quote_id"] == 55


def test_re_affirmed_pin_with_a_revised_quote_is_not_an_override():
    """#427: the spec keeps Acme pinned, Acme's file changed (a revision) and new quotes
    arrived: the plan revises and acknowledges, and says nothing about overriding a pin."""
    b = _pinned_on(55, "Acme Rebar", new_quotes_since_carry=True)
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    acme = acme_rebar()
    changed = replace(acme, lines=[replace(acme.lines[0], unit_price=1.60)])
    plan = push_spec(spec_with(selected="Acme Rebar", pinned=True), [(ACME_FILE, changed)],
                     ex=basic_export(b), sc=_synced(sha="sha-old"))
    assert [o.kind for o in plan.ops if o.package == "Reinforcing steel"] == \
        ["create_revision", "update_line", "acknowledge", "recalc"]
    assert [e.text for e in plan.entries if "overrides" in e.text] == []


def test_acknowledge_only_when_spec_pins_the_same_choice():
    b = _pinned_on(55, "Acme Rebar", new_quotes_since_carry=True)
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    b.quote("Reinforcing steel", 56, "Bolt Rebar", 4730, amount=1720.0, lines=[{**ACME_LINE, "line_id": 956}])
    ex = basic_export(b)
    plan = push_spec(spec_with(selected="Acme Rebar", pinned=True), ex=ex)
    rebar = [o for o in plan.ops if o.package == "Reinforcing steel"]
    assert [o.kind for o in rebar] == ["acknowledge", "recalc"]
    ack = rebar[0]
    assert ack.tool == "acknowledge_work_package_quotes" and ack.args == {"work_package_id": 273}
    assert ack.sidecar == {"packages.Reinforcing steel.bm_choice": "$"}

    plan = push_spec(spec_with(selected="Bolt Rebar", pinned=True), ex=ex)
    assert not [o for o in plan.ops if o.kind == "acknowledge"]
    assert one(plan.ops, kind="carry").args["quote_id"] == 56


# ---------- plug removal (spec §1.4) ----------

PLUGS = [{"component_id": 9001, "name": "01 Rebar furnished and placed", "component_type": "subcontractor"},
         {"component_id": 9002, "name": "02 Couplers", "component_type": "material"},
         {"component_id": 9003, "name": "03 Small tools", "component_type": "other"}]


def _plug_export(comps=PLUGS):
    b = rebar_builder({"61": 7001, "62": 7011}).components("61", 3617, comps).components("62", 3618, comps[:1])
    return basic_export(b)


def test_remove_plug_offered_for_carried_items_only():
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), [(ACME_FILE, acme_rebar())], ex=_plug_export())
    ops = [o for o in plan.ops if o.kind == "remove_plug"]
    assert {o.args["component_id"] for o in ops} == {9001, 9002}
    assert ops[0].tool == "delete_component"
    assert ops[0].note == "item 61 · 01 Rebar furnished and placed · 1000 × 1.80 = 1,800.00 · package Reinforcing steel"
    assert ops[0].sidecar == {"packages.Reinforcing steel.plugs_removed.61": {
        "assembly_id": 3617, "component_id": 9001, "name": "01 Rebar furnished and placed"}}
    assert ops[1].note.startswith("item 61 · 02 Couplers · 40 × 12.50 = 500.00")
    assert plan.ops[-1].kind == "recalc"


def test_remove_plug_follows_picks():
    qt = q("Acme Rebar", "Reinforcing steel", [{"item_number": "61", "unit_price": 1.65, "quantity": 1000}])
    plan = push_spec(spec_rebar_61_62(picks={"61": "Acme Rebar"}), [(ACME_FILE, qt)], ex=_plug_export())
    assert {o.args["component_id"] for o in plan.ops if o.kind == "remove_plug"} == {9001, 9002}


def test_no_remove_plug_when_arr_or_automatic():
    plan = push_spec(spec_rebar_61_62(), [(ACME_FILE, acme_rebar())], ex=_plug_export())
    assert not [o for o in plan.ops if o.kind == "remove_plug"]


def _removed(assembly_id, component_id, name=None):
    return {"assembly_id": assembly_id, "component_id": component_id, "name": name}


def test_already_removed_plugs_are_not_offered_again():
    sc = Sidecar()
    sc.package("Reinforcing steel").plugs_removed = {"61": [_removed(3617, 9001)]}
    ex = _plug_export(PLUGS[1:])          # 9001 is gone from BidSheet.ai
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), [(ACME_FILE, acme_rebar())], ex=ex, sc=sc)
    assert [o.args["component_id"] for o in plan.ops if o.kind == "remove_plug"] == [9002]
    sc.package("Reinforcing steel").plugs_removed = {"61": [_removed(3617, 9002, "02 Couplers")]}
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), [(ACME_FILE, acme_rebar())],
                     ex=_plug_export(), sc=sc)
    assert [o.args["component_id"] for o in plan.ops if o.kind == "remove_plug"] == [9001]


def test_stale_plug_records_are_flagged_and_not_counted():
    """#428: after a push-assemblies re-push the recorded assembly ids are gone. When the
    export says which assemblies an item has now, a record naming another assembly is
    stale: it is left out of the removed count, reported, and handed to --apply to prune."""
    stale, live = _removed(3000, 8001, "02 Couplers"), _removed(3617, 9001, "01 Rebar furnished and placed")
    sc = Sidecar()
    ps = sc.package("Reinforcing steel")
    ps.plugs_removed = {"61": [stale, live]}
    ps.spec_choice = {"selected": "Acme Rebar", "pinned": False, "picks": {}}
    plan = push_spec(spec_rebar_61_62(), ex=_plug_export(), sc=sc)     # export: item 61 has assembly 3617
    texts = [e.text for e in plan.entries if e.kind == "notice"]
    assert texts == [
        "Reinforcing steel: 1 plug component(s) were removed on item 61 when Acme Rebar was carried; "
        "push-assemblies restores them",
        "Reinforcing steel: 1 stale plug record(s) on item 61 (3000:8001 02 Couplers): the assembly was "
        "replaced by a re-push; --apply prunes them"]
    assert plan.meta["stale_plugs"] == {"Reinforcing steel": {"61": [stale]}}


def test_no_stale_detection_when_the_export_lacks_assembly_ids():
    sc = Sidecar()
    ps = sc.package("Reinforcing steel")
    ps.plugs_removed = {"61": [_removed(3000, 8001, "02 Couplers")]}
    ps.spec_choice = {"selected": "Acme Rebar", "pinned": False, "picks": {}}
    ex = _plug_export()
    ex.package("Reinforcing steel").assemblies.clear()
    plan = push_spec(spec_rebar_61_62(), ex=ex, sc=sc)
    assert "stale_plugs" not in plan.meta
    assert one(plan.entries, kind="notice").text.startswith("Reinforcing steel: 1 plug component(s) were removed")


def test_return_to_arr_prints_removed_plugs():
    sc = Sidecar()
    ps = sc.package("Reinforcing steel")
    ps.plugs_removed = {"61": [_removed(3617, 9001)]}
    ps.spec_choice = {"selected": "Acme Rebar", "pinned": False, "picks": {}}
    plan = push_spec(spec_rebar_61_62(), ex=_plug_export(), sc=sc)
    assert not [o for o in plan.ops if o.kind == "remove_plug"]
    assert one(plan.entries, kind="notice").text == (
        "Reinforcing steel: 1 plug component(s) were removed on item 61 when Acme Rebar was carried; "
        "push-assemblies restores them")
    ps.spec_choice = None
    plan = push_spec(spec_rebar_61_62(), ex=_plug_export(), sc=sc)
    assert "when a vendor was carried" in one(plan.entries, kind="notice").text


def test_notes_already_carrying_the_pieces_do_not_get_them_twice():
    """A file pull wrote copies BidSheet.ai's notes, which already carry the derived-amount
    note, the condition lines and the ref line the push adds (ruling 22)."""
    pulled = replace(acme_rebar(), notes="\n".join(
        [DERIVED_AMOUNT_NOTE, "Couplers included: yes", "ref Q-100, dated 2026-10-27"]))
    notes = one(push([(ACME_FILE, pulled)]).ops, kind="create_quote").args["notes"]
    assert notes == pulled.notes
    for piece in (DERIVED_AMOUNT_NOTE, "Couplers included: yes", "ref Q-100, dated 2026-10-27"):
        assert notes.count(piece) == 1


# ---------- final review fixes ----------

def _plugs_on(b):
    return basic_export(b.components("61", 3617, PLUGS))


def _plug_ids(plan):
    return {o.args["component_id"] for o in plan.ops if o.kind == "remove_plug"}


def test_no_plug_offer_when_the_choice_is_a_conflict():
    """Probe A: spec Acme, BidSheet.ai pinned on Zed, both moved since the sidecar."""
    b = _pinned_on(57, "Zed Rebar", items={"61": 7001, "62": 7011})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    b.quote("Reinforcing steel", 57, "Zed Rebar", None, amount=1700.0, lines=[{**ACME_LINE, "line_id": 957}])
    sc = Sidecar()
    sc.package("Reinforcing steel").spec_choice = {"selected": "ARR", "pinned": False, "picks": {}}
    sc.package("Reinforcing steel").bm_choice = {"carry_mode": "automatic", "selected_quote_id": None,
                                                 "hand_items": []}
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), [(ACME_FILE, acme_rebar())],
                     ex=_plugs_on(b), sc=sc)
    assert one(plan.entries, kind="conflict")
    assert not [o for o in plan.ops if o.kind == "carry"]
    assert _plug_ids(plan) == set()
    # the conflict stands: apply records neither side's baseline for the package
    assert "Reinforcing steel" not in plan.meta["spec_choice"]
    assert "Reinforcing steel" not in plan.meta.get("bm_choice", {})


def test_no_plug_offer_when_the_carried_quote_is_refused():
    """Probe B: Acme's file prices an item outside the package; the choice is refused."""
    bad = q("Acme Rebar", "Reinforcing steel", [{"item_number": "61", "unit_price": 1.65, "quantity": 1000},
                                                {"item_number": "39", "unit_price": 1.0, "quantity": 837}])
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), [(ACME_FILE, bad)],
                     ex=_plugs_on(rebar_builder({"61": 7001, "62": 7011})))
    assert {e.kind for e in plan.entries} >= {"refused"}
    assert not [o for o in plan.ops if o.kind == "carry"]
    assert _plug_ids(plan) == set()


def test_plug_offer_when_the_carry_is_already_in_effect():
    b = _pinned_on(55, "Acme Rebar", items={"61": 7001, "62": 7011})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), ex=_plugs_on(b))
    assert not [o for o in plan.ops if o.kind == "carry"]
    assert _plug_ids(plan) == {9001, 9002}


def test_plug_offer_for_a_vendor_quoted_only_in_bidsheet():
    """Probe C: spec selected Acme, Acme's quote only in the export."""
    b = rebar_builder({"61": 7001, "62": 7011})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), ex=_plugs_on(b))
    assert one(plan.ops, kind="carry").args["quote_id"] == 55
    assert _plug_ids(plan) == {9001, 9002}


def test_no_plug_offer_for_an_item_the_bidsheet_quote_excludes():
    b = rebar_builder({"61": 7001, "62": 7011})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0,
            lines=[{**ACME_LINE, "is_included": False}])
    plan = push_spec(spec_rebar_61_62(selected="Acme Rebar"), ex=_plugs_on(b))
    assert _plug_ids(plan) == set()


def test_plug_name_cut_by_the_old_push_still_matches():
    long_name = "Rebar furnished and placed, epoxy coated, including chairs, tie wire, " \
                "laps and mechanical splices per plan sheets S-12"
    assert len(long_name) == 118
    spec = spec_rebar_61_62(selected="Acme Rebar")
    item61 = next(i for i in spec["items"] if i["item_no"] == "61")
    item61["labor"][0]["lines"][0]["name"] = long_name
    cut = ("01 " + long_name)[:113]
    comps = [{"component_id": 9001, "name": cut, "component_type": "subcontractor"}]
    b = rebar_builder({"61": 7001, "62": 7011}).components("61", 3617, comps)
    plan = push_spec(spec, [(ACME_FILE, acme_rebar())], ex=basic_export(b))
    assert _plug_ids(plan) == {9001}


def test_plug_note_prints_a_formula_qty_raw():
    spec = spec_rebar_61_62(selected="Acme Rebar")
    item61 = next(i for i in spec["items"] if i["item_no"] == "61")
    item61["labor"][0]["lines"][1]["qty"] = "=20*2"
    plan = push_spec(spec, [(ACME_FILE, acme_rebar())], ex=_plug_export())
    note = next(o.note for o in plan.ops if o.kind == "remove_plug" and o.args["component_id"] == 9002)
    assert note == "item 61 · 02 Couplers · =20*2 × 12.50 · package Reinforcing steel"


def test_a_formula_qty_is_not_pushed_as_a_quantity():
    spec = spec_with()
    item61 = next(i for i in spec["items"] if i["item_no"] == "61")
    item61["labor"][0]["lines"][0]["qty"] = "=500*2"
    qt = q("Acme Rebar", "Reinforcing steel", [{"item_number": "61", "line_name": "Rebar furnished and placed",
                                                "unit_price": 1.65}])
    plan = push_spec(spec, [(ACME_FILE, qt)])
    assert "formula" in one(plan.entries, kind="refused").text
    assert not [o for o in plan.ops if o.kind in ("create_quote", "create_line")]


def test_no_baseline_push_that_overrides_a_bidsheet_pin_says_so():
    """Probe D: sidecar has spec_choice but no bm_choice; the estimator pinned Zed in BidSheet.ai."""
    b = _pinned_on(57, "Zed Rebar")
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    b.quote("Reinforcing steel", 57, "Zed Rebar", None, amount=1700.0, lines=[{**ACME_LINE, "line_id": 957}])
    sc = Sidecar()
    sc.package("Reinforcing steel").spec_choice = {"selected": "ARR", "pinned": False, "picks": {}}
    plan = push_spec(spec_with(selected="Acme Rebar"), ex=basic_export(b), sc=sc)
    assert one(plan.ops, kind="carry").args["quote_id"] == 55
    assert one(plan.entries, kind="notice").text == \
        "Reinforcing steel: overrides BidSheet.ai's pin on Zed Rebar (pinned)"
    assert plan.meta["bm_choice"]["Reinforcing steel"] == {
        "carry_mode": "pinned", "selected_quote_id": 55, "hand_items": []}


def test_an_automatic_package_with_quote_ops_records_its_baseline():
    plan = push([(ACME_FILE, acme_rebar())])
    assert plan.meta["bm_choice"] == {"Reinforcing steel": {
        "carry_mode": "automatic", "selected_quote_id": None, "hand_items": []}}
    assert not [o for o in plan.ops if o.sidecar.get("packages.Reinforcing steel.bm_choice")]


def test_a_revised_carried_quote_baseline_references_the_revision():
    b = _pinned_on(55, "Acme Rebar")
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    changed = replace(acme_rebar(), lines=[replace(acme_rebar().lines[0], unit_price=1.60)])
    plan = plan_push(spec_two_packages(), [(ACME_FILE, changed, "sha-new")], basic_export(b), _synced(),
                     spec_name="s", now=NOW)
    rev = one(plan.ops, kind="create_revision")
    assert plan.meta["bm_choice"]["Reinforcing steel"]["selected_quote_id"] == {"$ref": rev.id, "path": "$.id"}


def test_an_automatic_carry_moving_is_not_a_bidsheet_choice_move():
    """The bid-day chain: push (automatic), BidSheet.ai re-evaluates its carry, the
    estimator then picks a vendor in Excel: no conflict."""
    b = rebar_builder(selected_quote={"id": 56, "vendor_name": "Bolt Rebar"})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    b.quote("Reinforcing steel", 56, "Bolt Rebar", 4730, amount=1600.0, lines=[{**ACME_LINE, "line_id": 956}])
    sc = Sidecar()
    sc.package("Reinforcing steel").spec_choice = {"selected": "ARR", "pinned": False, "picks": {}}
    sc.package("Reinforcing steel").bm_choice = {"carry_mode": "automatic", "selected_quote_id": 55,
                                                 "hand_items": []}
    plan = push_spec(spec_with(selected="Acme Rebar"), ex=basic_export(b), sc=sc)
    assert not [e for e in plan.entries if e.kind == "conflict"]
    assert one(plan.ops, kind="carry").args["quote_id"] == 55


def test_an_unchanged_unsynced_file_is_adopted():
    ex = _export_with_quote()
    notes = one(push([(ACME_FILE, acme_rebar())]).ops, kind="create_quote").args["notes"]
    ex.package("Reinforcing steel").quotes[0].notes = notes
    plan = push([(ACME_FILE, acme_rebar())], ex)
    assert not plan.ops
    assert one(plan.entries, kind="notice").text == f"{ACME_FILE}: adopted BidSheet.ai quote 55 rev 1"
    assert plan.meta["adopt"] == {"Reinforcing steel": {ACME_FILE: {
        "quote_id": 55, "revision": 1, "vendor_id": 4722, "lines": {"61": 901}}}}


def test_a_cleared_exclusion_note_is_sent_empty():
    plan = _revised(acme_rebar(), [{**ACME_LINE, "exclusion_notes": "no chairs"}])
    upd = one(plan.ops, kind="update_line")
    assert upd.args["exclusion_notes"] == ""


def test_no_recalc_without_an_estimate_package_id():
    ex = basic_export()
    ex.package("Reinforcing steel").estimate_package_id = None
    plan = push([(ACME_FILE, acme_rebar())], ex)
    assert not [o for o in plan.ops if o.kind == "recalc"]
    assert any("no estimate package id" in e.text for e in plan.entries if e.kind == "notice")


def test_quote_ops_carry_a_one_line_note():
    plan = push([(ACME_FILE, acme_rebar())])
    assert one(plan.ops, kind="create_quote").note == "Acme Rebar, amount 1,650.00, derived, 1 line(s)"
    changed = replace(acme_rebar(), lines=[replace(acme_rebar().lines[0], unit_price=1.60)], amount=1600.0)
    plan = plan_push(spec_two_packages(), [(ACME_FILE, changed, "sha-new")], _export_with_quote(), _synced(),
                     spec_name="s", now=NOW)
    assert one(plan.ops, kind="create_revision").note == "Acme Rebar, amount 1,600.00, 1 line(s)"


def test_all_arr_picks_on_an_automatic_package_push_nothing():
    b = rebar_builder(selected_quote={"id": 55, "vendor_name": "Acme Rebar"})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, amount=1650.0, lines=[ACME_LINE])
    plan = push_spec(spec_with(picks={"61": "ARR"}), ex=basic_export(b))
    assert not plan.ops
