"""The exchange contract's golden change sets (docs/estimate-exchange-contract.md,
part 7). Each scenario builds HeavyBook's book of the golden read model, edits
it the way an estimator would in Excel, and reads it back with HeavyBook's
reader; the change set (or the refusal) is checked in under
docs/estimate-exchange-contract/scenarios/. BidSheet.ai's contract test
dry-runs every change set and writes its plan beside it (<name>.plan.json);
the tests at the end hold each plan to its change set.

A change to the reader or the pack that changes a golden is a contract
change: regenerate with UPDATE_GOLDEN=1 on purpose, then regenerate the plans
(the document's part 7 says how). The edits are written here, not imported
from HeavyBook's own tests, so the public goldens do not move when a test
helper does."""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import BF, CR, CW
from estimating_tools.heavybook.tests import _readback as H

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "estimate-exchange-contract"
READ_MODEL = CONTRACT / "read-model.json"
SCENARIOS = CONTRACT / "scenarios"
HEAVYBOOK_GOLDEN = H.FIXTURE.parent / "golden" / "readback.ops.json"


def _bid_row(ws, item_id):
    return H.find_row(ws, "ITEM_BID", item_id, kind_col=BF.KIND, id_col=BF.ID)


def changed_inputs(wb):
    cr = wb[H.CR_TAB]
    cr[f"{CR.UCOST}{H.cr_row(cr, 'ITEM', 1)}"] = 150
    cr[f"{CR.QTY}{H.cr_row(cr, 'ELEMENT_QTY', 1)}"] = 70
    cr[f"{CR.PROD}{H.cr_row(cr, 'ACTIVITY', 2)}"] = 2
    cr[f"{CR.QTY}{H.cr_row(cr, 'RESOURCE', 1)}"] = 40


def bid_form(wb):
    bf = wb[H.BF_TAB]
    bf[f"{BF.VALUE}{BF.ROWS['markup_percentage']}"] = 12
    bf[f"{BF.SCOPE}{_bid_row(bf, 3)}"] = "excluded"
    bf[f"{BF.OVERRIDE}{_bid_row(bf, 4)}"] = 2500


