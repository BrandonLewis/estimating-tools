"""Package frames from the spec and the quote files, and the driven-cell transform."""
from __future__ import annotations

import copy
import dataclasses

import pytest

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec.package_frames import (
    PackageError,
    apply_packages,
    build_package_frames,
)
from estimating_tools.estimate_spec.tests._fieldbook import (
    QUOTES,
    _line,
    example_spec,
    fieldbook_pack,
    packaged_spec,
)
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine

HAUL_KEY = "2/02/0"
BOX_KEY = "3/01/0"


def frames(spec=None, quotes=None, spares=4):
    return build_package_frames(spec or packaged_spec(), QUOTES if quotes is None else quotes,
                                spare_columns=spares, taken=set())


def frame(name, **kw):
    (f,) = [f for f in frames(**kw) if f.name == name]
    return f


def column(f, vendor):
    (v,) = [v for v in f.vendors if v.name == vendor]
    return v


def test_frames_carry_lines_titles_and_spares():
    hauling = frame("Hauling")
    assert hauling.title == "Sub Hauling"
    assert [ln.key for ln in hauling.lines] == [HAUL_KEY]
    (line,) = hauling.lines
    assert (line.item_sheet, line.slot, line.line_index, line.qty, line.plug_price,
            line.task_key, line.uom) == ("2 - 8IN MAIN", "02", 0, 460, 18, "task[02-200]", "CY")
    assert [v.name for v in hauling.vendors] == ["Dirt Movers", "Bulk Haul Co", "", "", "", ""]
    assert [v.is_spare for v in hauling.vendors][-4:] == [True] * 4
    dm = column(hauling, "Dirt Movers")
    assert dm.cells == {HAUL_KEY: 16.5} and dm.surcharge == pytest.approx(0.04)
    assert hauling.conditions == ["Fuel surcharge", "Dump fees"]


def test_selector_matches_vendor_case_insensitively():
    spec = packaged_spec()
    spec["work_packages"][0]["selected"] = "  dirt MOVERS "
    spec["work_packages"][0]["picks"] = {"2": "bulk haul co"}
    hauling = frame("Hauling", spec=spec)
    assert hauling.selected == "Dirt Movers"
    assert hauling.effective_source("2") == "Bulk Haul Co"
    valves = frame("Valves", spec=spec)
    assert valves.effective_source("3") == "ARR"


def test_two_files_for_one_vendor_keep_the_latest():
    old = CanonicalQuote(
        vendor_name="dirt movers", work_package_name="Hauling", quote_date="2026-10-12",
        lines=[QuoteLine(schedule_name="Base", item_number="2", unit_price=17.25,
                         line_name="Haul, import + export")])
    hauling = frame("Hauling", quotes=[QUOTES[0], old, *QUOTES[1:]])
    assert [v.name for v in hauling.vendors if not v.is_spare] == ["Dirt Movers", "Bulk Haul Co"]
    assert column(hauling, "Dirt Movers").cells == {HAUL_KEY: 16.5}
    assert len(hauling.frames_notes) == 1 and "2026-10-12" in hauling.frames_notes[0]


def test_same_date_conflict_is_refused():
    clash = dataclasses.replace(QUOTES[0], lines=[QuoteLine(
        schedule_name="Base", item_number="2", unit_price=15.0, line_name="Haul, import + export")])
    with pytest.raises(PackageError,
                       match="Hauling: two quote files for Dirt Movers with the same date"):
        frames(quotes=[QUOTES[0], clash])


def test_lump_sum_is_prorated_by_plug_extension():
    hauling = frame("Hauling")
    bulk = column(hauling, "Bulk Haul Co")
    assert bulk.lump_sum is True
    assert bulk.cells[HAUL_KEY] == pytest.approx(19.0)
    (scope_line,) = hauling.as_scope()["lines"]
    assert scope_line["prorated"] == {"Bulk Haul Co": pytest.approx(8740.0)}


