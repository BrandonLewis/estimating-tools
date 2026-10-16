"""Tests for the cost-code / activity-code id resolver (#203)."""
from __future__ import annotations

import pytest

from estimating_tools.costcodes.resolver import (
    ActivityCodeRef, CostCodeResolver,
)

# shape of a `list_activity_codes` result row (id / code / description …)
ROWS = [
    {"id": 1, "code": "08-000", "description": "Mobilization / Demobilization"},
    {"id": 70, "code": "03-600", "description": "Box Culvert / Channel"},
    {"id": 92, "code": "03-900", "description": "Rebar"},
]


def _resolver():
    return CostCodeResolver.from_rows(ROWS, system_id=1)


def test_bidirectional_lookup():
    r = _resolver()
    assert r.id_of("03-600") == 70
    assert r.code_of(70) == "03-600"
    assert r.label_of("03-600") == "Box Culvert / Channel"
    assert r.label_of(70) == "Box Culvert / Channel"       # id or code
    assert r.system_id == 1


def test_ref_accepts_code_or_id():
    r = _resolver()
    assert r.ref("03-900") == ActivityCodeRef(id=92, code="03-900",
                                              label="Rebar")
    assert r.ref(92) == r.ref("03-900")


def test_get_is_non_raising():
    r = _resolver()
    assert r.get("nope") is None
    assert r.get(9999, default="x") == "x"
    assert r.get("03-600").id == 70


def test_miss_is_loud_and_lists_candidates():
    r = _resolver()
    with pytest.raises(KeyError) as exc:
        r.id_of("99-999")
    msg = str(exc.value)
    assert "99-999" in msg
    assert "03-600" in msg          # names some available codes
    with pytest.raises(KeyError):
        r.code_of(4242)


def test_membership_and_listing():
    r = _resolver()
    assert "03-600" in r and 70 in r
    assert "zz" not in r and 5 not in r
    assert len(r) == 3
    assert r.codes() == ["03-600", "03-900", "08-000"]   # sorted
    assert r.ids() == [1, 70, 92]


def test_duplicate_code_or_id_is_rejected():
    with pytest.raises(ValueError, match="duplicate code"):
        CostCodeResolver.from_rows(ROWS + [{"id": 71, "code": "03-600",
                                            "description": "clash"}])
    with pytest.raises(ValueError, match="duplicate id"):
        CostCodeResolver.from_rows(ROWS + [{"id": 70, "code": "03-601",
                                            "description": "clash"}])


def test_from_rows_tolerates_label_keys():
    # falls back to name/label when there's no description
    r = CostCodeResolver.from_rows([{"id": 5, "code": "01-100", "name": "Foo"}])
    assert r.label_of("01-100") == "Foo"
    r2 = CostCodeResolver.from_rows([{"id": 6, "code": "01-200"}])  # no label
    assert r2.label_of("01-200") == ""


def test_from_rows_rejects_missing_required_keys():
    with pytest.raises(ValueError, match="code"):
        CostCodeResolver.from_rows([{"id": 1, "description": "no code"}])
    with pytest.raises(ValueError, match="id"):
        CostCodeResolver.from_rows([{"code": "01-100", "description": "no id"}])


def test_lazy_finder_resolves_and_caches():
    calls = []

    def finder(code):
        calls.append(code)
        return {"id": 500, "code": code, "description": "Late-bound"}

    r = CostCodeResolver(finder=finder, system_id=1)
    assert r.id_of("07-777") == 500
    assert r.label_of("07-777") == "Late-bound"   # served from cache
    assert calls == ["07-777"]                     # finder hit exactly once


def test_lazy_finder_miss_still_raises():
    r = CostCodeResolver(finder=lambda code: None)
    with pytest.raises(KeyError, match="07-777"):
        r.id_of("07-777")


def test_from_rows_ignores_error_rows():
    # a BM {"error": ...} row (or any non-dict) is skipped, not crashed on
    r = CostCodeResolver.from_rows(ROWS + [{"error": "not found"}])
    assert len(r) == 3


def test_lazy_finder_skips_error_sentinel():
    # a {"error": ...} row from the finder is a miss, not a crash
    r = CostCodeResolver(finder=lambda code: {"error": "not found"})
    assert r.get("07-777") is None
    with pytest.raises(KeyError):
        r.id_of("07-777")


def test_lazy_finder_rejects_half_populated_row():
    # a row with an id but no code is malformed — fail loud, don't invent one
    r = CostCodeResolver(finder=lambda code: {"id": 501, "description": "x"})
    with pytest.raises(ValueError, match="code"):
        r.id_of("07-777")


def test_lazy_finder_honors_configured_label_keys():
    # a custom label key must apply to finder-resolved rows too, not just
    # preloaded ones
    r = CostCodeResolver.from_rows(
        [], label_keys=("summary",),
        finder=lambda code: {"id": 7, "code": code, "summary": "Custom"})
    assert r.label_of("09-000") == "Custom"
