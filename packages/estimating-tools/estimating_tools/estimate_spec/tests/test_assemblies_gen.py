"""Assembly generator: per-item bulk_create_assemblies payloads and the report."""
from __future__ import annotations

import json

import pytest

from estimating_tools.estimate_spec.assemblies_gen import (
    GenError, GenResult, compare_payloads, generate_assemblies, repush_plan, totals_by_type)
from estimating_tools.estimate_spec.bm_sync.sidecar import Sidecar
from estimating_tools.estimate_spec.tests._bm_fixture import spec_two_packages


def _item(spec, item_no):
    return next(i for i in spec["items"] if i["item_no"] == item_no)


def test_crew_assembly_shape_item_61():
    r = generate_assemblies(spec_two_packages(), bid="T1")
    crew = r.payloads["61"][0]
    assert crew["assembly_type"] == "CREW" and crew["external_id"] == "T1:61:01:crew"
    assert crew["name"].startswith("01 51-100 crew: ") and crew["production_rate"] == 16.0 and crew["production_unit"] == "HOURS"
    assert crew["hours_per_shift"] == 8 and crew["basis_quantity"] == 1000 and crew["basis_unit"] == "LB"
    assert crew["external_source"] == "ESTIMATING_PLUGIN"
    c = crew["components"]
    assert c[0] == {"component_type": "labor", "name": "01 Foreman", "quantity": 1, "unit": "EA", "unit_cost": 136.46, "trade": "Foreman", "description": "1 x 2 days x 8 h, production basis", "sort_order": 0}
    assert c[1]["quantity"] == 2 and c[1]["name"] == "02 Laborer"
    assert c[2] == {"component_type": "equipment", "name": "03 Excavator, 320 class", "quantity": 8.0, "unit": "HR", "unit_cost": 66.0, "trade": "Excavator, 320 class", "description": "1 x 1 days x 8 h", "sort_order": 2}


def test_part_time_labor_is_flat_man_hours():
    spec = spec_two_packages()
    _item(spec, "61")["labor"][0]["crew"][1]["days"] = 1
    laborer = generate_assemblies(spec, bid="T1").payloads["61"][0]["components"][1]
    assert laborer["labor_cost_basis"] == "flat"
    assert laborer["quantity"] == 16.0 and laborer["unit"] == "MH"
    assert laborer["description"] == "2 x 1 days x 8 h, flat"


def test_generic_assembly_includes_package_lines_with_description():
    r = generate_assemblies(spec_two_packages(), bid="T1")
    gen = r.payloads["61"][1]
    assert gen["assembly_type"] == "GENERIC" and gen["external_id"] == "T1:61:01:lines" and gen["name"] == "01 51-100 lines: material / sub / other"
    assert gen["description"] == "cost lines from the fieldbook task (plugs unless a vendor is named)"
    assert set(gen) == {"name", "assembly_type", "description", "external_source", "external_id", "components"}
    assert gen["components"][0] == {"component_type": "subcontractor", "name": "01 Rebar furnished and placed", "quantity": 1000, "unit": "LB", "unit_cost": 1.8, "description": "plug; package Reinforcing steel", "sort_order": 0}
    assert gen["components"][1]["component_type"] == "material" and gen["components"][2]["description"] == "plug"


def test_quote_line_with_vendor_names_the_vendor():
    spec = spec_two_packages()
    _item(spec, "61")["labor"][0]["lines"][0]["vendor"] = "Acme Rebar"
    gen = generate_assemblies(spec, bid="T1").payloads["61"][1]
    assert gen["components"][0]["description"] == "quote Acme Rebar; package Reinforcing steel"


def test_self_perform_task_is_emitted_at_full_crew_and_reported():
    r = generate_assemblies(spec_two_packages(), bid="T1")
    slot02 = [p for p in r.payloads["61"] if p["external_id"] == "T1:61:02:crew"]
    assert len(slot02) == 1 and slot02[0]["production_rate"] == 8.0
    assert "## Self-perform tasks" in r.report
    assert "61 slot 02: switched off in the workbook when Reinforcing steel is carried" in r.report


def test_task_without_crew_emits_generic_only():
    spec = spec_two_packages()
    _item(spec, "39")["labor"][0]["crew"] = []
    payloads = generate_assemblies(spec, bid="T1").payloads["39"]
    assert [p["assembly_type"] for p in payloads] == ["GENERIC"]