def test_excluded_and_folded_lines():
    spec = packaged_spec()
    # A second Hauling line on item 2 task 02, so a vendor can fold one into the other.
    spec["work_packages"][0]["selected"] = "ARR"
    block = spec["items"][1]["labor"][1]
    block["lines"].append({"cost_type": "subcontract", "name": "Dump fees", "qty": 460,
                           "uom": "CY", "unit_price": 4, "package": "Hauling"})
    q = CanonicalQuote(vendor_name="Folders Inc", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  is_included=False, exclusion_notes="by others"),
        QuoteLine(schedule_name="Base", item_number="2", line_name="Dump fees",
                  folded_into="Haul, import + export"),
    ])
    hauling = frame("Hauling", spec=spec, quotes=[q])
    assert column(hauling, "Folders Inc").cells == {"2/02/0": "excl", "2/02/1": "incl"}
    # A line with no line_name on an item with two package lines is ambiguous.
    vague = CanonicalQuote(vendor_name="Vague", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="2", unit_price=10)])
    with pytest.raises(PackageError, match="Hauling: Vague"):
        frames(spec=spec, quotes=[vague])


def test_amount_only_line_is_divided_by_qty():
    q = CanonicalQuote(vendor_name="Per Line", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="2", amount=9200)])
    assert column(frame("Hauling", quotes=[*QUOTES, q]), "Per Line").cells == {HAUL_KEY: pytest.approx(20.0)}


def test_unknown_selected_is_refused():
    spec = packaged_spec()
    spec["work_packages"][0]["selected"] = "Dirt Mover"
    with pytest.raises(PackageError) as exc:
        frames(spec=spec)
    assert str(exc.value) == ("Hauling: selected 'Dirt Mover' is not ARR, CARRY or a quoted "
                              "vendor (vendors: Dirt Movers, Bulk Haul Co)")


def test_quote_line_outside_the_package_is_refused():
    q = CanonicalQuote(vendor_name="Wanderer", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="3", unit_price=5)])
    with pytest.raises(PackageError, match="Hauling: Wanderer .*item '3'.* not in the package"):
        frames(quotes=[q])


def test_item_without_a_package_line_is_refused():
    spec = packaged_spec()
    del _line(spec, "3", "01", "Valve boxes (subcontract)")["package"]
    with pytest.raises(PackageError, match=r"Valves: item '3' has no line tagged package: "
                                           r"Valves \(run est-estimate packages sync\)"):
        frames(spec=spec)


def test_vendor_name_with_braces_is_refused():
    q = CanonicalQuote(vendor_name="Bad {name}", work_package_name="Hauling", amount=1)
    with pytest.raises(PackageError, match="Bad {name}"):
        frames(quotes=[q])


def test_detail_rows_list_the_takeoff():
    spec = packaged_spec()
    spec["work_packages"][1]["detail"] = "precast"
    assert frame("Valves", spec=spec).detail_rows == [("Gate valve", 4, "EA", "takeoff")]
    assert frame("Hauling", spec=spec).detail_rows == []


