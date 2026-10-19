"""Fieldbook's work-package spreads price the bid -- evaluated with pycel.

Built from the pack's shipped example, `examples/demo-packages.estimate.yaml`,
with its quote files (`examples/quotes/*.json`), so the example data is what is
exercised. The figures (8 h shifts, the demo rates):

- Item 2 task 02-200 (support task): crew 8,376.00 = EO 1x3x8x82 1,968 +
  Laborer 2x3x8x61 2,928 + Loader 3x8x110 2,640 + compactor 3x8x35 840.
  Its haul line, 460 CY: Dirt Movers 16.50 x 1.04 = 17.16 -> 7,893.60 (subtotal
  16,269.60); ARR plug 18.00 -> 8,280.00 (16,656.00); Bulk Haul Co's 8,740 lump
  sum prorated over the one line -> 19.00 -> 8,740.00 (17,116.00).
- Item 3 task 02-510 (self-perform): ARR crew Pipelayer 2x2x8x74 2,368 +
  Laborer 1x2x8x61 976 = 3,344 + boxes 4x650 2,600 = 5,944.00; Valve Pros
  carried: crew off + 4x900 = 3,600.00; CARRY 850/EA: crew off + 3,400.00.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec.package_frames import PackageError
from estimating_tools.estimate_spec.tests._fieldbook import (
    FIELDBOOK_DIR, check_statuses, fieldbook_pack, packaged_spec, task_block)
from estimating_tools.estimate_spec.tests._formula_eval import evaluate
from estimating_tools.quotes.files import load_quotes

EXAMPLE_PACKAGES = FIELDBOOK_DIR / "examples" / "demo-packages.estimate.yaml"
QUOTES_DIR = FIELDBOOK_DIR / "examples" / "quotes"
ITEM2, ITEM3 = "2 - 8IN MAIN", "3 - VALVES"
HAUL, BOXES = "Haul, import + export", "Valve boxes (subcontract)"


def _spec() -> dict:
    return yaml.safe_load(EXAMPLE_PACKAGES.read_text(encoding="utf-8"))


def _package(spec: dict, name: str) -> dict:
    (pkg,) = [p for p in spec["work_packages"] if p["name"] == name]
    return pkg


def _build(spec: dict, tmp_path):
    wb = B.generate(spec, fieldbook_pack(), quotes=load_quotes(QUOTES_DIR))
    return wb, evaluate(wb, tmp_path)


def _selecting(package: str, selected: str, **extra) -> dict:
    spec = _spec()
    _package(spec, package).update(selected=selected, **extra)
    return spec


def _row(ws, col, value, start=1) -> int:
    return next(r for r in range(start, ws.max_row + 1) if ws[f"{col}{r}"].value == value)


def _col(ws, hdr: int, label: str) -> str:
    return next(c.column_letter for c in ws[hdr] if c.value == label)


def _spread_line(ws, name: str) -> int:
    """The line row of `name` on a package sheet (below its vendors header)."""
    hdr = next(r for r in range(1, ws.max_row + 1)
               if ws[f"A{r}"].value == "Item" and ws[f"B{r}"].value == "Line")
    return _row(ws, "B", name, start=hdr + 1)


def _item_line(ws, code: str, name: str) -> int:
    (r,) = [r for r in task_block(ws, code)["LINE"] if ws[f"A{r}"].value == name]
    return r


def _subtotal(ws, code: str) -> int:
    return task_block(ws, code)["SUBTOTAL"][0]


def _check_10(wb, ev, package: str):
    """Check 10's status for `package`, evaluating that row only (pycel's SUMIF
    raises on an #N/A in its range where Excel returns #N/A, so the item
    checks of a deliberately broken workbook are not evaluated here)."""
    ws = wb["Checks"]
    r = next(r for r in range(1, ws.max_row + 1)
             if ws[f"A{r}"].value == 10 and ws[f"C{r}"].value == package)
    return ev[f"Checks!F{r}"]


def _crew_cost(ws, ev, sheet: str, code: str) -> float:
    return sum(ev[f"{sheet}!P{r}"] for r in task_block(ws, code)["CREW"])


@pytest.fixture(scope="module")
def example(tmp_path_factory):
    return _build(_spec(), tmp_path_factory.mktemp("packages"))


def test_the_shipped_example_is_the_packaged_fixture():
    assert _spec() == packaged_spec()
    assert sorted(q.vendor_name for q in load_quotes(QUOTES_DIR)) == [
        "Bulk Haul Co", "Dirt Movers", "Valve Pros"]


def test_the_carried_vendor_prices_the_item(example):
    wb, ev = example
    item, sub = wb[ITEM2], wb["Sub Hauling"]
    r = _spread_line(sub, HAUL)
    assert ev[f"Sub Hauling!F{r}"] == pytest.approx(17.16)
    assert ev[f"Sub Hauling!G{r}"] == pytest.approx(7893.60)
    line = _item_line(item, "02-200", HAUL)
    assert ev[f"{ITEM2}!G{line}"] == pytest.approx(17.16)
    assert ev[f"{ITEM2}!P{line}"] == pytest.approx(7893.60)
    assert (ev[f"{ITEM2}!I{line}"], ev[f"{ITEM2}!J{line}"]) == ("QUOTE", "Dirt Movers")
    assert ev[f"{ITEM2}!P{_subtotal(item, '02-200')}"] == pytest.approx(16269.60)


def test_arr_keeps_the_plug(tmp_path):
    wb, ev = _build(_selecting("Hauling", "ARR"), tmp_path)
    item = wb[ITEM2]
    line = _item_line(item, "02-200", HAUL)
    assert ev[f"{ITEM2}!G{line}"] == pytest.approx(18.0)
    assert ev[f"{ITEM2}!P{line}"] == pytest.approx(8280.00)
    assert ev[f"{ITEM2}!I{line}"] == "PLUG"
    assert ev[f"{ITEM2}!P{_subtotal(item, '02-200')}"] == pytest.approx(16656.00)


def test_a_self_perform_task_switches_off_when_a_vendor_is_carried(example, tmp_path):
    wb, ev = example                                    # Valves carried at ARR: own crew on
    sub = _subtotal(wb[ITEM3], "02-510")
    assert _crew_cost(wb[ITEM3], ev, ITEM3, "02-510") == pytest.approx(3344.00)
    assert ev[f"{ITEM3}!P{sub}"] == pytest.approx(5944.00)

    wb, ev = _build(_selecting("Valves", "Valve Pros"), tmp_path)
    ws = wb[ITEM3]
    sub = _subtotal(ws, "02-510")
    assert ev[f"{ITEM3}!P{sub}"] == pytest.approx(3600.00)
    assert ev[f"{ITEM3}!K{sub}"] == 0                 # crew hours off
    assert _crew_cost(ws, ev, ITEM3, "02-510") == 0
    line = _item_line(ws, "02-510", BOXES)
    assert (ev[f"{ITEM3}!G{line}"], ev[f"{ITEM3}!J{line}"]) == (900, "Valve Pros")


def test_a_support_task_stays(example, tmp_path):
    wb, ev = example                                    # Hauling carried at Dirt Movers
    assert _crew_cost(wb[ITEM2], ev, ITEM2, "02-200") == pytest.approx(8376.00)
    wb2, ev2 = _build(_selecting("Hauling", "ARR"), tmp_path)
    assert _crew_cost(wb2[ITEM2], ev2, ITEM2, "02-200") == pytest.approx(8376.00)
    ws = wb[ITEM2]
    for r in task_block(ws, "02-200")["CREW"]:          # no switch on a support crew
        assert "Sub " not in str(ws[f"E{r}"].value)


def test_a_lump_sum_is_prorated_and_flagged(tmp_path):
    wb, ev = _build(_selecting("Hauling", "Bulk Haul Co"), tmp_path)
    r = _spread_line(wb["Sub Hauling"], HAUL)
    assert ev[f"Sub Hauling!F{r}"] == pytest.approx(19.00)
    assert ev[f"Sub Hauling!G{r}"] == pytest.approx(8740.00)
    item = wb[ITEM2]
    line = _item_line(item, "02-200", HAUL)
    assert ev[f"{ITEM2}!P{line}"] == pytest.approx(8740.00)
    assert ev[f"{ITEM2}!J{line}"] == "Bulk Haul Co"
    assert ev[f"{ITEM2}!P{_subtotal(item, '02-200')}"] == pytest.approx(17116.00)
    ss = wb["Sub Spreads"]
    row = _row(ss, "A", "Hauling")
    assert ss[f"J{row}"].value == "LUMP SUM"
    assert ev[f"Sub Spreads!H{row}"] == pytest.approx(8740.00)


def test_spread_qty_links_to_a_formula_line(example, tmp_path):
    spec = _spec()
    (item2,) = [i for i in spec["items"] if i["item_no"] == "2"]
    (line,) = [ln for b in item2["labor"] for ln in b.get("lines", []) if ln["name"] == HAUL]
    line["qty"] = "=460*1"
    # A lump sum is prorated over the lines' plug extensions at build time, so
    # it needs a numeric qty: with Bulk Haul Co's lump sum in the quotes the
    # build refuses (loudly); the priced quotes link through a formula qty.
    with pytest.raises(PackageError, match="Bulk Haul Co quotes a lump sum.*numeric qty"):
        B.generate(copy.deepcopy(spec), fieldbook_pack(), quotes=load_quotes(QUOTES_DIR))
    priced = [q for q in load_quotes(QUOTES_DIR) if q.amount is None]
    wb = B.generate(spec, fieldbook_pack(), quotes=priced)
    ev = evaluate(wb, tmp_path)
    r = _spread_line(wb["Sub Hauling"], HAUL)
    d = wb["Sub Hauling"][f"D{r}"].value
    assert d.startswith(f"='{ITEM2}'!"), d
    assert ev[f"Sub Hauling!D{r}"] == 460
    item_line = _item_line(wb[ITEM2], "02-200", HAUL)
    assert wb[ITEM2][f"B{item_line}"].value == "=460*1"
    base_wb, base_ev = example
    total = _row(wb[ITEM2], "A", "ITEM TOTAL")
    assert total == _row(base_wb[ITEM2], "A", "ITEM TOTAL")
    assert ev[f"{ITEM2}!P{total}"] == pytest.approx(base_ev[f"{ITEM2}!P{total}"])
    assert ev[f"{ITEM2}!P{_subtotal(wb[ITEM2], '02-200')}"] == pytest.approx(16269.60)


def test_an_unknown_selector_is_a_build_error():
    with pytest.raises(PackageError) as err:
        B.generate(_selecting("Hauling", "Dirt Mover"), fieldbook_pack(),
                   quotes=load_quotes(QUOTES_DIR))
    msg = str(err.value)
    assert "Dirt Mover" in msg and "Dirt Movers" in msg and "Bulk Haul Co" in msg


def test_check_10_passes_on_the_example(example):
    wb, ev = example
    status = check_statuses(wb, ev)
    assert status[(10, "Hauling")] == "✓"
    assert status[(10, "Valves")] == "✓"
    assert set(status.values()) == {"✓"}


def test_a_carry_source_with_no_figure_is_loud(tmp_path):
    wb, ev = _build(_selecting("Valves", "CARRY"), tmp_path)
    sub = wb["Sub Valves"]
    r = _spread_line(sub, BOXES)
    hdr = _row(sub, "A", "Item")
    assert sub[f"{_col(sub, hdr, 'CARRY')}{r}"].value in (None, "")
    assert ev[f"Sub Valves!F{r}"] == "#N/A"
    ws = wb[ITEM3]
    line = _item_line(ws, "02-510", BOXES)
    assert ev[f"{ITEM3}!G{line}"] == "#N/A"
    assert ev[f"{ITEM3}!P{line}"] == "#N/A"
    assert ev[f"{ITEM3}!P{_subtotal(ws, '02-510')}"] == "#N/A"
    assert _check_10(wb, ev, "Valves") == "✗"
    assert _check_10(wb, ev, "Hauling") == "✓"


def test_a_carry_figure_prices_the_line(tmp_path):
    wb, ev = _build(_selecting("Valves", "CARRY", carry={"3": 850}), tmp_path)
    ws = wb[ITEM3]
    line = _item_line(ws, "02-510", BOXES)
    assert ev[f"{ITEM3}!G{line}"] == 850
    assert ev[f"{ITEM3}!P{line}"] == pytest.approx(3400.00)
    sub = _subtotal(ws, "02-510")
    assert ev[f"{ITEM3}!K{sub}"] == 0
    assert ev[f"{ITEM3}!P{sub}"] == pytest.approx(3400.00)
    assert check_statuses(wb, ev)[(10, "Valves")] == "✓"


def test_every_check_passes_with_a_vendor_carried(tmp_path):
    # Valve Pros carried on Valves: item 3's self-perform crew and lines go to
    # 0 (U = SP) -- still a priced line for rule 3, not a missing price.
    wb, ev = _build(_selecting("Valves", "Valve Pros"), tmp_path)
    status = check_statuses(wb, ev)
    assert status[(3, 3)] == "✓"
    assert set(status.values()) == {"✓"}, {k: v for k, v in status.items() if v != "✓"}


def test_a_switched_off_self_perform_line_is_a_priced_line_for_rule_3(tmp_path):
    # A material line of item 3's self-perform task: Valve Pros carried, its
    # qty is 4 x factor 0 = 0 (U = SP, full basis in V) -- rule 3 stays ✓.
    spec = _selecting("Valves", "Valve Pros")
    (item3,) = [i for i in spec["items"] if i["item_no"] == "3"]
    item3["labor"][0]["lines"].append(
        {"cost_type": "material", "name": "Gaskets", "qty": 4, "uom": "EA",
         "unit_price": 10, "source": "plug"})
    wb, ev = _build(spec, tmp_path)
    ws = wb[ITEM3]
    gaskets = _item_line(ws, "02-510", "Gaskets")
    assert (ws[f"U{gaskets}"].value, ev[f"{ITEM3}!B{gaskets}"]) == ("SP", 0)
    status = check_statuses(wb, ev)
    assert status[(3, 3)] == "✓"
    assert set(status.values()) == {"✓"}, {k: v for k, v in status.items() if v != "✓"}


def test_a_folded_package_line_is_a_priced_line_for_rule_3(tmp_path):
    # A second Valves line on item 3 that Valve Pros folds into the boxes
    # (state incl, price 0): rule 3 stays ✓.
    spec = _selecting("Valves", "Valve Pros")
    (item3,) = [i for i in spec["items"] if i["item_no"] == "3"]
    item3["labor"][0]["lines"].append(
        {"cost_type": "subcontract", "name": "Box risers", "qty": 4, "uom": "EA",
         "unit_price": 80, "package": "Valves"})
    quotes = load_quotes(QUOTES_DIR)
    (vp,) = [q for q in quotes if q.vendor_name == "Valve Pros"]
    from estimating_tools.quotes.model import QuoteLine
    vp.lines.append(QuoteLine(schedule_name="Base", item_number="3", line_name="Box risers",
                              folded_into=BOXES))
    wb = B.generate(spec, fieldbook_pack(), quotes=quotes)
    ev = evaluate(wb, tmp_path)
    ws = wb[ITEM3]
    risers = _item_line(ws, "02-510", "Box risers")
    assert ev[f"{ITEM3}!G{risers}"] == 0
    status = check_statuses(wb, ev)
    assert status[(3, 3)] == "✓"
    assert set(status.values()) == {"✓"}, {k: v for k, v in status.items() if v != "✓"}


def test_rule_3_still_flags_a_zero_qty_line_while_arr_prices_it(tmp_path):
    spec = _spec()                                       # Valves at ARR: factor 1
    (item3,) = [i for i in spec["items"] if i["item_no"] == "3"]
    item3["labor"][0]["lines"].append(
        {"cost_type": "material", "name": "Grease", "qty": 0, "uom": "EA",
         "unit_price": 5, "source": "plug"})
    wb, ev = _build(spec, tmp_path)
    assert check_statuses(wb, ev)[(3, 3)] == "✗"
