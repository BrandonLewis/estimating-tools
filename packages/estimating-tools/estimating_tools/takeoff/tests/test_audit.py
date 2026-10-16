"""Unit tests for the pure audit assembler (dict fixtures, no I/O)."""
import pytest

from estimating_tools.takeoff.audit import AuditFinding, build_audit, load_bm_snapshot
from estimating_tools.takeoff.model import CanonicalTakeoff, TakeoffRow


def _snapshot(**over):
    d = {"estimate_ref": "sample-bridge", "fetched_at": "2026-08-11T00:00:00Z",
         "items": [{"schedule": "A", "item_number": "12",
                    "description": "Structural Concrete", "unit": "SF",
                    "estimate_qty": 480.0,
                    "structures": [{"structure_id": "HW-3", "sections": []}]}]}
    d.update(over)
    return d


def test_valid_snapshot_loads():
    snap = load_bm_snapshot(_snapshot())
    assert snap["items"][0]["estimate_qty"] == 480.0


def test_snapshot_must_be_object_with_items_list():
    with pytest.raises(ValueError, match="items"):
        load_bm_snapshot({"estimate_ref": "x"})
    with pytest.raises(ValueError, match="object"):
        load_bm_snapshot([1, 2])


def test_snapshot_item_missing_fields_names_the_item():
    bad = _snapshot(items=[{"schedule": "A", "item_number": "12"}])
    with pytest.raises(ValueError, match=r"items\[0\].*unit"):
        load_bm_snapshot(bad)


def test_snapshot_qty_must_be_number():
    bad = _snapshot()
    bad["items"][0]["estimate_qty"] = "lots"
    with pytest.raises(ValueError, match="estimate_qty"):
        load_bm_snapshot(bad)


def test_snapshot_structure_entries_must_be_objects():
    # bare strings would crash the assembler later (s.get on a str) — the
    # spec's posture is fail loudly at load
    bad = _snapshot()
    bad["items"][0]["structures"] = ["HW-3"]
    with pytest.raises(ValueError, match=r"structures\[0\]"):
        load_bm_snapshot(bad)


def test_finding_kind_is_validated():
    with pytest.raises(ValueError, match="unknown finding kind"):
        AuditFinding("typo-kind", "", "x")


def _row(**over):
    base = dict(description="Structural Concrete", kind="quantity",
                quantity=480.0, unit="SF", cost_code="03310",
                item_number="12", schedule="A", structure_id="HW-3",
                elements=[{"name": "Deck-1", "global_id": "G1",
                           "section_type": "decks", "count": 1,
                           "length_ft": 10.0, "width_ft": 4.0,
                           "height_ft": 0.67, "measure": "GrossArea",
                           "value_si": 44.59}])
    base.update(over)
    return TakeoffRow(**base)


def _takeoff(rows):
    return CanonicalTakeoff(organization_id=1, project_ref="B1", rows=rows)


def test_takeoff_only_audit_is_single_leg_ok():
    rep = build_audit(_takeoff([_row()]))
    assert rep.legs == {"ifc": False, "bm": False, "mesh": False}
    (item,) = rep.items
    assert item.takeoff_qty == 480.0
    assert item.ifc_qty is None and item.bm_qty is None
    assert item.status == "OK"
    assert item.element_count == 1
    # no comparison leg requested -> no verdict to give
    assert item.verdict == "" and item.verdict_tier == ""


def test_bm_leg_within_tolerance_is_ok():
    bm = _snapshot()   # estimate_qty 480.0, item A/12
    rep = build_audit(_takeoff([_row()]), bm=load_bm_snapshot(bm))
    (item,) = rep.items
    assert item.bm_qty == 480.0
    assert item.delta_bm_pct == 0.0
    assert item.status == "OK"


