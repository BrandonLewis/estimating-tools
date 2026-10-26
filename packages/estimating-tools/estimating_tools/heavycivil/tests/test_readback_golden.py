"""One combined edit's change set, checked in (spec §5 Golden). BidSheet.ai's
contract test will apply this file's ``ops`` with dry_run to the fixture
estimate (a follow-up there). Regenerate with UPDATE_GOLDEN=1 after a reviewed change."""
from __future__ import annotations

import json
import os
from pathlib import Path

from estimating_tools.heavycivil.columns import BF, CR, CW
from estimating_tools.heavycivil.tests import _readback as H

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "readback.ops.json"


def combined_edit(path):
    wb = H.open_book(path)
    bf, cr, cw = wb[H.BF_TAB], wb[H.CR_TAB], wb[H.CW_TAB]
    bf[f"{BF.VALUE}4"] = 12                                        # markup %
    cr[f"{CR.QTY}{H.cr_row(cr, 'RESOURCE', 1)}"] = 32              # a resource edit
    H.type_row(cr, H.cr_row(cr, "START", parent=4),                # a typed step
               {CR.DESC: "Strip", CR.QTY: 4, CR.UNIT: "HOURS"})
    r = H.cr_row(cr, "RESOURCE", 2)                                # a copied resource
    H.insert_copies(cr, r, r, H.block_end(cr, 2))
    cr.delete_rows(H.cr_row(cr, "RESOURCE", 4))                    # a deleted resource
    first = H.cr_row(cr, "ACTIVITY", 6)                            # activity 6: item 2 -> 3
    H.cut_rows(cr, first, H.cr_row(cr, "END", parent=6), H.cr_row(cr, "ITEM", 5))
    first, last = H.cr_row(cr, "ACTIVITY", 1), H.cr_row(cr, "END", parent=1)
    H.insert_copies(cr, first, last, last + 1)                     # a crew-priced copy
    cw[f"{CW.COUNT}{H.cw_row(cw, 'MEMBER', 1)}"] = 3                # a member count
    H.save_book(wb, path)


def test_golden_change_set(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "book.xlsx")
    combined_edit(path)
    got = json.loads(json.dumps(H.read(path).as_json(), sort_keys=True))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes((json.dumps(got, indent=1, sort_keys=True, ensure_ascii=False)
                            + "\n").encode("utf-8"))
    assert got == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_golden_ops_cover_every_kind_of_change():
    ops = {op["op"] for op in json.loads(GOLDEN.read_text(encoding="utf-8"))["ops"]}
    assert ops == {"estimate.update", "activity.move", "activity.create", "activity.update",
                   "step.add", "resource.create", "resource.update", "crew.update_members",
                   "activity.set_crew", "resource.delete"}
