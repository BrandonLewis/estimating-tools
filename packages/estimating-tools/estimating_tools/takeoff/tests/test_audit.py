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


def test_a_grouping_whole_is_not_an_orphan_but_a_bare_leaf_is():
    """bimforge 0.1.102 groups a handrail or barrier run under one IfcRailing
    / IfcWall WHOLE with no body and no quantities (its parts carry them);
    `mark_wholes` flags it, and the audit ignores it. A physical element of
    a measured class with no quantities is still an orphan: it is work the
    takeoff does not count."""
    leg = _ifc_leg()
    leg["G7"] = {"name": "NB handrail run", "ifc_class": "IfcSlab",
                 "qtys": {}, "whole": True}         # the grouping whole
    leg["G9"] = {"name": "Deck-9", "ifc_class": "IfcSlab",
                 "qtys": {"GrossArea": 5.0}}
    leg["G6"] = {"name": "Deck-6", "ifc_class": "IfcSlab",
                 "qtys": {}}                        # a leaf nobody measured
    rep = build_audit(_takeoff([_row()]), ifc=leg)
    orphans = sorted(f.detail for f in rep.exceptions
                     if f.kind == "orphan-element")
    assert len(orphans) == 2
    assert any("Deck-9" in d for d in orphans)
    assert any("Deck-6" in d for d in orphans)
    assert not any("handrail run" in d for d in orphans)


def test_mark_wholes_flags_only_bodiless_quantity_less_aggregators(tmp_path):
    """On a real IFC from the bimforge kernel: the run whole (no body, no
    Qto, parts under it) is flagged; its parts and a standalone element are
    not; a bodiless element with no parts is not."""
    import uuid

    pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.primitives import Prism
    from bimforge.author.project import ProjectContext
    from bimforge.bim.ifc_takeoff import ifc_leg

    from estimating_tools.takeoff.audit import mark_wholes
    ctx = ProjectContext(name="Wholes", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, guid_ns=uuid.UUID(int=9797))
    m = StructureModel("wholes", ctx)
    m.add(Element("NB handrail run", "IfcRailing", predefined_type="HANDRAIL"))
    for i in range(2):
        p = Prism(f"NB post {i + 1}", [(-0.1 + 6 * i, -0.1), (0.1 + 6 * i, -0.1),
                                       (0.1 + 6 * i, 0.1), (-0.1 + 6 * i, 0.1)],
                  z_bot=0.0, z_top=1.3, ifc="IfcMember")
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcMember",
                                    part_of="NB handrail run"))
    d = Prism("Deck", [(0, 0), (10, 0), (10, 4), (0, 4)], z_bot=2.0, z_top=3.0,
              ifc="IfcSlab")
    m.add(Element.from_geometry(d.name, d, ifc_class="IfcSlab"))
    m.add(Element("Loose rebar", "IfcReinforcingBar",
                  quantities={"weight_lb": 10.0}))      # bodiless, no parts
    out = tmp_path / "w.ifc"
    emit_ifc(m, str(out))
    leg = mark_wholes(out, ifc_leg(str(out)))
    by_name = {v["name"]: v for v in leg.values()}
    assert by_name["NB handrail run"].get("whole") is True
    assert by_name["NB handrail run"]["qtys"] == {}
    for name in ("NB post 1", "NB post 2", "Deck", "Loose rebar"):
        assert "whole" not in by_name[name], name
