"""SolicitationRecord + journal semantics (estimating_tools.quotespace.model)."""
import json

import pytest

from estimating_tools.quotespace.model import (
    SolicitationRecord, append_records, current_records, read_journal)


def _rec(**kw):
    base = dict(
        work_package={"name": "Structural Concrete", "bm_work_package_id": 12},
        vendor={"org_name": "ACME Rebar", "bm_vendor_id": 34},
        contacts=["joe@acmerebar.com"],
        items=[{"schedule": "A", "item_number": "23"}],
        status="planned",
    )
    base.update(kw)
    return SolicitationRecord(**base)


def test_record_gets_a_generated_id_and_defaults():
    r = _rec()
    assert r.record_id.startswith("sol-")
    assert r.channel == "email"
    assert r.status == "planned"


def test_key_is_casefolded_package_vendor_pair():
    assert _rec().key() == ("structural concrete", "acme rebar")


def test_rejects_missing_package_name():
    with pytest.raises(ValueError, match="work_package.name"):
        _rec(work_package={"name": " "})


def test_rejects_missing_vendor_name():
    with pytest.raises(ValueError, match="vendor.org_name"):
        _rec(vendor={"org_name": ""})


def test_rejects_bad_channel_and_status():
    with pytest.raises(ValueError, match="channel"):
        _rec(channel="fax")
    with pytest.raises(ValueError, match="status"):
        _rec(status="maybe")


def test_sent_requires_sent_at():
    with pytest.raises(ValueError, match="sent_at"):
        _rec(status="sent")
    r = _rec(status="sent", sent_at="2026-08-07")
    assert r.sent_at == "2026-08-07"


def test_to_payload_drops_empty_but_keeps_zero_and_ids():
    r = _rec(notes="", sent_at="")
    p = r.to_payload()
    assert "notes" not in p and "sent_at" not in p
    assert p["work_package"]["bm_work_package_id"] == 12
    assert p["record_id"].startswith("sol-")


def test_journal_round_trip_and_latest_wins(tmp_path):
    j = tmp_path / "Subquotes" / "solicitations.jsonl"
    first = _rec()
    append_records(j, [first])
    later = _rec(status="sent", sent_at="2026-08-07")
    append_records(j, [later])
    other = _rec(vendor={"org_name": "Basalt Steel"})
    append_records(j, [other])

    all_recs = read_journal(j)
    assert len(all_recs) == 3  # append-only: history preserved
    current = current_records(all_recs)
    assert len(current) == 2
    assert current[first.key()].status == "sent"          # latest wins
    assert current[other.key()].vendor["org_name"] == "Basalt Steel"


def test_read_journal_reports_bad_line_number(tmp_path):
    j = tmp_path / "solicitations.jsonl"
    j.write_text('{"ok": false\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        read_journal(j)


def test_read_journal_reports_schema_drift_with_line_number(tmp_path):
    j = tmp_path / "solicitations.jsonl"
    j.write_text(json.dumps({
        "work_package": {"name": "P"}, "vendor": {"org_name": "V"},
        "mystery_field": 1}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid record on line 1"):
        read_journal(j)


def test_read_journal_missing_file_is_empty(tmp_path):
    assert read_journal(tmp_path / "nope.jsonl") == []


def test_from_bm_builds_record_from_solicitation_row():
    from estimating_tools.quotespace.model import SolicitationRecord
    bm_row = {
        "work_package_id": 175, "vendor_id": 4711,
        "sent_at": "2026-08-07", "channel": "email", "status": "sent",
        "contacts": ["joe@acme.com"],
        "items": [{"schedule": "A", "item_number": "23"}],
        "notes": "", "revision": 2, "is_current": True,
    }
    rec = SolicitationRecord.from_bm(
        bm_row, work_package_name="Rebar", vendor_org_name="ACME Rebar")
    assert rec.work_package == {"name": "Rebar", "bm_work_package_id": 175}
    assert rec.vendor == {"org_name": "ACME Rebar", "bm_vendor_id": 4711}
    assert rec.status == "sent" and rec.sent_at == "2026-08-07"
    assert rec.channel == "email"
    assert rec.contacts == ["joe@acme.com"]
    assert rec.items == [{"schedule": "A", "item_number": "23"}]
    assert rec.key() == ("rebar", "acme rebar")


def test_from_bm_defaults_missing_optionals():
    from estimating_tools.quotespace.model import SolicitationRecord
    rec = SolicitationRecord.from_bm(
        {"work_package_id": 1, "vendor_id": 2, "status": "planned"},
        work_package_name="P", vendor_org_name="V")
    assert rec.contacts == [] and rec.items == [] and rec.channel == "email"
    assert rec.sent_at == "" and rec.notes == ""


def test_content_signature_is_order_insensitive():
    # Same content, but item dict keys and contacts in a different order:
    # the signature must be identical so a sync sees no change (no spam).
    a = _rec(contacts=["a@x.com", "b@x.com"],
             items=[{"schedule": "A", "item_number": "1"}])
    b = _rec(contacts=["b@x.com", "a@x.com"],
             items=[{"item_number": "1", "schedule": "A"}])
    assert a.content_signature() == b.content_signature()


def test_content_signature_reflects_a_real_change():
    a = _rec(status="planned")
    b = _rec(status="declined")
    assert a.content_signature() != b.content_signature()