def test_bm_variance_over_tolerance_flags():
    bm = _snapshot()
    bm["items"][0]["estimate_qty"] = 500.0            # +4.17%
    rep = build_audit(_takeoff([_row()]), bm=load_bm_snapshot(bm), tol_pct=1.0)
    (item,) = rep.items
    assert item.status == "VARIANCE"
    assert any(f.kind == "variance" for f in rep.exceptions)


def test_missing_in_bm_and_missing_in_takeoff():
    bm = _snapshot()
    bm["items"].append({"schedule": "A", "item_number": "13",
                        "description": "Riprap", "unit": "TON",
                        "estimate_qty": 90.0, "structures": []})
    rep = build_audit(_takeoff([_row(),
                                _row(item_number="14", description="Fence",
                                     quantity=100.0, unit="LF", elements=[])]),
                      bm=load_bm_snapshot(bm))
    by_key = {i.item_key: i for i in rep.items}
    assert by_key["A/13"].status == "MISSING IN TAKEOFF"
    assert by_key["A/14"].status == "MISSING IN BM"
    kinds = {f.kind for f in rep.exceptions}
    assert {"missing-in-bm", "missing-in-takeoff"} <= kinds


def test_zero_takeoff_qty_has_no_pct_and_flags():
    rep = build_audit(_takeoff([_row(quantity=0.0)]),
                      bm=load_bm_snapshot(_snapshot()))
    (item,) = rep.items
    assert item.delta_bm_pct is None
    assert any(f.kind == "zero-takeoff" for f in rep.exceptions)
    assert item.status == "VARIANCE"


def test_structure_mismatch_between_bm_and_takeoff():
    bm = _snapshot()
    bm["items"][0]["structures"] = [{"structure_id": "HW-9", "sections": []}]
    rep = build_audit(_takeoff([_row()]), bm=load_bm_snapshot(bm))
    assert any(f.kind == "structure-mismatch" for f in rep.exceptions)


def test_material_and_structure_rows_are_ignored():
    rows = [_row(), TakeoffRow(description="epoxy", kind="material",
                               quantity=2.0, unit="EA")]
    rep = build_audit(_takeoff(rows))
    assert len(rep.items) == 1


def _ifc_leg():
    # what bim.ifc_takeoff.ifc_leg returns: SI qtys keyed by GlobalId
    return {"G1": {"name": "Deck-1", "ifc_class": "IfcSlab",
                   "qtys": {"GrossArea": 44.59, "Length": 3.05}}}


def test_ifc_leg_ok_and_elements_tab_rows():
    rep = build_audit(_takeoff([_row()]), ifc=_ifc_leg())
    (item,) = rep.items
    assert item.ifc_qty == 480.0          # proportional: identical SI sums
    assert item.delta_ifc_pct == 0.0
    assert item.status == "OK"
    (el,) = rep.elements
    assert (el.global_id, el.join, el.delta_flag) == ("G1", "id", "OK")
    assert el.takeoff_si == 44.59 and el.ifc_si == 44.59


def test_stale_ifc_variance_flags_item_and_element():
    leg = _ifc_leg()
    leg["G1"]["qtys"]["GrossArea"] = 50.0      # model changed after takeoff
    rep = build_audit(_takeoff([_row()]), ifc=leg, tol_pct=1.0)
    (item,) = rep.items
    assert item.status == "VARIANCE"
    assert rep.elements[0].delta_flag == "VARIANCE"


def test_takeoff_element_gone_from_ifc():
    rep = build_audit(_takeoff([_row()]), ifc={})
    (item,) = rep.items
    assert item.status == "MISSING IN IFC"
    assert rep.elements[0].delta_flag == "MISSING IN IFC"


def test_orphan_ifc_element_of_measured_class_flags():
    leg = _ifc_leg()
    leg["G9"] = {"name": "Deck-9", "ifc_class": "IfcSlab",
                 "qtys": {"GrossArea": 5.0}}
    leg["G8"] = {"name": "Rail-1", "ifc_class": "IfcRailing",
                 "qtys": {"Length": 4.0}}       # class never measured: ignored
    rep = build_audit(_takeoff([_row()]), ifc=leg)
    orphans = [f for f in rep.exceptions if f.kind == "orphan-element"]
    assert len(orphans) == 1 and "Deck-9" in orphans[0].detail