def test_as_scope_shape():
    scope = frame("Hauling").as_scope()
    assert scope["name"] == "Hauling" and scope["title"] == "Sub Hauling"
    assert scope["selected"] == "Dirt Movers" and scope["kind"] == "subcontract"
    assert scope["vendor_names"] == ["Dirt Movers", "Bulk Haul Co", "", "", "", ""]
    assert scope["items"] == [{"item_no": "2", "item_sheet": "2 - 8IN MAIN", "source": "Dirt Movers",
                               "arr_sp": "0"}]                 # item 2 has no self-perform task
    assert scope["strategy"] == "sub_out" and scope["lump_flag"] == "LUMP SUM"
    assert [(v["idx"], v["name"], v["role"], v["lump"]) for v in scope["vendors"][:3]] == [
        (0, "Dirt Movers", "quoted", ""), (1, "Bulk Haul Co", "lump", "LUMP SUM"), (2, "", "spare", "")]
    assert scope["surcharges"] == [{"vendor": "Dirt Movers", "pct": 0.04},
                                   {"vendor": "Bulk Haul Co", "pct": 0.0}]
    assert [{k: c[k] for k in ("text", "cells")} for c in scope["conditions"]] == [
        {"text": "Fuel surcharge", "cells": {"Dirt Movers": "4% of invoice"}},
        {"text": "Dump fees", "cells": {"Dirt Movers": "included"}}]
    (line,) = scope["lines"]
    assert line["cells"] == {"Dirt Movers": 16.5, "Bulk Haul Co": pytest.approx(19.0)}
    assert line["pick"] == "Dirt Movers" and line["carry"] is None
    # the flat per-vendor-column fields a band reads as {it.c{v.idx}} / {it.n{v.idx}}
    assert (line["c0"], line["c1"], line["c2"]) == (16.5, pytest.approx(19.0), "")
    assert (line["n0"], line["n1"]) == ("", "prorated from $8,740.00 lump sum")
    assert (line["code"], line["item_pick"], line["carry_price"]) == ("02-200", "", "")
    assert [(c["t0"], c["t1"]) for c in scope["conditions"]] == [("4% of invoice", ""), ("included", "")]
    assert scope["detail_rows"] == []


def test_as_scope_names_the_self_perform_tasks_the_package_switches():
    assert frame("Valves").as_scope()["items"] == [{"item_no": "3", "item_sheet": "3 - VALVES", "source": "ARR",
                      "arr_sp": "{ref:3 - VALVES!task[02-510].arr_cost}"}]


def test_carry_is_a_package_lines_dollars_per_unit():
    spec = packaged_spec()
    spec["work_packages"][0]["carry"] = {"2": 17.5}               # item 2 has one package line
    (line,) = frame("Hauling", spec=spec).as_scope()["lines"]
    assert (line["carry"], line["carry_price"]) == (17.5, 17.5)


def test_carry_keyed_by_line_on_a_multi_line_item():
    spec = packaged_spec()
    (item2,) = [i for i in spec["items"] if i["item_no"] == "2"]
    item2["labor"][1]["lines"].append({"cost_type": "subcontract", "name": "Dump fees", "qty": 1,
                                       "uom": "LS", "unit_price": 500, "package": "Hauling"})
    spec["work_packages"][0]["carry"] = {"2/Dump fees": 400}
    haul, dump = frame("Hauling", spec=spec).as_scope()["lines"]
    assert (haul["carry"], haul["carry_price"]) == (None, "")
    assert (dump["carry"], dump["carry_price"]) == (400, 400)
    # a lump sum's note names the quote's total; `prorated` keeps each line's share
    assert dump["prorated_from"] == {"Bulk Haul Co": 8740.0}
    assert dump["prorated"]["Bulk Haul Co"] == pytest.approx(8740 * 500 / 8780)
    assert dump["n1"] == "prorated from $8,740.00 lump sum"


def test_titles_avoid_taken_sheet_names():
    fs = build_package_frames(packaged_spec(), QUOTES, spare_columns=0, taken={"sub hauling"})
    assert [f.title for f in fs] == ["Sub Hauling (2)", "Sub Valves"]