def typed_resource(wb):
    cr = wb[H.CR_TAB]
    H.type_row(cr, H.block_end(cr, 2),
               {CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"})


def stale_paste(wb):
    cr = wb[H.CR_TAB]
    src = H.cr_row(cr, "RESOURCE", 3)
    H.insert_copies(cr, src, src, H.block_end(cr, 1))


def cut_resource(wb):
    cr = wb[H.CR_TAB]
    src = H.cr_row(cr, "RESOURCE", 3)
    H.cut_rows(cr, src, src, H.block_end(cr, 1))


def copied_linked_resource(wb):
    cr = wb[H.CR_TAB]
    src = H.cr_row(cr, "RESOURCE", 9)
    H.insert_copies(cr, src, src, H.block_end(cr, 8))


def edited_copy_of_linked_resource(wb):
    cr = wb[H.CR_TAB]
    src = H.cr_row(cr, "RESOURCE", 9)
    at = H.insert_copies(cr, src, src, H.block_end(cr, 8))
    cr[f"{CR.UCOST}{at}"] = 120


def reburdened_copy_of_linked_resource(wb):
    """A rate-linked line copied and its burden changed, its unit cost left
    as it was: an input other than the quantity differs from the source's,
    so the copy goes up unlinked (rule 11)."""
    cr = wb[H.CR_TAB]
    src = H.cr_row(cr, "RESOURCE", 9)
    at = H.insert_copies(cr, src, src, H.block_end(cr, 8))
    cr[f"{CR.BURD}{at}"] = 15


def renumbered_resource(wb):
    """A line typed between Walls' Carpenters and Foreman, which tie on
    sort order 0 (Foreman after it by id): no order fits between them, so
    Foreman is renumbered to 1."""
    cr = wb[H.CR_TAB]
    H.type_row(cr, H.cr_row(cr, "RESOURCE", 3),
               {CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250, CR.TYPE: "equipment"})


def reordered_activity(wb):
    """Pour (sort order 4) cut above Prep (3) among item 1's roots: no op
    reorders existing rows, so the read notes it and sends nothing."""
    cr = wb[H.CR_TAB]
    first = H.cr_row(cr, "ACTIVITY", 5)
    H.cut_rows(cr, first, H.block_end(cr, 5), H.cr_row(cr, "ACTIVITY", 4))


def typed_step(wb):
    cr = wb[H.CR_TAB]
    H.type_row(cr, H.cr_row(cr, "START", parent=4), {CR.DESC: "Strip", CR.QTY: 1})


def edited_step(wb):
    cr = wb[H.CR_TAB]
    cr[f"{CR.QTY}{H.cr_row(cr, 'STEP', 1)}"] = 3


def replaced_step(wb):
    cr = wb[H.CR_TAB]
    H.type_row(cr, H.cr_row(cr, "START", parent=4), {CR.DESC: "Strip", CR.QTY: 1})
    cr.delete_rows(H.cr_row(cr, "STEP", 1))


def deleted_activity(wb):
    cr = wb[H.CR_TAB]
    first = H.cr_row(cr, "ACTIVITY", 7)
    cr.delete_rows(first, H.block_end(cr, 7) - first + 1)


def deleted_member(wb):
    cw = wb[H.CW_TAB]
    cw.delete_rows(H.cw_row(cw, "MEMBER", 1))


def edited_library_crew(wb):
    cw = wb[H.CW_TAB]
    cw[f"{CW.COUNT}{H.cw_row(cw, 'MEMBER', 3)}"] = 4


def moved_and_copied_activities(wb):
    """HeavyBook's combined golden edit (heavybook/tests/test_readback_golden.py)."""
    bf, cr, cw = wb[H.BF_TAB], wb[H.CR_TAB], wb[H.CW_TAB]
    bf[f"{BF.VALUE}{BF.ROWS['markup_percentage']}"] = 12
    cr[f"{CR.QTY}{H.cr_row(cr, 'RESOURCE', 1)}"] = 32
    H.type_row(cr, H.cr_row(cr, "START", parent=4),
               {CR.DESC: "Strip", CR.QTY: 4, CR.UNIT: "HOURS"})
    src = H.cr_row(cr, "RESOURCE", 2)
    H.insert_copies(cr, src, src, H.block_end(cr, 2))
    cr.delete_rows(H.cr_row(cr, "RESOURCE", 4))
    first = H.cr_row(cr, "ACTIVITY", 6)
    H.cut_rows(cr, first, H.cr_row(cr, "END", parent=6), H.cr_row(cr, "ITEM", 5))
    first, last = H.cr_row(cr, "ACTIVITY", 1), H.cr_row(cr, "END", parent=1)
    H.insert_copies(cr, first, last, last + 1)
    cw[f"{CW.COUNT}{H.cw_row(cw, 'MEMBER', 1)}"] = 3


def formula_overwritten(wb):
    cr = wb[H.CR_TAB]
    cr[f"{CR.LAB}{H.cr_row(cr, 'ACTIVITY', 2)}"] = 1000


def all_steps_deleted(wb):
    cr = wb[H.CR_TAB]
    cr.delete_rows(H.cr_row(cr, "STEP", 1))


#: name -> (the edit, the ops its change set holds).
CHANGED = {
    "changed-inputs": (changed_inputs, {"item.update", "element.set_quantity",
                                        "activity.update", "resource.update"}),
    "bid-form": (bid_form, {"estimate.update", "item.update"}),
    "typed-resource": (typed_resource, {"resource.create"}),
    "stale-paste": (stale_paste, {"resource.create"}),
    "cut-resource": (cut_resource, {"resource.create", "resource.delete"}),
    "copied-linked-resource": (copied_linked_resource, {"resource.create"}),
    "edited-copy-of-linked-resource": (edited_copy_of_linked_resource, {"resource.create"}),
    "renumbered-resource": (renumbered_resource, {"resource.create", "resource.update"}),
    "reordered-activity": (reordered_activity, set()),
    "reburdened-copy-of-linked-resource": (reburdened_copy_of_linked_resource,
                                           {"resource.create"}),
    "typed-step": (typed_step, {"step.add"}),
    "edited-step": (edited_step, {"step.update"}),
    "replaced-step": (replaced_step, {"step.add", "step.delete"}),
    "deleted-activity": (deleted_activity, {"activity.delete"}),
    "deleted-member": (deleted_member, {"crew.update_members"}),
    "edited-library-crew": (edited_library_crew, {"crew.update_members"}),
    "moved-and-copied-activities": (moved_and_copied_activities, {
        "estimate.update", "activity.move", "activity.create", "activity.update", "step.add",
        "resource.create", "resource.update", "crew.update_members", "activity.set_crew",
        "resource.delete"}),
}
#: name -> (the edit, text one of its problems holds).
REFUSED = {
    "formula-overwritten": (formula_overwritten, "held a formula and now holds a value"),
    "all-steps-deleted": (all_steps_deleted, "all of its steps were deleted"),
}


def _read(edit, tmp_path, name):
    doc = json.loads(READ_MODEL.read_text(encoding="utf-8"))
    path = H.build_book(doc, tmp_path / f"{name}.xlsx")
    wb = H.open_book(path)
    edit(wb)
    H.save_book(wb, path)
    return hb_pack.pack().read(path)


def _golden(path, got):
    got = json.loads(json.dumps(got, sort_keys=True))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False)
                          + "\n").encode("utf-8"))
    assert path.is_file(), (f"{path.name} is missing: run "
                            "UPDATE_GOLDEN=1 pytest tests/test_exchange_contract_goldens.py")
    assert got == json.loads(path.read_text(encoding="utf-8"))