def test_legacy_row_without_ids_name_joins_and_flags():
    legacy = _row(elements=[{"name": "Deck-1", "section_type": "decks",
                             "count": 1, "length_ft": 10.0, "width_ft": 4.0,
                             "height_ft": 0.67}])
    rep = build_audit(_takeoff([legacy]), ifc=_ifc_leg())
    (el,) = rep.elements
    assert (el.join, el.delta_flag) == ("name", "LEGACY")
    kinds = {f.kind for f in rep.exceptions}
    assert "name-join" in kinds and "legacy-row" in kinds


def test_duplicate_name_join_is_exception_not_guess():
    leg = _ifc_leg()
    leg["G2"] = {"name": "Deck-1", "ifc_class": "IfcSlab",
                 "qtys": {"GrossArea": 9.0}}
    legacy = _row(elements=[{"name": "Deck-1", "section_type": "decks",
                             "count": 1, "length_ft": None, "width_ft": None,
                             "height_ft": None}])
    rep = build_audit(_takeoff([legacy]), ifc=leg)
    (el,) = rep.elements
    assert el.join == "none"
    assert any(f.kind == "duplicate-name" for f in rep.exceptions)


def test_row_without_elements_flags_no_elements():
    rep = build_audit(_takeoff([_row(elements=[])]), ifc=_ifc_leg())
    assert any(f.kind == "no-elements" for f in rep.exceptions)
    assert rep.items[0].ifc_qty is None


def test_unit_conflict_with_ifc_does_not_fabricate_ifc_qty():
    # BUG 1: mixed units -> takeoff_qty None; the IFC rollup must not
    # fabricate ifc_qty=0.0 from `takeoff_qty or 0`.
    leg = _ifc_leg()
    leg["G2"] = {"name": "Deck-2", "ifc_class": "IfcSlab",
                 "qtys": {"GrossArea": 44.59}}
    rows = [_row(),
            _row(unit="SY", quantity=53.0,
                 elements=[{"name": "Deck-2", "global_id": "G2",
                            "section_type": "decks", "count": 1,
                            "length_ft": 10.0, "width_ft": 4.0,
                            "height_ft": 0.67, "measure": "GrossArea",
                            "value_si": 44.59}])]
    rep = build_audit(_takeoff(rows), ifc=leg)
    (item,) = rep.items
    assert item.ifc_qty is None
    assert any(f.kind == "unit-conflict" for f in rep.exceptions)
    assert not any(f.kind == "variance" for f in rep.exceptions)


def test_name_join_fan_in_does_not_double_count():
    # BUG 2: two gid-less elements sharing a name must not both claim the
    # single matching IFC element (double-counted i_si).
    el = {"name": "Deck-1", "section_type": "decks", "count": 1,
          "length_ft": 10.0, "width_ft": 4.0, "height_ft": 0.67,
          "measure": "GrossArea", "value_si": 44.59}
    rep = build_audit(_takeoff([_row(elements=[dict(el)]),
                                _row(elements=[dict(el)])]),
                      ifc=_ifc_leg())
    joins = sorted(e.join for e in rep.elements)
    assert joins == ["name", "none"]
    assert any(f.kind == "duplicate-name" for f in rep.exceptions)
    assert not any(f.kind == "variance" for f in rep.exceptions)