def test_apply_packages_rewrites_only_driven_cells():
    spec = packaged_spec()
    before = copy.deepcopy(spec)
    fs = frames(spec=spec)
    out = apply_packages(spec, fs, shift_hours=8)
    assert spec == before                                      # the original is untouched

    haul = _line(out, "2", "02", "Haul, import + export")
    assert haul["unit_price"] == "={ref:Sub Hauling!lines.line[2/02/0].rate}"
    assert (haul["source"], haul["pkg_ref"]) == ("pkg", "Sub Hauling!lines.line[2/02/0]")
    assert haul["vendor"] == "={ref:Sub Hauling!lines.line[2/02/0].src}"
    assert (haul["u_tag"], haul["arr_qty"], haul["arr_price"]) == ("PKG", "(460)", "(18)")
    assert (haul["plug"], haul["qty_full"], haul["index"], haul["qty"]) == (18, 460, 0, 460)

    box = _line(out, "3", "01", "Valve boxes (subcontract)")
    assert box["unit_price"] == "={ref:Sub Valves!lines.line[3/01/0].rate}"
    assert (box["plug"], box["qty_full"], box["qty"]) == (650, 4, 4)   # a package line's qty stays

    # Item 2 task 02 is a support task (the default): its crew is untouched.
    assert out["items"][1]["labor"][1]["crew"] == before["items"][1]["labor"][1]["crew"]
    # Item 3 task 01 is self-perform: every crew member's days scale by the factor.
    task = out["items"][2]["labor"][0]
    assert task["carry"] == "self_perform"
    sp = "{ref:Sub Valves!items.item[3].sp_factor}"
    assert [m["days"] for m in task["crew"]] == [f"=2*{sp}", f"=2*{sp}"]
    assert [m["days_full"] for m in task["crew"]] == [2, 2]
    assert [(m["u_tag"], m["arr_days"]) for m in task["crew"]] == [("SP", "(2)"), ("SP", "(2)")]
    assert task["sp_note"] == "(self-perform: off when a vendor is carried)"

    # Every other line keeps its values; it gains only its index.
    trench = out["items"][1]["labor"][0]
    assert [ln["index"] for ln in trench["lines"]] == [0, 1, 2]
    for got, want in zip(trench["lines"], before["items"][1]["labor"][0]["lines"]):
        assert {k: v for k, v in got.items() if k != "index"} == want

    assert [p["name"] for p in out["_packages"]] == ["Hauling", "Valves"]
    assert out["_packages"] == [f.as_scope() for f in fs]


def test_self_perform_formula_days_and_lines_are_wrapped():
    spec = packaged_spec()
    task = spec["items"][2]["labor"][0]
    task["crew"][0]["days"] = "=1+1"
    task["lines"].append({"cost_type": "material", "name": "Grout", "qty": "=2*3",
                          "uom": "BAG", "unit_price": 12})
    task["lines"].append({"cost_type": "material", "name": "Bolts", "qty": 8,
                          "uom": "EA", "unit_price": 3})
    out = apply_packages(spec, frames(spec=spec), shift_hours=8)
    sp = "{ref:Sub Valves!items.item[3].sp_factor}"
    t = out["items"][2]["labor"][0]
    assert t["crew"][0]["days"] == f"=(1+1)*{sp}"
    grout, bolts = t["lines"][1], t["lines"][2]
    assert (grout["qty"], grout["qty_full"]) == (f"=(2*3)*{sp}", "=2*3")
    assert (grout["u_tag"], grout["arr_qty"]) == ("SP", "(2*3)")
    assert t["crew"][0]["arr_days"] == "(1+1)"
    assert (bolts["qty"], bolts["qty_full"], bolts["index"]) == (f"=8*{sp}", 8, 2)


def test_an_item_in_two_packages_is_switched_off_by_the_first():
    spec = packaged_spec()
    spec["work_packages"].append({"name": "Valves Too", "kind": "supply", "items": ["3"]})
    spec["items"][2]["labor"][0]["lines"].append(
        {"cost_type": "material", "name": "Valve nuts", "qty": 4, "uom": "EA",
         "unit_price": 2, "package": "Valves Too"})
    out = apply_packages(spec, frames(spec=spec), shift_hours=8)
    days = out["items"][2]["labor"][0]["crew"][0]["days"]
    assert days == "=2*{ref:Sub Valves!items.item[3].sp_factor}"


def test_an_unpackaged_spec_builds_unchanged():
    wb = B.generate(example_spec(), fieldbook_pack())
    assert not any(n.startswith("Sub ") for n in wb.sheetnames)


def test_generate_levels_the_quotes_it_is_given():
    spec = packaged_spec()
    spec["work_packages"][0]["selected"] = "Bulk Haul Co"
    with pytest.raises(PackageError, match=r"vendors: none"):
        B.generate(spec, fieldbook_pack())             # no quotes passed: nobody quoted


