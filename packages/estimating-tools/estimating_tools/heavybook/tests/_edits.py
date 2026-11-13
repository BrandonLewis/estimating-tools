"""The nine Cost Report edits whose read-back the code build recorded
(``fixtures/golden/edits.json``) and the template build must reproduce."""
from __future__ import annotations

import json

from estimating_tools.heavybook.columns import CR
from estimating_tools.heavybook.tests import _readback as H


def _quantity(ws):
    ws[f"{CR.QTY}{H.cr_row(ws, 'RESOURCE', 1)}"] = 40


def _typed_resource(ws):
    H.type_row(ws, H.block_end(ws, 2), {CR.DESC: "Pump", CR.QTY: 1, CR.UCOST: 250,
                                        CR.TYPE: "equipment"})


def _stale_paste(ws):
    src = H.cr_row(ws, "RESOURCE", 3)
    H.insert_copies(ws, src, src, H.block_end(ws, 1))


def _cut(ws):
    src = H.cr_row(ws, "RESOURCE", 3)
    H.cut_rows(ws, src, src, H.block_end(ws, 1))


def _deleted_step(ws):
    ws.delete_rows(H.cr_row(ws, "STEP", 1))


def _inputs(ws):
    ws[f"{CR.PROD}{H.cr_row(ws, 'ACTIVITY', 2)}"] = 2
    ws[f"{CR.QTY}{H.cr_row(ws, 'ELEMENT_QTY', 1)}"] = 70
    ws[f"{CR.UCOST}{H.cr_row(ws, 'ITEM', 1)}"] = 150


def _typed_step(ws):
    H.type_row(ws, H.cr_row(ws, "START", parent=4), {CR.DESC: "Strip", CR.QTY: 1})


def _deleted_activity(ws):
    first = H.cr_row(ws, "ACTIVITY", 7)
    ws.delete_rows(first, H.block_end(ws, 7) - first + 1)


def _formula_overtyped(ws):
    ws[f"{CR.LAB}{H.cr_row(ws, 'ACTIVITY', 2)}"] = 1000


EDITS = {f.__name__.lstrip("_"): f for f in (
    _quantity, _typed_resource, _stale_paste, _cut, _deleted_step, _inputs, _typed_step,
    _deleted_activity, _formula_overtyped)}


def read_after(edit, path) -> dict:
    """``edit`` the book at ``path`` and read it back: ``{"problems",
    "ops", "rows"}``, as JSON holds them."""
    from estimating_tools.heavybook import pack as hb_pack

    wb = H.open_book(path)
    edit(wb[H.CR_TAB])
    H.save_book(wb, path)
    r = hb_pack.pack().read(path)
    out = {"problems": r.problems,
           "ops": r.change_set.ops if r.change_set else None,
           "rows": r.change_set.rows if r.change_set else None}
    return json.loads(json.dumps(out, default=str))