def test_zero_base_element_vs_nonzero_ifc_is_variance():
    # BUG 3: t_si == 0 vs i_si != 0 must flag, not silently pass as OK.
    leg = _ifc_leg()
    leg["G1"]["qtys"]["GrossArea"] = 5.0
    row = _row(elements=[{"name": "Deck-1", "global_id": "G1",
                          "section_type": "decks", "count": 1,
                          "length_ft": 10.0, "width_ft": 4.0,
                          "height_ft": 0.67, "measure": "GrossArea",
                          "value_si": 0.0}])
    rep = build_audit(_takeoff([row]), ifc=leg)
    (el,) = rep.elements
    assert el.delta_flag == "VARIANCE"
    (item,) = rep.items
    assert item.status == "VARIANCE"
    assert any(f.kind == "variance" for f in rep.exceptions)


def test_gid_joined_element_missing_measure_has_finding():
    # BUG 4: gid joins but the IFC element lacks the measure -> the
    # MISSING IN IFC status must come with a finding for --strict.
    leg = {"G1": {"name": "Deck-1", "ifc_class": "IfcSlab",
                  "qtys": {"Length": 3.05}}}       # no GrossArea
    rep = build_audit(_takeoff([_row()]), ifc=leg)
    (item,) = rep.items
    assert item.status == "MISSING IN IFC"
    assert any(f.kind == "missing-in-ifc" for f in rep.exceptions)