def test_build_reads_the_spec_quotes_dir_and_the_cli_reports_a_package_error(tmp_path, capsys):
    import yaml

    from estimating_tools.estimate_spec.cli import main
    from estimating_tools.estimate_spec.tests._fieldbook import FIELDBOOK_DIR
    from estimating_tools.quotes.files import write_quote_file

    spec = packaged_spec()
    spec["work_packages"][0]["selected"] = "Nobody"
    spec["work_packages_quotes_dir"] = "bids"
    path = tmp_path / "spec.estimate.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    (tmp_path / "bids").mkdir()
    write_quote_file(tmp_path / "bids" / "dirt-movers--hauling.json", QUOTES[0])
    with pytest.raises(PackageError, match=r"\(vendors: Dirt Movers\)"):
        B.build(path, tmp_path / "out.xlsx", fieldbook_pack())
    rc = main(["build", str(path), "-o", str(tmp_path / "out.xlsx"), "--format", str(FIELDBOOK_DIR)])
    assert rc == 1
    assert "PackageError: Hauling: selected 'Nobody'" in capsys.readouterr().err


def test_a_quoted_vendors_ref_is_never_blank(tmp_path):
    import dataclasses
    from estimating_tools.quotes.files import load_quotes, write_quote_file
    write_quote_file(tmp_path / "bulk.json", QUOTES[1])
    loaded = load_quotes(tmp_path)
    quotes = [QUOTES[0], loaded[0], dataclasses.replace(QUOTES[2], quote_ref="VP-1")]
    refs = {v.name: v.quote_ref for fr in frames(quotes=quotes) for v in fr.vendors
            if not v.is_spare}
    assert refs == {"Dirt Movers": "2026-10-20",       # its date
                    "Bulk Haul Co": "bulk.json",      # the file it was read from
                    "Valve Pros": "VP-1"}             # its own ref
    plain = {v.name: v.quote_ref for fr in frames() for v in fr.vendors if not v.is_spare}
    assert plain["Bulk Haul Co"] == "bulk-haul-co--hauling.json"    # no file: its slug


# ------------------------------------------------------------ alternates (C2)

def _arr():
    spec = packaged_spec()
    spec["work_packages"][0]["selected"] = "ARR"
    return spec


def _two_line_hauling():
    """packaged_spec with a second Hauling line on item 2 task 02 (Dump fees,
    460 CY at a $4 plug), Hauling carried at ARR."""
    spec = packaged_spec()
    spec["work_packages"][0]["selected"] = "ARR"
    spec["items"][1]["labor"][1]["lines"].append(
        {"cost_type": "subcontract", "name": "Dump fees", "qty": 460, "uom": "CY",
         "unit_price": 4, "package": "Hauling"})
    return spec


def test_an_alternate_never_prices_and_shows_in_the_conditions_grid():
    q = CanonicalQuote(vendor_name="Alt Haul", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  unit_price=16.0),
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  unit_price=12.5, is_alternate=True),
    ])
    hauling = frame("Hauling", spec=_arr(), quotes=[q])
    alt = column(hauling, "Alt Haul")
    assert alt.cells == {HAUL_KEY: 16.0}                        # the base price, never 12.5
    assert hauling.conditions[-1] == "Alternate: Haul, import + export"
    (cond,) = [c for c in hauling.as_scope()["conditions"]
               if c["text"] == "Alternate: Haul, import + export"]
    assert cond["t0"] == "$12.50 / CY"
    assert cond["cells"] == {"Alt Haul": "$12.50 / CY"}


def test_an_alternate_alone_leaves_the_line_unquoted():
    q = CanonicalQuote(vendor_name="Alt Only", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  amount=5000.0, is_alternate=True)])
    hauling = frame("Hauling", spec=_arr(), quotes=[q])
    assert column(hauling, "Alt Only").cells == {}
    (line,) = hauling.as_scope()["lines"]
    assert line["c0"] == ""
    (cond,) = [c for c in hauling.as_scope()["conditions"] if c["text"].startswith("Alternate")]
    assert cond["t0"] == "$5,000.00 lump sum"