def test_task_with_neither_crew_nor_lines_is_skipped_and_reported():
    spec = spec_two_packages()
    blk = _item(spec, "39")["labor"][0]
    blk["crew"], blk["lines"] = [], []
    r = generate_assemblies(spec, bid="T1")
    assert "39" not in r.payloads
    assert "## Skipped" in r.report and "39 slot 01" in r.report


def test_unknown_trade_is_an_error():
    spec = spec_two_packages()
    _item(spec, "61")["labor"][0]["crew"].append({"trade": "Welder", "count": 1, "days": 1})
    with pytest.raises(GenError, match="item 61 slot 01: trade 'Welder' is in no rate table"):
        generate_assemblies(spec, bid="T1")


def test_formula_days_evaluate():
    spec = spec_two_packages()
    blk = _item(spec, "62")["labor"][0]
    blk["activities"] = [{"factor": 1.5}, {"factor": 1.5}]
    blk["crew_factor"] = 1.0
    blk["crew"] = [{"trade": "Foreman", "count": 1, "days": "{ref:labor[01].prod_days}"},
                   {"trade": "Laborer", "count": 2, "days": "=crew_first"},
                   {"trade": "Excavator, 320 class", "count": 1, "days": "=1+0.5"}]
    crew = generate_assemblies(spec, bid="T1").payloads["62"][0]
    assert crew["production_rate"] == 24.0
    c = crew["components"]
    assert c[0]["description"] == "1 x 3 days x 8 h, production basis"
    assert c[1]["description"] == "2 x 3 days x 8 h, production basis"
    assert c[2]["quantity"] == 12.0 and c[2]["description"] == "1 x 1.5 days x 8 h"


def test_report_lists_package_lines_and_totals():
    r = generate_assemblies(spec_two_packages(), bid="T1")
    assert "## Reinforcing steel" in r.report and "61 · 01 Rebar furnished and placed · 1000 × 1.80 = 1,800.00" in r.report and "total 2,300.00" in r.report
    assert "## Ready-mix concrete" in r.report and "total 27,010.00" in r.report
    rows = r.package_lines["Reinforcing steel"]
    assert [(x.item_no, x.slot, x.line_name, x.value, x.component_name) for x in rows] == [
        ("61", "01", "Rebar furnished and placed", 1800.0, "01 Rebar furnished and placed"),
        ("61", "01", "Couplers", 500.0, "02 Couplers")]


def test_totals_by_type():
    r = generate_assemblies(spec_two_packages(), bid="T1")
    assert totals_by_type(r.payloads["61"]) == {
        "labor": round(1 * 136.46 * 16 + 2 * 88.37 * 16 + 88.37 * 8, 2),
        "equipment": round(8 * 66.0 + 16 * 8.5 + 8 * 28.0, 2),
        "material": 500.0, "subcontractor": 1800.0, "other": 60.0}


def test_activities_without_a_crew_factor_are_an_error():
    spec = spec_two_packages()
    blk = _item(spec, "62")["labor"][0]
    blk["activities"] = [{"factor": 1.0}]
    blk["crew"][0]["days"] = "{ref:labor[01].prod_days}"
    with pytest.raises(GenError, match="item 62 slot 01: activities need a crew_factor"):
        generate_assemblies(spec, bid="T1")


def test_long_names_are_cut_to_255_characters():
    spec = spec_two_packages()
    blk = _item(spec, "61")["labor"][0]
    blk["description"] = "x" * 300
    blk["lines"][0]["name"] = "y" * 300
    blk["crew"][0]["trade"] = "F" * 300
    spec["rate_table"].append({"trade": "F" * 300, "rate": 136.46})
    crew, gen = generate_assemblies(spec, bid="T1").payloads["61"][:2]
    assert len(crew["name"]) == 255 and crew["name"].startswith("01 51-100 crew: xxx")
    assert len(gen["name"]) <= 255
    assert len(crew["components"][0]["name"]) == 255 and crew["components"][0]["name"].startswith("01 FFF")
    assert len(gen["components"][0]["name"]) == 255 and gen["components"][0]["name"].startswith("01 yyy")


