"""layout_map: a format pack's map of where Estimate Navigator finds things."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.estimate_spec import layout_map as LM

GOOD = {
    "version": 1,
    "tables": {
        "index": {"sheet": "Cost Summary", "rows": {"each": "cs[*].bid"},
                  "columns": {"item_no": "A", "descr": "B", "cost": "H", "link": "C"}},
        "checks": {"sheet": "Checks", "rows": {"after": "checks_head.count", "skip": 1},
                   "columns": {"rule_no": "A", "rule": "B", "item": "C", "status": "F"}},
        "codes": {"sheet": "Codes", "rows": {"span": "code_rows.codes"},
                  "columns": {"code": "A", "descr": "B", "listed": "C"}},
    },
    "cells": {"direct_total": "Cost Summary!cost_summary_total.direct"},
    "tags": {"kind": "Q", "code_chain": "R"},
    "blocks": {"item": "ITEM", "head": "TASK", "body": ["NOTE", "CREW", "LINE"],
               "end": "END", "sub": "SUBTOTAL", "code_col": "A"},
    "templates": {"item": {"recipe": "lump_sum", "item_no": "TEMPLATE"},
                  "rows": {"crew": "CREW", "line": "LINE"},
                  "clear": {"TASK": ["A", "B"], "CREW": ["A", "D", "E"]}},
}

EXPORTS = {
    "Cost Summary": {"cs[1].bid": "$L$3", "cs[2].bid": "$L$4", "cs[3].bid": "$L$5",
                     "cost_summary_total.direct": "$H$7"},
    "Checks": {"checks_head.pass": "$B$2", "checks_head.count": "$D$2"},
    "Codes": {"code_rows.codes": "$A$1:$A$6", "code_rows.listed": "$C$1:$C$6"},
}
MAX_ROWS = {"Cost Summary": 10, "Checks": 30, "Codes": 6}


def test_a_valid_map_validates():
    assert LM.validate(copy.deepcopy(GOOD), "format.yaml")["version"] == 1


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m.update(extra=1), "unknown keys"),
    (lambda m: m.update(version=2), "version must be 1"),
    (lambda m: m.update(version=True), "version must be 1"),
    (lambda m: m.update(version=1.0), "version must be 1"),
    (lambda m: m["tables"].pop("index"), "must declare index"),
    (lambda m: m["tables"].update(other=m["tables"]["codes"]), "unknown table"),
    (lambda m: m["tables"]["index"]["columns"].pop("link"), "columns must be exactly"),
    (lambda m: m["tables"]["index"]["columns"].update(link="c"), "column letter"),
    (lambda m: m["tables"]["index"].update(rows={"each": "x", "span": "y"}), "exactly one of"),
    (lambda m: m["tables"]["index"].update(rows={"each": "x", "skip": 1}), "skip goes with after"),
    (lambda m: m["cells"].update(grand="Bid Form!x.y"), "may name only"),
    (lambda m: m["cells"].update(direct_total="no-sheet"), "SHEET!EXPORT"),
    (lambda m: m["tags"].pop("code_chain"), ".tags must map exactly"),
    (lambda m: m["blocks"].pop("end"), ".blocks must"),
    (lambda m: m["blocks"].update(body=[]), ".blocks must"),
    (lambda m: m["blocks"].update(body=["NOTE", ""]), ".blocks must"),
    (lambda m: m["templates"]["item"].update(sheet="X"), "must not name a sheet"),
    (lambda m: m["templates"]["item"].update(recipe=""), "must be an item with a recipe"),
    (lambda m: m["templates"]["rows"].pop("line"), ".templates.rows"),
    (lambda m: m["templates"]["rows"].update(crew=""), ".templates.rows must map exactly"),
    (lambda m: m["templates"]["clear"].update(CREW="A"), ".templates.clear"),
])
def test_invalid_maps_are_refused(mutate, message):
    m = copy.deepcopy(GOOD)
    mutate(m)
    with pytest.raises(LM.LayoutMapError, match=message):
        LM.validate(m, "format.yaml")


def test_each_rows_span_the_matched_exports():
    names, tables = LM.resolve(GOOD, EXPORTS, MAX_ROWS)
    assert names["est.index"] == ("Cost Summary", "$A$3:$H$5")
    assert names["est.index.item_no"] == ("Cost Summary", "$A$3:$A$5")
    assert names["est.index.link"] == ("Cost Summary", "$C$3:$C$5")
    assert names["est.direct_total"] == ("Cost Summary", "$H$7")
    assert tables == ["checks", "codes", "index"]


def test_brackets_in_a_glob_are_literal():
    exports = {"Cost Summary": {"cs1.bid": "$L$3", "cost_summary_total.direct": "$H$7"}}
    names, tables = LM.resolve(GOOD, exports, MAX_ROWS)
    assert "est.index" not in names and "index" not in tables


def test_a_gap_in_each_rows_is_refused():
    exports = copy.deepcopy(EXPORTS)
    exports["Cost Summary"]["cs[3].bid"] = "$L$9"
    with pytest.raises(LM.LayoutMapError, match="not contiguous"):
        LM.resolve(GOOD, exports, MAX_ROWS)


def test_after_rows_run_from_past_the_anchor_to_the_last_used_row():
    names, _ = LM.resolve(GOOD, EXPORTS, MAX_ROWS)
    assert names["est.checks"] == ("Checks", "$A$4:$F$30")
    assert names["est.checks.status"] == ("Checks", "$F$4:$F$30")


def test_span_rows_follow_the_export_range():
    names, _ = LM.resolve(GOOD, EXPORTS, MAX_ROWS)
    assert names["est.codes"] == ("Codes", "$A$1:$C$6")


def test_a_table_whose_export_is_missing_is_left_out():
    exports = copy.deepcopy(EXPORTS)
    del exports["Codes"]
    names, tables = LM.resolve(GOOD, exports, MAX_ROWS)
    assert "codes" not in tables and not any(n.startswith("est.codes") for n in names)


def test_a_missing_cell_export_is_an_error():
    exports = copy.deepcopy(EXPORTS)
    del exports["Cost Summary"]["cost_summary_total.direct"]
    with pytest.raises(LM.LayoutMapError, match="publishes no export"):
        LM.resolve(GOOD, exports, MAX_ROWS)


def test_row_parsing_only_looks_after_the_last_bang():
    # A sheet-qualified address ("AB1!$D$2") must read its row from the part
    # after the "!" (2), not from a column+row-shaped sheet name before it (1).
    exports = copy.deepcopy(EXPORTS)
    exports["Checks"]["checks_head.count"] = "AB1!$D$2"
    names, _ = LM.resolve(GOOD, exports, MAX_ROWS)
    assert names["est.checks"] == ("Checks", "$A$4:$F$30")


@pytest.mark.parametrize("addr", ["$P:$P", "$3:$5", "6"])
def test_an_each_export_naming_no_row_is_refused(addr):
    exports = copy.deepcopy(EXPORTS)
    exports["Cost Summary"]["cs[1].bid"] = addr
    with pytest.raises(LM.LayoutMapError, match="names no row"):
        LM.resolve(GOOD, exports, MAX_ROWS)


def test_an_after_anchor_naming_no_row_is_refused():
    exports = copy.deepcopy(EXPORTS)
    exports["Checks"]["checks_head.count"] = "$P:$P"
    with pytest.raises(LM.LayoutMapError, match="names no row"):
        LM.resolve(GOOD, exports, MAX_ROWS)


def test_a_span_anchor_naming_no_row_is_refused():
    exports = copy.deepcopy(EXPORTS)
    exports["Codes"]["code_rows.codes"] = "$1:$6"
    with pytest.raises(LM.LayoutMapError, match="names no row"):
        LM.resolve(GOOD, exports, MAX_ROWS)


def test_an_each_export_that_is_a_range_is_refused():
    exports = copy.deepcopy(EXPORTS)
    exports["Cost Summary"]["cs[1].bid"] = "$L$3:$L$4"
    with pytest.raises(LM.LayoutMapError, match="is a range; each needs one row per export"):
        LM.resolve(GOOD, exports, MAX_ROWS)


def test_each_rows_deduplicate_before_the_contiguity_check():
    # cs[2b] lands on the same row (4) as cs[2]; that must not read as a gap.
    exports = copy.deepcopy(EXPORTS)
    exports["Cost Summary"]["cs[2b].bid"] = "$M$4"
    names, tables = LM.resolve(GOOD, exports, MAX_ROWS)
    assert names["est.index"] == ("Cost Summary", "$A$3:$H$5")
    assert tables == ["checks", "codes", "index"]


def test_after_rows_start_past_the_anchors_last_row_when_the_anchor_is_a_range():
    exports = copy.deepcopy(EXPORTS)
    exports["Checks"]["checks_head.count"] = "$D$2:$D$3"
    names, _ = LM.resolve(GOOD, exports, MAX_ROWS)
    assert names["est.checks"] == ("Checks", "$A$5:$F$30")


def test_multi_letter_columns_sort_by_column_index_not_alphabetically():
    lm = copy.deepcopy(GOOD)
    lm["tables"]["index"]["columns"] = {"item_no": "B", "descr": "C", "cost": "AA", "link": "A"}
    names, _ = LM.resolve(lm, EXPORTS, MAX_ROWS)
    assert names["est.index"] == ("Cost Summary", "$A$3:$AA$5")
    assert names["est.index.cost"] == ("Cost Summary", "$AA$3:$AA$5")


def test_after_rows_resolve_to_nothing_when_max_row_is_before_first():
    max_rows = dict(MAX_ROWS, Checks=3)
    names, tables = LM.resolve(GOOD, EXPORTS, max_rows)
    assert "checks" not in tables and not any(n.startswith("est.checks") for n in names)


def test_after_rows_resolve_to_nothing_when_the_sheet_is_missing_from_max_rows():
    max_rows = {k: v for k, v in MAX_ROWS.items() if k != "Checks"}
    names, tables = LM.resolve(GOOD, EXPORTS, max_rows)
    assert "checks" not in tables and not any(n.startswith("est.checks") for n in names)
