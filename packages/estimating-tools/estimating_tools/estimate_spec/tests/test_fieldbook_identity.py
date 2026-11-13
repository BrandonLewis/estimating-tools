"""Identity on fieldbook's rows (fieldbook spec, "Identity is added,
structure is kept"): four hidden stored columns after Q to V -- W id, X v,
Y ref, Z time unit -- written from the config's ``exchange`` mappings. A
book built from a spec carries no id, ``v`` or link, and every crew row's
time unit is DAYS. A crew row's hours multiply by the shift only when its
time unit says DAYS."""
from __future__ import annotations

import dataclasses

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec.tests._fieldbook import (build, example_spec,
                                                             fieldbook_pack, rows_of_kind,
                                                             task_block)
from estimating_tools.estimate_spec.tests._formula_eval import evaluate

ITEM2 = "2 - 8IN MAIN"
SHIFT = "'Rates'!$B$2"


def _unchecked(spec):
    """Build ``spec`` without the spec schema, which has no ``exchange`` key
    (a build from the read model skips it; Task 10)."""
    return B.generate(spec, dataclasses.replace(fieldbook_pack(), strict=False))


def _with_identity():
    spec = example_spec()
    item = spec["items"][1]
    item["exchange"] = {"id": 12, "v": "a000000000000012"}
    task = item["labor"][0]
    task["exchange"] = {"id": 22, "v": "123e456789012345"}
    task["crew"][0]["exchange"] = {"id": 32, "v": "0000000000000032", "ref": "labor:1",
                                   "time_unit": "HOURS"}
    task["lines"][0]["exchange"] = {"id": 34, "v": "c000000000000034"}
    return spec


def test_the_ids_land_in_the_hidden_columns():
    ws = _unchecked(_with_identity())[ITEM2]
    (item,) = rows_of_kind(ws, "ITEM")
    assert (ws[f"W{item}"].value, ws[f"X{item}"].value) == (12, "a000000000000012")
    block = task_block(ws, "02-100")
    (head,) = block["TASK"]
    assert (ws[f"W{head}"].value, ws[f"X{head}"].value) == (22, "123e456789012345")
    assert ws[f"X{head}"].data_type == "s"
    crew = block["CREW"][0]
    assert [ws[f"{c}{crew}"].value for c in "WXYZ"] == [32, "0000000000000032", "labor:1",
                                                         "HOURS"]
    line = block["LINE"][0]
    assert [ws[f"{c}{line}"].value for c in "WXY"] == [34, "c000000000000034", None]
    assert all(ws.column_dimensions[c].hidden for c in "QRSTUVWXYZ")


def test_a_spec_book_carries_no_identity_and_days_everywhere():
    wb = build()
    for title in ("1 - MOBILIZATION", ITEM2, "3 - VALVES"):
        ws = wb[title]
        for r in range(1, ws.max_row + 1):
            assert [ws[f"{c}{r}"].value for c in "WXY"] == [None, None, None]
        assert {ws[f"Z{r}"].value for r in rows_of_kind(ws, "CREW")} == {"DAYS"}


def test_hours_multiply_by_the_shift_only_on_a_days_row(tmp_path):
    wb = _unchecked(_with_identity())
    ws = wb[ITEM2]
    hours, days = task_block(ws, "02-100")["CREW"][:2]
    assert ws[f"F{hours}"].value == f'=D{hours}*E{hours}*IF($Z{hours}="HOURS",1,{SHIFT})'
    ev = evaluate(wb, tmp_path)
    assert ev[f"{ITEM2}!F{hours}"] == ws[f"D{hours}"].value * ws[f"E{hours}"].value
    assert ev[f"{ITEM2}!F{days}"] == ws[f"D{days}"].value * ws[f"E{days}"].value * 8


def test_the_days_heading_says_hours_when_marked():
    ws = build()[ITEM2]
    head = next(r for r in rows_of_kind(ws, "HEAD")
                if ws[f"A{r}"].value == "Code / resource / item")
    assert ws[f"E{head}"].value == "Days (hrs if marked)"


def test_library_rates_carry_their_tag_and_link_and_local_rates_none():
    spec = example_spec()
    spec["rate_table"][0]["exchange"] = {"tag": "RATE", "ref": "labor:1"}
    ws = _unchecked(spec)["Rates"]
    named = {ws[f"A{r}"].value: r for r in range(1, ws.max_row + 1)}
    first = named[spec["rate_table"][0]["trade"]]
    other = named[spec["rate_table"][1]["trade"]]
    assert (ws[f"I{first}"].value, ws[f"J{first}"].value) == ("RATE", "labor:1")
    assert (ws[f"I{other}"].value, ws[f"J{other}"].value) == (None, None)
    assert ws.column_dimensions["I"].hidden and ws.column_dimensions["J"].hidden


def test_the_shift_length_has_a_defined_name():
    wb = build()
    assert wb.defined_names["est.shift_hours"].attr_text == SHIFT

