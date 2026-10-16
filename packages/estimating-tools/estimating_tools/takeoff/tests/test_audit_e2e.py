"""End-to-end: sample DXF -> dxf2bim IFC -> takeoff -> three-way audit OK.

Lives in the estimating layer (moved from bimforge/bim/tests): it exercises
`estimating_tools.takeoff.audit` over bimforge's pipeline, and bimforge's own
suite must run standalone without this package installed.
"""
import json
from importlib.resources import files as _res_files

import pytest
import yaml

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features
from bimforge.bim.ifc_takeoff import build_takeoff, ifc_leg
from bimforge.bim.sample import write_sample_dxf
from estimating_tools.takeoff.audit import build_audit, load_bm_snapshot
from estimating_tools.takeoff.model import CanonicalTakeoff


@pytest.fixture()
def pipeline(tmp_path):
    # identical setup to test_ifc2dxf.py::pipeline_ifc (sample DXF -> ft-unit,
    # EPSG:2226-georeferenced IFC via dxf2bim), extended to also stage the
    # shipped takeoff_map.example.yaml next to it (the same resource
    # est-bim sample --with-configs copies out). Returns (ifc_path, tmap_path).
    dxf = write_sample_dxf(str(tmp_path / "sample.dxf"))
    cfg = yaml.safe_load(
        (_res_files("bimforge.bim") / "examples" /
         "layer_map.example.yaml").read_text(encoding="utf-8"))
    cfg["units"] = {"dxf_length_unit": "ft"}
    cfg["georeference"] = {"crs_epsg": 2226, "base_easting": None,
                           "base_northing": None, "base_height": 0.0}
    scale = UNIT_TO_M["ft"]
    feats = extract_features(dxf, cfg.get("layers", {}), scale)
    ifc_path = tmp_path / "sample.ifc"
    build_ifc(feats, cfg, str(ifc_path))

    tmap_text = (_res_files("bimforge.bim") / "examples" /
                 "takeoff_map.example.yaml").read_text(encoding="utf-8")
    tmap_path = tmp_path / "takeoff_map.example.yaml"
    tmap_path.write_text(tmap_text, encoding="utf-8")

    return ifc_path, tmap_path


def test_three_way_audit_of_own_pipeline_is_clean(pipeline, tmp_path):
    ifc_path, tmap_path = pipeline
    tmap = yaml.safe_load(tmap_path.read_text(encoding="utf-8"))
    takeoff_dict, _warnings = build_takeoff(str(ifc_path), tmap)
    takeoff = CanonicalTakeoff.from_json(json.dumps(takeoff_dict))
    assert takeoff.rows, "sample pipeline produced no takeoff rows"
    # every element the takeoff emitted carries the audit join keys
    for row in takeoff.rows:
        for e in row.elements:
            assert e["global_id"] and e["measure"] and e["value_si"] is not None

    # synthetic BM snapshot: the estimate agrees with the takeoff exactly
    snap = {"estimate_ref": "e2e", "items": [
        {"schedule": r.schedule, "item_number": r.item_number,
         "description": r.description, "unit": r.unit,
         "estimate_qty": r.quantity,
         "structures": ([{"structure_id": r.structure_id, "sections": []}]
                        if r.structure_id else [])}
        for r in takeoff.rows]}

    rep = build_audit(takeoff, ifc=ifc_leg(str(ifc_path)),
                      bm=load_bm_snapshot(snap))
    assert rep.legs == {"ifc": True, "bm": True, "mesh": False}
    assert [i.status for i in rep.items] == ["OK"] * len(rep.items)
    assert rep.exceptions == []
    assert all(e.join == "id" for e in rep.elements)