def _changes(name):
    return json.loads((SCENARIOS / f"{name}.changes.json").read_text(encoding="utf-8"))


def test_the_golden_read_model_is_heavybook_s_parity_fixture():
    assert (json.loads(READ_MODEL.read_text(encoding="utf-8"))
            == json.loads(H.FIXTURE.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", sorted(CHANGED))
def test_a_scenario_reads_back_as_its_golden_change_set(name, tmp_path):
    edit, ops = CHANGED[name]
    result = _read(edit, tmp_path, name)
    assert not result.problems, result.problems
    got = result.change_set.as_json()
    assert {op["op"] for op in got["ops"]} == ops
    _golden(SCENARIOS / f"{name}.changes.json", got)


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_a_refused_scenario_reads_back_as_its_golden_refusal(name, tmp_path):
    edit, why = REFUSED[name]
    result = _read(edit, tmp_path, name)
    assert any(why in p for p in result.problems), result.problems
    _golden(SCENARIOS / f"{name}.refused.json", {"problems": result.problems})


def test_the_combined_scenario_is_heavybook_s_own_golden():
    golden = json.loads(HEAVYBOOK_GOLDEN.read_text(encoding="utf-8"))
    assert _changes("moved-and-copied-activities")["ops"] == golden["ops"]


def test_a_copy_keeps_its_rate_link_only_while_unedited():
    (kept,) = _changes("copied-linked-resource")["ops"]
    (edited,) = _changes("edited-copy-of-linked-resource")["ops"]
    assert kept["fields"]["material_cost_id"] == 1
    assert "material_cost_id" not in edited["fields"]
    assert edited["fields"]["unit_cost"] == "120"
    # An input other than the unit cost and the quantity (its burden) edited:
    # unlinked too, at the unit cost the book shows -- the source's.
    (reburdened,) = _changes("reburdened-copy-of-linked-resource")["ops"]
    source = next(r for r in _read_model()["resources"] if r["id"] == 9)
    assert "material_cost_id" not in reburdened["fields"]
    assert reburdened["fields"]["burden_percentage"] == "15"
    assert source["burden_percentage"] is None
    assert Decimal(reburdened["fields"]["unit_cost"]) == Decimal(source["unit_cost"])


def _read_model() -> dict:
    return json.loads(READ_MODEL.read_text(encoding="utf-8"))


def test_a_line_typed_between_tied_lines_renumbers_the_one_below():
    res = {r["name"]: r for r in _read_model()["resources"] if r["activity_id"] == 2}
    above, below = res["Carpenters"], res["Foreman"]
    assert above["sort_order"] == below["sort_order"] and above["id"] < below["id"]
    create, update = _changes("renumbered-resource")["ops"]
    assert create["op"] == "resource.create"
    assert create["fields"]["sort_order"] == above["sort_order"]
    assert update == {"op": "resource.update", "ref": below["id"], "v": below["v"],
                      "fields": {"sort_order": above["sort_order"] + 1}}


def test_an_existing_row_moved_within_its_block_is_noted_and_not_sent():
    from estimating_tools.exchange.reader.ops import REORDERED

    changes = _changes("reordered-activity")
    assert changes["ops"] == [] and changes["rows"] == []
    (note,) = changes["notes"]
    assert note.endswith(": " + REORDERED.format(what="activity 'Pour'"))


def test_a_library_crew_is_edited_against_its_own_id():
    (op,) = _changes("edited-library-crew")["ops"]
    assert (op["op"], op["ref"]) == ("crew.update_members", 2)


def test_a_cut_line_is_a_delete_and_a_create():
    ops = _changes("cut-resource")["ops"]
    assert [(op["op"], op["ref"]) for op in ops] == [("resource.create", "new:r1"),
                                                     ("resource.delete", 3)]


def test_no_stray_golden_files():
    allowed = ({f"{n}.changes.json" for n in CHANGED} | {f"{n}.plan.json" for n in CHANGED}
               | {f"{n}.refused.json" for n in REFUSED})
    assert {p.name for p in SCENARIOS.iterdir()} <= allowed


CREATING = {"activity.create", "step.add", "resource.create", "element.create", "section.upsert"}


def _plan(name):
    return json.loads((SCENARIOS / f"{name}.plan.json").read_text(encoding="utf-8"))


def _kind(op: str) -> str:
    """The kind of row an op names: its prefix (``step.add`` -> ``step``)."""
    return op.split(".")[0]


@pytest.mark.parametrize("name", sorted(CHANGED))
def test_bidsheet_s_dry_run_of_a_scenario_is_checked_in_beside_it(name):
    changes, plan = _changes(name), _plan(name)
    ops = changes["ops"]
    assert plan["dry_run"] is True
    assert [r["op"] for r in plan["ops"]] == [op["op"] for op in ops]
    made = {op["ref"]: _kind(op["op"]) for op in ops
            if op["op"] in CREATING and str(op.get("ref", "")).startswith("new:")}
    tokens = {k: v for k, v in plan["created"].items() if not k.startswith("crew:")}
    assert tokens == made
    copies = {k for k in plan["created"] if k.startswith("crew:")}
    assert copies <= {f"crew:{op['ref']}" for op in ops if op["op"] == "crew.update_members"}
    assert all(plan["created"][k] == "crew" for k in copies)
    deletes = {(_kind(op["op"]), op["ref"]) for op in ops if op["op"].endswith(".delete")}
    assert {(d["kind"], d["id"]) for d in plan["deleted"]} == deletes
    assert set(plan["totals"]) == {"before", "after"}


def test_a_refused_scenario_has_no_plan():
    for name in REFUSED:
        assert not (SCENARIOS / f"{name}.plan.json").exists(), name


def test_the_library_crew_scenario_s_plan_names_the_copy():
    (op,) = [op for op in _changes("edited-library-crew")["ops"]
             if op["op"] == "crew.update_members"]
    crew = op["ref"]
    plan = _plan("edited-library-crew")
    assert plan["created"] == {f"crew:{crew}": "crew"}
    assert (f"library crew {crew} copied into this estimate as crew crew:{crew}"
            in plan["warnings"])
