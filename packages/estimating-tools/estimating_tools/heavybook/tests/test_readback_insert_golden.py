"""Estimate Navigator's inserts read back, checked in (spec "Testing"):
the second golden change set, ``readback.insert.ops.json``. BidSheet.ai's
contract test dry-runs its ``ops`` against the fixture estimate, as it does
``readback.ops.json``. Regenerate with UPDATE_GOLDEN=1 after a reviewed
change."""
from __future__ import annotations

import json
import os
from pathlib import Path

from estimating_tools.heavybook.columns import CR, CW
from estimating_tools.heavybook.tests import _readback as H

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "readback.insert.ops.json"


def navigator_inserts(path):
    """Each insert as the add-in places it, then the cells its note names
    filled in. Each row is looked up after the inserts before it."""
    wb = H.open_book(path)
    cr, cw = wb[H.CR_TAB], wb[H.CW_TAB]
    # An untouched resource line in Pour (activity 5): skipped with a note.
    H.insert_template(wb, "hc.tpl.resource", H.CR_TAB, H.block_end(cr, 5))
    # New stepped activity on item B3 (cursor on its ITEM row): after its
    # last ELEMENT_QTY row, so it is the item's first activity.
    at = H.cr_row(cr, "ACTIVITY", 6)
    H.insert_template(wb, "hc.tpl.stepped", H.CR_TAB, at)
    cr[f"{CR.DESC}{at}"] = "Cure"
    step = H.cr_row(cr, "STEP", start=at)
    cr[f"{CR.DESC}{step}"], cr[f"{CR.QTY}{step}"], cr[f"{CR.UNIT}{step}"] = "Wet cure", 3, "DAYS"
    res = H.cr_row(cr, "RESOURCE", start=at)
    for letter, value in {CR.DESC: "Curing compound", CR.QTY: 40, CR.UNIT: "GAL",
                          CR.UCOST: 12.5, CR.TYPE: "material"}.items():
        cr[f"{letter}{res}"] = value
    # ... and a second line, inserted with the cursor on the new block's END.
    second = H.insert_template(wb, "hc.tpl.resource", H.CR_TAB,
                               H.cr_row(cr, "END", start=at))
    for letter, value in {CR.DESC: "Curing labor", CR.QTY: 16, CR.UCOST: 52,
                          CR.TYPE: "labor"}.items():
        cr[f"{letter}{second}"] = value
    # A new step in Prep (activity 4), cursor between STEPS and START.
    step = H.insert_template(wb, "hc.tpl.step", H.CR_TAB, H.cr_row(cr, "START", parent=4))
    cr[f"{CR.DESC}{step}"], cr[f"{CR.QTY}{step}"], cr[f"{CR.UNIT}{step}"] = "Strip", 4, "HOURS"
    # A new resource line in Walls (activity 2), cursor on its END.
    res = H.insert_template(wb, "hc.tpl.resource", H.CR_TAB, H.block_end(cr, 2))
    for letter, value in {CR.DESC: "Pump", CR.QTY: 2, CR.UCOST: 80,
                          CR.TYPE: "equipment"}.items():
        cr[f"{letter}{res}"] = value
    # A new member in the Pour crew (crew 2, a library crew), cursor on its
    # end row: BidSheet.ai copies the crew into the estimate.
    member = H.insert_template(wb, "hc.tpl.member", H.CW_TAB,
                               H.cw_row(cw, "CREW_END", parent=2))
    cw[f"{CW.CODE}{member}"], cw[f"{CW.COUNT}{member}"] = "OPER", 1
    H.save_book(wb, path)


def test_insert_golden_change_set(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")
    navigator_inserts(path)
    got = json.loads(json.dumps(H.read(path).as_json(), sort_keys=True))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes((json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False)
                            + "\n").encode("utf-8"))
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_insert_golden_covers_each_new_row_kind():
    cs = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert [(op["op"], op["ref"]) for op in cs["ops"]] == [
        ("activity.create", "new:a1"),
        ("step.add", "new:s1"), ("step.add", "new:s2"),
        ("resource.create", "new:r1"), ("resource.create", "new:r2"),
        ("resource.create", "new:r3"),
        ("crew.update_members", 2)]
    by_ref = {op["ref"]: op for op in cs["ops"]}
    assert by_ref["new:a1"]["fields"]["estimate_item_id"] == 2
    assert by_ref["new:s1"]["fields"]["activity_id"] == 4
    assert by_ref["new:s2"]["fields"]["activity_id"] == "new:a1"
    assert [by_ref[r]["fields"]["activity_id"] for r in ("new:r1", "new:r2", "new:r3")] == [
        2, "new:a1", "new:a1"]
    assert any(n.endswith("an empty inserted resource line was skipped") for n in cs["notes"])