def test_two_base_lines_on_one_package_line_are_an_error():
    q = CanonicalQuote(vendor_name="Twice", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  unit_price=16.0),
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  unit_price=15.0),
    ])
    q.source_file = "twice--hauling.json"
    with pytest.raises(PackageError) as err:
        frame("Hauling", spec=_arr(), quotes=[q])
    assert str(err.value) == (
        "Hauling: twice--hauling.json: lines 1 and 2 both price item '2' line "
        "'Haul, import + export' -- keep one (mark the other is_alternate if it is an alternate)")


def test_alternate_rows_render_in_the_conditions_grid():
    from estimating_tools.estimate_spec.build import generate
    q = CanonicalQuote(vendor_name="Alt Haul", work_package_name="Hauling", lines=[
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  unit_price=16.0),
        QuoteLine(schedule_name="Base", item_number="2", line_name="Haul, import + export",
                  unit_price=12.5, is_alternate=True)])
    wb = generate(_arr(), fieldbook_pack(), quotes=[q, *QUOTES[1:]])
    ws = wb["Sub Hauling"]
    (r,) = [r for r in range(1, ws.max_row + 1)
            if ws[f"B{r}"].value == "Alternate: Haul, import + export"]
    assert ws[f"K{r}"].value == "$12.50 / CY"                  # under Alt Haul (column K)
    assert ws[f"M{r}"].value in (None, "")                     # Bulk Haul Co has none
    line = next(r for r in range(1, ws.max_row + 1) if ws[f"B{r}"].value == "Haul, import + export")
    assert ws[f"K{line}"].value == 16.0


# ------------------------------------------------------------ remainder (I10)

def test_an_amount_with_priced_lines_prorates_the_remainder():
    q = CanonicalQuote(vendor_name="Part Lump", work_package_name="Hauling", amount=9000.0,
                       lines=[QuoteLine(schedule_name="Base", item_number="2",
                                        line_name="Haul, import + export", unit_price=15.0)])
    hauling = frame("Hauling", spec=_two_line_hauling(), quotes=[q])
    col = column(hauling, "Part Lump")
    # 9,000 - 460 x 15 = 2,100 left for Dump fees (the only unpriced line)
    assert col.cells["2/02/0"] == 15.0
    assert col.prorated == {"2/02/1": pytest.approx(2100.0)}
    assert col.cells["2/02/1"] == pytest.approx(2100.0 / 460)
    assert (col.lump_sum, col.lump_amount, col.remainder) == (True, 9000.0, pytest.approx(2100.0))
    haul, dump = hauling.as_scope()["lines"]
    assert (haul["n0"], haul["p0"]) == ("", "input")
    assert dump["n0"] == "prorated from $2,100.00 remainder of $9,000.00 lump sum"
    assert dump["p0"] == "derived"


def test_a_remainder_is_shared_by_plug_extension_and_skips_excluded_lines():
    spec = _two_line_hauling()
    spec["items"][1]["labor"][1]["lines"].append(
        {"cost_type": "subcontract", "name": "Tarps", "qty": 1, "uom": "LS",
         "unit_price": 160, "package": "Hauling"})
    spec["items"][1]["labor"][1]["lines"].append(
        {"cost_type": "subcontract", "name": "Flagging", "qty": 1, "uom": "LS",
         "unit_price": 999, "package": "Hauling"})
    q = CanonicalQuote(vendor_name="Part Lump", work_package_name="Hauling", amount=10000.0,
                       lines=[QuoteLine(schedule_name="Base", item_number="2",
                                        line_name="Haul, import + export", unit_price=15.0),
                              QuoteLine(schedule_name="Base", item_number="2",
                                        line_name="Flagging", is_included=False)])
    col = column(frame("Hauling", spec=spec, quotes=[q]), "Part Lump")
    remainder = 10000.0 - 460 * 15.0                           # 3,100
    plug = {"2/02/1": 460 * 4, "2/02/2": 160}                  # Dump fees, Tarps
    assert col.cells["2/02/3"] == "excl"
    assert col.prorated == pytest.approx(
        {k: remainder * v / sum(plug.values()) for k, v in plug.items()})


