"""Manifest round-trips, registers documents idempotently, holds the bid frame."""
import json

import pytest

from estimating_tools.intake.manifest import (
    BidFrameItem, ManifestDocument, ProjectManifest,
)

TS = "2026-08-02T12:00:00+00:00"


def test_round_trip(tmp_path):
    m = ProjectManifest(name="Job X", organization_id=7, bm_project_id=42,
                        project_ref="job-x", bid_number="2206",
                        bid_date="2026-07-16", bid_dir="B1042-2026-07-16")
    m.register_document("Plans/set1.pdf", kind="plans", source="local",
                        sha256="a" * 64, registered_at=TS)
    path = tmp_path / "manifest.json"
    m.save(path)
    m2 = ProjectManifest.load(path)
    assert m2.name == "Job X"
    assert m2.organization_id == 7
    assert m2.bid_dir == "B1042-2026-07-16"
    assert m2.documents[0].kind == "plans"
    assert json.loads(path.read_text())["version"] == 1


def test_register_document_idempotent_by_path():
    m = ProjectManifest(name="Job X")
    m.register_document("Specs/s.pdf", kind="specs", source="local",
                        sha256="a" * 64, registered_at=TS)
    m.register_document("Plans/p.pdf", kind="plans", source="local",
                        sha256="c" * 64, registered_at=TS)
    m.register_document("Specs/s.pdf", kind="specs", source="local",
                        sha256="b" * 64, registered_at=TS)
    assert len(m.documents) == 2
    assert [d.path for d in m.documents] == ["Plans/p.pdf", "Specs/s.pdf"]
    assert m.documents[-1].sha256 == "b" * 64  # re-register replaces


def test_invalid_kind_and_source_raise():
    with pytest.raises(ValueError, match="invalid document kind"):
        ManifestDocument(path="x", kind="blueprints", source="local",
                         sha256="a" * 64, registered_at=TS)
    with pytest.raises(ValueError, match="invalid document source"):
        ManifestDocument(path="x", kind="plans", source="dropbox",
                         sha256="a" * 64, registered_at=TS)


def test_bid_frame_snapshot():
    m = ProjectManifest(name="Job X")
    m.set_bid_frame(
        [BidFrameItem(item_number="0010", schedule="A", item_code="03 30 00",
                      description="Structure concrete", unit="CY",
                      project_bid_item_id=901, estimated_quantity=120.0)],
        snapshot_at=TS,
    )
    assert m.bid_frame_snapshot_at == TS
    assert m.bid_frame[0].project_bid_item_id == 901


def test_load_rejects_non_object(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text("[]")
    with pytest.raises(ValueError, match="manifest JSON must be a JSON object"):
        ProjectManifest.load(p)


def test_load_rejects_non_list_sections(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text('{"name": "x", "documents": {"path": "a"}}')
    with pytest.raises(ValueError, match="'documents' must be a list"):
        ProjectManifest.load(p)
    p.write_text('{"name": "x", "bid_frame": {"item_number": "1"}}')
    with pytest.raises(ValueError, match="'bid_frame' must be a list"):
        ProjectManifest.load(p)
