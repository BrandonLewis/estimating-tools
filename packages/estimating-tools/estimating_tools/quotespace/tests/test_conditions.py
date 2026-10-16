"""QuoteConditionRecord + journal (estimating_tools.quotespace.conditions)."""
import pytest

from estimating_tools.quotespace.conditions import (
    QuoteConditionRecord, read_conditions)
from estimating_tools.quotespace.model import append_records, current_records


def _rec(**kw):
    base = dict(
        work_package={"name": "Rebar", "bm_work_package_id": 178},
        vendor={"org_name": "Nucor", "bm_vendor_id": 4711},
        separate_acceptance_permitted=False,
        acceptance_notes="not for separate acceptance",
        scope_tags=[{"group": "cages",
                     "items": [{"schedule": "A", "item_number": "35"}],
                     "treatment": "separate", "folded_into": None,
                     "notes": ""}],
    )
    base.update(kw)
    return QuoteConditionRecord(**base)


def test_record_id_and_key():
    r = _rec()
    assert r.record_id.startswith("qc-")
    assert r.key() == ("rebar", "nucor")


def test_flag_tristate_default_unknown():
    assert _rec(separate_acceptance_permitted=None).separate_acceptance_permitted is None
    r2 = QuoteConditionRecord(work_package={"name": "R"}, vendor={"org_name": "V"})
    assert r2.separate_acceptance_permitted is None


def test_false_flag_survives_payload():
    p = _rec().to_payload()
    assert p["separate_acceptance_permitted"] is False


def test_folded_requires_target_and_separate_forbids_it():
    with pytest.raises(ValueError, match="folded_into"):
        _rec(scope_tags=[{"group": "g", "items": [], "treatment": "folded",
                          "folded_into": None}])
    with pytest.raises(ValueError, match="folded_into"):
        _rec(scope_tags=[{"group": "g", "items": [], "treatment": "separate",
                          "folded_into": {"schedule": "A", "item_number": "41"}}])


def test_rejects_bad_treatment_and_missing_group():
    with pytest.raises(ValueError, match="treatment"):
        _rec(scope_tags=[{"group": "g", "items": [], "treatment": "maybe"}])
    with pytest.raises(ValueError, match="group"):
        _rec(scope_tags=[{"group": " ", "items": [], "treatment": "separate"}])


def test_rejects_non_dict_tag_and_bad_shapes():
    with pytest.raises(ValueError, match="JSON object"):
        _rec(scope_tags=["oops"])
    with pytest.raises(ValueError, match="item_number"):
        _rec(scope_tags=[{"group": "g", "items": [{"schedule": "A"}],
                          "treatment": "separate"}])
    with pytest.raises(ValueError, match="folded_into"):
        _rec(scope_tags=[{"group": "g", "items": [], "treatment": "folded",
                          "folded_into": "41"}])


def test_journal_line_with_non_dict_tag_names_the_line(tmp_path):
    j = tmp_path / "j.jsonl"
    j.write_text('{"work_package": {"name": "P"}, "vendor": {"org_name": "V"},'
                 ' "scope_tags": ["oops"]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        read_conditions(j)


def test_journal_round_trip_latest_wins(tmp_path):
    j = tmp_path / "Subquotes" / "quote-conditions.jsonl"
    append_records(j, [_rec()])
    append_records(j, [_rec(separate_acceptance_permitted=True)])
    recs = read_conditions(j)
    assert len(recs) == 2
    assert current_records(recs)[("rebar", "nucor")].separate_acceptance_permitted is True


def test_read_conditions_missing_file_and_bad_line(tmp_path):
    assert read_conditions(tmp_path / "nope.jsonl") == []
    j = tmp_path / "j.jsonl"
    j.write_text('{"bogus_key": 1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        read_conditions(j)


def test_solicitation_journal_still_reads(tmp_path):
    # the generalization must not break the existing default
    from estimating_tools.quotespace.model import SolicitationRecord, read_journal
    j = tmp_path / "s.jsonl"
    append_records(j, [SolicitationRecord(
        work_package={"name": "P"}, vendor={"org_name": "V"})])
    assert read_journal(j)[0].vendor["org_name"] == "V"


def test_from_bm_quote_builds_condition_record():
    from estimating_tools.quotespace.conditions import QuoteConditionRecord
    quote = {
        "vendor_id": 4711, "vendor_name": "Nucor",
        "separate_acceptance_permitted": False,
        "acceptance_notes": "not for separate acceptance",
        "scope_tags": [{"group": "cages",
                        "treatment": "folded",
                        "folded_into": {"schedule": "A", "item_number": "41"},
                        "notes": ""}],
    }
    rec = QuoteConditionRecord.from_bm_quote(quote, work_package_name="Rebar")
    assert rec.work_package == {"name": "Rebar", "bm_work_package_id": None}
    assert rec.vendor == {"org_name": "Nucor", "bm_vendor_id": 4711}
    assert rec.separate_acceptance_permitted is False
    assert rec.acceptance_notes == "not for separate acceptance"
    assert rec.scope_tags[0]["group"] == "cages"
    assert rec.key() == ("rebar", "nucor")


def test_from_bm_quote_tolerates_missing_conditions():
    from estimating_tools.quotespace.conditions import QuoteConditionRecord
    rec = QuoteConditionRecord.from_bm_quote(
        {"vendor_name": "V"}, work_package_name="P")
    assert rec.separate_acceptance_permitted is None
    assert rec.acceptance_notes == "" and rec.scope_tags == []