def test_a_remainder_of_zero_or_less_is_an_error():
    q = CanonicalQuote(vendor_name="Over", work_package_name="Hauling", amount=6900.0,
                       lines=[QuoteLine(schedule_name="Base", item_number="2",
                                        line_name="Haul, import + export", unit_price=15.0)])
    q.source_file = "over--hauling.json"
    with pytest.raises(PackageError) as err:
        frame("Hauling", spec=_two_line_hauling(), quotes=[q])
    assert str(err.value) == (
        "Hauling: over--hauling.json: the lump sum $6,900.00 less the priced lines' extensions "
        "leaves $0.00 for the unpriced lines (Dump fees) -- nothing to prorate")


def test_an_amount_whose_lines_price_everything_is_not_prorated():
    q = CanonicalQuote(vendor_name="Total", work_package_name="Hauling", amount=1.0,
                       lines=[QuoteLine(schedule_name="Base", item_number="2",
                                        line_name="Haul, import + export", unit_price=15.0)])
    col = column(frame("Hauling", spec=_arr(), quotes=[q]), "Total")
    assert (col.cells, col.prorated, col.lump_sum) == ({HAUL_KEY: 15.0}, {}, False)


# ------------------------------------------------------------ braces (I8)

def _braced_quotes():
    q = copy.deepcopy(QUOTES)
    q[0].conditions["Fuel surcharge"] = "per DOT index {monthly}"
    q[0].quote_ref = "Q-{7}"
    q[0].source_file = "dirt-movers--hauling.json"
    return q


def test_braces_in_quote_text_render_literally():
    from estimating_tools.estimate_spec.build import generate
    from estimating_tools.estimate_spec.readback import read_back
    quotes = _braced_quotes()
    wb = generate(packaged_spec(), fieldbook_pack(), quotes=quotes)
    values = {c.value for row in wb["Sub Hauling"].iter_rows() for c in row}
    assert {"per DOT index {monthly}", "Q-{7}"} <= values
    rb = read_back(packaged_spec(), wb, fieldbook_pack(), quotes=quotes)
    assert (rb.findings.problems, rb.quote_writes, rb.findings.changes) == ([], [], [])


def test_a_quote_text_the_resolver_cannot_render_names_the_file(monkeypatch):
    # The guard behind the literal binding: were quote text ever resolved,
    # the failure names the quote file, not a bare placeholder error.
    from estimating_tools.estimate_spec import build
    monkeypatch.setattr(build, "literal", lambda text: str(text))
    quotes = _braced_quotes()
    quotes[0].quote_ref = "Q-7"
    with pytest.raises(PackageError) as err:
        build.generate(packaged_spec(), fieldbook_pack(), quotes=quotes)
    assert str(err.value) == "dirt-movers--hauling.json: text {monthly} cannot be rendered"


def test_duplicate_package_line_names_are_refused_before_matching_quote_prices():
    spec = packaged_spec()
    lines = spec["items"][1]["labor"][1]["lines"]
    (haul,) = [line for line in lines if line.get("package") == "Hauling"]
    lines.append(copy.deepcopy(haul))
    with pytest.raises(PackageError, match="duplicate package line name"):
        frames(spec=spec)


def test_package_names_cannot_collide_under_quote_matching_rules():
    spec = packaged_spec()
    duplicate = copy.deepcopy(spec["work_packages"][0])
    duplicate["name"] = " hauling "
    spec["work_packages"].append(duplicate)
    with pytest.raises(ValueError, match="duplicate package name"):
        B.generate(spec, fieldbook_pack(), quotes=QUOTES)