def test_zero_day_members_are_skipped():
    spec = spec_two_packages()
    _item(spec, "61")["labor"][0]["crew"][1]["days"] = 0
    c = generate_assemblies(spec, bid="T1").payloads["61"][0]["components"]
    assert "Laborer" not in [x["trade"] for x in c]
    assert [(x["name"], x["sort_order"]) for x in c[:2]] == [("01 Foreman", 0), ("02 Excavator, 320 class", 1)]
    assert all(x["quantity"] for x in c)


def test_carried_forward_cell_ref_days_are_recorded_in_carries():
    spec = spec_two_packages()
    _item(spec, "62")["labor"][0]["crew"].append({"trade": "Laborer", "count": 1, "days": "=B12"})
    carries: list = []
    generate_assemblies(spec, bid="T1", carries=carries)
    assert carries and carries[0]["formula"] == "=B12" and "labor[01] Laborer days" in carries[0]["where"]


def _removed(assembly_id, component_id, name=None):
    return {"assembly_id": assembly_id, "component_id": component_id, "name": name}


def _sidecar(**removed) -> Sidecar:
    sc = Sidecar()
    sc.package("Reinforcing steel").plugs_removed = removed
    return sc


def test_repush_plan_names_deletes_then_create_then_restore():
    r = generate_assemblies(spec_two_packages(), bid="T1")
    ids = {"assemblies": {"61": {"T1:61:01:crew": 3616, "T1:61:01:lines": 3617}}}
    text = repush_plan(r, ids, _sidecar(**{"61": [_removed(3617, 9001)]}))
    assert "delete_assembly 3616" in text and "delete_assembly 3617" in text
    assert "bulk_create_assemblies 61 (3 assemblies)" in text
    assert "re-remove: 61 · 01 Rebar furnished and placed" in text
    assert text.index("delete_assembly 3617") < text.index("bulk_create_assemblies 61") \
        < text.index("re-remove: 61")


def test_repush_plan_flags_a_partial_removal_and_unknown_assemblies():
    """Nameless (legacy) records: fewer removed than package lines means the plan cannot
    tell which, so every line is listed with a note to confirm."""
    r = generate_assemblies(spec_two_packages(), bid="T1")
    ids = {"assemblies": {"61": {"T1:61:01:lines": 3617}, "99": {"T1:99:01:crew": 3700}}}
    text = repush_plan(r, ids, _sidecar(**{"61": [_removed(3617, 9001), _removed(5555, 1)]}))
    assert "re-remove: 61 · 02 Couplers" in text
    assert "1 of 2 Reinforcing steel line(s) on T1:61:01:lines were removed (3617:9001)" in text
    assert "re-remove: 61 · 5555:1 (assembly not in the existing ids)" in text
    assert "delete_assembly 3700" in text and "no generated payload for 99" in text


def test_repush_plan_uses_recorded_names_for_a_partial_removal():
    """#428: a record that carries the component name re-removes exactly that line; no
    confirm-which note, and an unmatched assembly is named too."""
    r = generate_assemblies(spec_two_packages(), bid="T1")
    ids = {"assemblies": {"61": {"T1:61:01:lines": 3617}}}
    text = repush_plan(r, ids, _sidecar(**{"61": [_removed(3617, 9002, "02 Couplers"),
                                                  _removed(5555, 1, "03 Small tools")]}))
    lines = [ln for ln in text.splitlines() if ln.startswith("- re-remove: 61") or ln.startswith("- note:")]
    assert lines == ["- re-remove: 61 · 02 Couplers",
                     "- re-remove: 61 · 5555:1 03 Small tools (assembly not in the existing ids)"]


def _lines_payload(*names):
    return {"61": [{"external_id": "T1:61:01:lines",
                    "components": [{"name": n, "description": "x; package Reinforcing steel"} for n in names]}]}


def test_repush_plan_matches_a_recorded_name_with_its_prefix_stripped():
    """#432 review: push matches BidSheet.ai components to spec lines with the two-digit
    prefix stripped, so a record may carry another position's prefix than the regenerated
    line; a unique prefix-stripped match names the line."""
    r = GenResult(_lines_payload("01 Rebar", "02 Couplers"), "", {})
    text = repush_plan(r, {"assemblies": {"61": {"T1:61:01:lines": 3617}}},
                       _sidecar(**{"61": [_removed(3617, 9002, "07 Couplers")]}))
    lines = [ln for ln in text.splitlines() if ln.startswith("- re-remove") or ln.startswith("- note")]
    assert lines == ["- re-remove: 61 · 02 Couplers"]