def test_snapshot_duplicate_item_key_raises():
    bad = _snapshot()
    bad["items"].append(dict(bad["items"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        load_bm_snapshot(bad)


def test_gid_join_claims_so_a_later_name_join_cannot_double_count():
    # hardening: a gid-joined element must ALSO claim its gid, so a
    # gid-less element sharing that IFC element's name cannot name-join
    # the same (already-claimed) IFC element and double-count its SI.
    leg = _ifc_leg()   # {"G1": {"name": "Deck-1", ...}}
    el1 = {"name": "Deck-1", "global_id": "G1", "section_type": "decks",
           "count": 1, "length_ft": 10.0, "width_ft": 4.0, "height_ft": 0.67,
           "measure": "GrossArea", "value_si": 44.59}
    el2 = {"name": "Deck-1", "section_type": "decks", "count": 1,
           "length_ft": 10.0, "width_ft": 4.0, "height_ft": 0.67,
           "measure": "GrossArea", "value_si": 44.59}
    rep = build_audit(_takeoff([_row(elements=[el1, el2])]), ifc=leg)
    by_gid = {e.global_id: e for e in rep.elements if e.global_id}
    none_joins = [e for e in rep.elements if e.join == "none"]
    assert by_gid["G1"].join == "id"
    assert len(none_joins) == 1
    assert any(f.kind == "duplicate-name" for f in rep.exceptions)
    (item,) = rep.items
    # not double-counted into a bogus OK rollup
    assert item.status == "MISSING IN IFC"
    assert item.ifc_qty is None


# --------------------------------------------------------------- mesh leg
def _mesh_entry(vol, name="Deck-1", ifc_class="IfcSlab", area=4.0,
                len_m=3.0, wid_m=1.2, hgt_m=0.2, z_min=0.0, z_max=0.2):
    return {"name": name, "ifc_class": ifc_class,
            "mesh": {"volume_m3": vol, "plan_area_m2": area,
                     "len_m": len_m, "wid_m": wid_m, "hgt_m": hgt_m,
                     "z_min_m": z_min, "z_max_m": z_max}}


def _vol_row(**over):
    """A CF item measured by GrossVolume: 64 cf, value_si 64 cf in m3."""
    si = 64.0 * (1200.0 / 3937.0) ** 3
    base = dict(description="Footing Concrete", kind="quantity",
                quantity=64.0, unit="CF", cost_code="03310",
                item_number="40", schedule="A", structure_id="HW-3",
                elements=[{"name": "FTG-1", "global_id": "G1",
                           "section_type": "footings", "count": 1,
                           "measure": "GrossVolume", "value_si": si}])
    base.update(over)
    return TakeoffRow(**base)


VOL_SI = 64.0 * (1200.0 / 3937.0) ** 3
VOL_IFC = {"G1": {"name": "FTG-1", "ifc_class": "IfcFooting",
                  "qtys": {"GrossVolume": VOL_SI}}}


def test_mesh_without_ifc_is_a_value_error():
    with pytest.raises(ValueError, match="mesh leg requires"):
        build_audit(_takeoff([_vol_row()]), mesh={"G1": _mesh_entry(1.0)})


def test_mesh_leg_ok_within_tolerance_and_rolls_up():
    mesh = {"G1": _mesh_entry(VOL_SI * 1.001, name="FTG-1",
                              ifc_class="IfcFooting")}      # +0.1% < 0.5%
    rep = build_audit(_takeoff([_vol_row()]), ifc=VOL_IFC, mesh=mesh)
    assert rep.legs == {"ifc": True, "bm": False, "mesh": True}
    (item,) = rep.items
    assert item.geom_status == "OK"
    assert item.measured_qty == pytest.approx(64.064, abs=1e-3)
    assert item.delta_geom_pct == pytest.approx(0.1, abs=0.01)
    (el,) = rep.elements
    assert el.geom_flag == "OK"
    assert el.mesh_si == pytest.approx(VOL_SI * 1.001)
    assert not any(f.kind == "geometry-variance" for f in rep.exceptions)
    (g,) = rep.geometry
    assert g.item_key == "A/40" and g.global_id == "G1"
    assert g.flag == "OK" and g.authored_si == pytest.approx(VOL_SI)


def test_mesh_variance_flags_element_item_and_finding():
    mesh = {"G1": _mesh_entry(VOL_SI * 1.05, name="FTG-1",
                              ifc_class="IfcFooting")}      # +5% > 0.5%
    rep = build_audit(_takeoff([_vol_row()]), ifc=VOL_IFC, mesh=mesh)
    (item,) = rep.items
    assert item.geom_status == "GEOM VARIANCE"
    (el,) = rep.elements
    assert el.geom_flag == "GEOM VARIANCE"
    assert any(f.kind == "geometry-variance" and "FTG-1" in f.detail
               for f in rep.exceptions)
    # the three-way status chain is UNTOUCHED by geometry findings
    assert item.status == "OK"


def test_geom_tol_pct_is_threaded():
    mesh = {"G1": _mesh_entry(VOL_SI * 1.05, name="FTG-1",
                              ifc_class="IfcFooting")}
    rep = build_audit(_takeoff([_vol_row()]), ifc=VOL_IFC, mesh=mesh,
                      geom_tol_pct=10.0)
    assert rep.items[0].geom_status == "OK"
    assert rep.provenance["geom_tol_pct"] == 10.0


def test_unmeshed_element_is_no_geometry_not_a_finding():
    rep = build_audit(_takeoff([_vol_row()]), ifc=VOL_IFC, mesh={})
    (item,) = rep.items
    assert item.geom_status == "NO GEOMETRY"
    assert item.measured_qty is None
    assert rep.elements[0].geom_flag == "NO GEOMETRY"
    assert not any(f.kind in ("geometry-variance", "unclassified-geometry")
                   for f in rep.exceptions)


def test_no_authored_volume_is_informational():
    ifc = {"G1": {"name": "FTG-1", "ifc_class": "IfcFooting",
                  "qtys": {"Count": 1.0, "GrossVolume": VOL_SI}}}
    del ifc["G1"]["qtys"]["GrossVolume"]
    mesh = {"G1": _mesh_entry(0.5, name="FTG-1", ifc_class="IfcFooting")}
    rep = build_audit(_takeoff([_vol_row()]), ifc=ifc, mesh=mesh)
    assert rep.elements[0].geom_flag == "NO AUTHORED VOLUME"
    assert not any(f.kind == "geometry-variance" for f in rep.exceptions)
    assert rep.items[0].measured_qty is None


def test_incomplete_ifc_leg_blocks_rollup_even_when_mesh_looks_ok():
    # Pins the `complete and mesh_complete` guard against a future
    # "simplification" to mesh_complete alone: the IFC leg is incomplete
    # (the element's measure 'GrossVolume' is missing from the IFC entry,
    # which carries only NetVolume), so the item roll-up must NOT happen —
    # even though the mesh leg alone looks fine (mesh volume matches the
    # authored NetVolume fallback, element geom_flag OK).
    ifc = {"G1": {"name": "FTG-1", "ifc_class": "IfcFooting",
                  "qtys": {"NetVolume": VOL_SI}}}
    mesh = {"G1": _mesh_entry(VOL_SI, name="FTG-1", ifc_class="IfcFooting")}
    rep = build_audit(_takeoff([_vol_row()]), ifc=ifc, mesh=mesh)
    (item,) = rep.items
    assert item.measured_qty is None
    assert item.geom_status == "NO GEOMETRY"
    assert rep.elements[0].geom_flag == "OK"


def test_zero_authored_volume_with_real_mesh_is_variance():
    # Authored GrossVolume of exactly 0: pct is undefined, but real mesh
    # volume is a real discrepancy — GEOM VARIANCE with a finding. The
    # ~zero-mesh sibling against the same zero base is OK, no finding.
    ifc = {"G1": {"name": "FTG-1", "ifc_class": "IfcFooting",
                  "qtys": {"GrossVolume": 0.0}}}
    mesh = {"G1": _mesh_entry(0.7, name="FTG-1", ifc_class="IfcFooting")}
    rep = build_audit(_takeoff([_vol_row()]), ifc=ifc, mesh=mesh)
    assert rep.elements[0].geom_flag == "GEOM VARIANCE"
    assert any(f.kind == "geometry-variance" for f in rep.exceptions)

    mesh0 = {"G1": _mesh_entry(0.0, name="FTG-1", ifc_class="IfcFooting")}
    rep0 = build_audit(_takeoff([_vol_row()]), ifc=ifc, mesh=mesh0)
    assert rep0.elements[0].geom_flag == "OK"
    assert not any(f.kind == "geometry-variance" for f in rep0.exceptions)


def test_non_volume_measure_item_is_na_but_elements_still_compared():
    # default _row measures GrossArea (SF item): item-level roll-up is n/a,
    # yet the element-level mesh-vs-authored-volume comparison still runs.
    ifc = {"G1": {"name": "Deck-1", "ifc_class": "IfcSlab",
                  "qtys": {"GrossArea": 44.59, "GrossVolume": 1.0}}}
    mesh = {"G1": _mesh_entry(1.2)}                          # +20% off authored
    rep = build_audit(_takeoff([_row()]), ifc=ifc, mesh=mesh)
    (item,) = rep.items
    assert item.geom_status == "n/a"
    assert item.measured_qty is None
    assert rep.elements[0].geom_flag == "GEOM VARIANCE"
    assert any(f.kind == "geometry-variance" for f in rep.exceptions)


def test_unclassified_geometry_finding_and_reference_row():
    mesh = {"G1": _mesh_entry(VOL_SI, name="FTG-1", ifc_class="IfcFooting"),
            "GX": _mesh_entry(0.7, name="mystery slab",
                              ifc_class="IfcBuildingElementProxy"),
            "GZ": _mesh_entry(0.0, name="zero shell",
                              ifc_class="IfcBuildingElementProxy")}
    rep = build_audit(_takeoff([_vol_row()]), ifc=VOL_IFC, mesh=mesh)
    uncl = [f for f in rep.exceptions if f.kind == "unclassified-geometry"]
    assert len(uncl) == 1 and "mystery slab" in uncl[0].detail
    by_gid = {g.global_id: g for g in rep.geometry}
    assert by_gid["GX"].flag == "UNCLASSIFIED" and by_gid["GX"].item_key == ""
    assert by_gid["GZ"].flag == "REFERENCE"      # ~0 m3: reported, not flagged
    assert rep.provenance["mesh_counts"] == {
        "meshed": 3, "qto_only": 0, "unclassified": 1}


def test_mesh_leg_off_leaves_defaults():
    rep = build_audit(_takeoff([_vol_row()]), ifc=VOL_IFC)
    assert rep.legs["mesh"] is False
    assert rep.items[0].geom_status == "n/a"
    assert rep.elements[0].geom_flag == "n/a"
    assert rep.elements[0].mesh_si is None
    assert rep.geometry == []


# --- graduated verdict bands (R1 item 9, Work Tools/ifc_qto.py ladder) -------
def test_verdict_bands():
    from estimating_tools.takeoff.audit import verdict
    assert verdict(None, "CY") == ("no paid item matched - review mapping",
                                   "yellow")
    assert verdict(0.005, "EA") == ("EXACT match", "green")
    assert verdict(0.005, "CY") == ("agrees (<=2%)", "green")
    assert verdict(2.0, "CY") == ("agrees (<=2%)", "green")
    assert verdict(2.01, "CY") == ("close (<=10%) - check assumptions",
                                   "green")
    assert verdict(-2.1, "CY") == ("close (<=10%) - check assumptions",
                                   "green")
    assert verdict(10.0, "CY") == ("close (<=10%) - check assumptions",
                                   "green")
    assert verdict(10.01, "CY") == ("material variance - see model assumptions",
                                    "yellow")
    assert verdict(-40.0, "CY") == ("material variance - see model assumptions",
                                    "yellow")
    assert verdict(40.1, "CY") == ("large variance - do NOT use for bidding",
                                   "red")


def test_item_verdict_uses_worst_delta_and_lands_on_items():
    rows = [_row()]
    bm = _snapshot()
    bm["items"][0]["estimate_qty"] = 720.0   # takeoff 480 -> +50% BM delta
    rep = build_audit(_takeoff(rows), bm=load_bm_snapshot(bm))
    it = rep.items[0]
    assert it.delta_bm_pct == pytest.approx(50.0)
    assert it.verdict == "large variance - do NOT use for bidding"
    assert it.verdict_tier == "red"
    assert it.status == "VARIANCE"           # status chain untouched


def test_item_verdict_worst_of_two_nonnull_deltas():
    from estimating_tools.takeoff.audit import _item_verdict
    # either leg can be the worst one; magnitude (abs) decides
    assert _item_verdict(50.0, 1.0, "CY") == \
        ("large variance - do NOT use for bidding", "red")
    assert _item_verdict(-1.0, -45.0, "CY") == \
        ("large variance - do NOT use for bidding", "red")


def test_worst_of_both_legs_lands_on_items():
    # IFC leg agrees (<2%) but BM leg is >40% off -> worst (BM) wins
    leg = _ifc_leg()
    leg["G1"]["qtys"]["GrossArea"] = 45.0    # ~+0.92% IFC delta
    bm = _snapshot()
    bm["items"][0]["estimate_qty"] = 720.0   # +50% BM delta
    rep = build_audit(_takeoff([_row()]), ifc=leg, bm=load_bm_snapshot(bm))
    it = rep.items[0]
    assert it.delta_ifc_pct is not None and abs(it.delta_ifc_pct) < 2.0
    assert it.delta_bm_pct == pytest.approx(50.0)
    assert it.verdict == "large variance - do NOT use for bidding"
    assert it.verdict_tier == "red"


def test_missing_in_takeoff_gets_review_mapping_verdict():
    bm = _snapshot()
    bm["items"][0]["item_number"] = "99"     # no takeoff row matches
    rep = build_audit(_takeoff([_row()]), bm=load_bm_snapshot(bm))
    missing = [i for i in rep.items if i.status == "MISSING IN TAKEOFF"]
    # direction-correct wording: the paid item exists, the takeoff row doesn't
    assert missing and missing[0].verdict == \
        "no takeoff row - review mapping"
    assert missing[0].verdict_tier == "yellow"