def test_repush_plan_asks_when_a_stripped_name_matches_two_lines():
    r = GenResult(_lines_payload("02 Couplers", "05 Couplers"), "", {})
    text = repush_plan(r, {"assemblies": {"61": {"T1:61:01:lines": 3617}}},
                       _sidecar(**{"61": [_removed(3617, 9002, "07 Couplers")]}))
    lines = [ln for ln in text.splitlines() if ln.startswith("- re-remove") or ln.startswith("- note")]
    assert lines == ["- re-remove: 61 · 02 Couplers", "- re-remove: 61 · 05 Couplers",
                     "- note: 3617:9002 07 Couplers matches 2 Reinforcing steel line(s) on T1:61:01:lines "
                     "(02 Couplers, 05 Couplers); confirm which to remove again"]


def test_repush_plan_reads_the_flat_ids_layout():
    r = generate_assemblies(spec_two_packages(), bid="T1")
    text = repush_plan(r, {"assemblies": {"T1:61:01:crew": 3616, "T1:61:01:lines": 3617}}, None)
    assert "delete_assembly 3616" in text and "delete_assembly 3617" in text


def _write(result, d):
    d.mkdir(exist_ok=True)
    for item_no, payloads in result.payloads.items():
        (d / f"{item_no}.json").write_text(json.dumps(payloads, indent=2))


def test_compare_matches_itself(tmp_path):
    r = generate_assemblies(spec_two_packages(), bid="T1")
    _write(r, tmp_path)
    rep = compare_payloads(r, tmp_path)
    assert rep.ok
    assert rep.render().startswith(f"compare: {len(r.payloads)} item(s), {len(r.payloads)} ok, 0 with differences")


def test_compare_reports_total_and_name_drift(tmp_path):
    r = generate_assemblies(spec_two_packages(), bid="T1")
    _write(r, tmp_path)
    old = json.loads((tmp_path / "61.json").read_text())
    old[1]["components"][0].update(unit_cost=1.9, name="01 Rebar placed")
    (tmp_path / "61.json").write_text(json.dumps(old))
    rep = compare_payloads(r, tmp_path)
    assert not rep.ok
    text = rep.render()
    assert "## 61" in text
    assert "61 T1:61:01:lines subcontractor 1,800.00 vs 1,900.00" in text
    assert "name only in existing: 01 Rebar placed" in text
    assert "name only in generated: 01 Rebar furnished and placed" in text


def test_compare_tolerates_names_truncated_past_100_characters(tmp_path):
    spec = spec_two_packages()
    _item(spec, "61")["labor"][0]["lines"][0]["name"] = "y" * 200
    r = generate_assemblies(spec, bid="T1")
    _write(r, tmp_path)
    old = json.loads((tmp_path / "61.json").read_text())
    old[1]["components"][0]["name"] = old[1]["components"][0]["name"][:120]
    (tmp_path / "61.json").write_text(json.dumps(old))
    assert compare_payloads(r, tmp_path).ok
    old[1]["components"][0]["name"] = old[1]["components"][0]["name"][:90]
    (tmp_path / "61.json").write_text(json.dumps(old))
    assert not compare_payloads(r, tmp_path).ok


def test_compare_reports_missing_and_extra_assemblies_and_files(tmp_path):
    r = generate_assemblies(spec_two_packages(), bid="T1")
    _write(r, tmp_path)
    old = json.loads((tmp_path / "61.json").read_text())
    old[0]["external_id"] = "T1:61:09:crew"
    old[1]["components"].pop()
    (tmp_path / "61.json").write_text(json.dumps(old))
    (tmp_path / "62.json").unlink()
    (tmp_path / "77.json").write_text("[]")
    text = compare_payloads(r, tmp_path).render()
    assert "assembly missing in existing: T1:61:01:crew" in text
    assert "assembly only in existing: T1:61:09:crew" in text
    assert f"T1:61:01:lines: component count {len(r.payloads['61'][1]['components'])} vs " \
           f"{len(r.payloads['61'][1]['components']) - 1}" in text
    assert "file missing in existing: 62.json" in text
    assert "file only in existing: 77.json" in text
