"""apply_conditions post-pass (estimating_tools.spreads.conditions).

Fixture is sample-bridge-shaped: item 41 (rebar, 54_500 LB) + item 35 (pile cages).
Nucor prices the cages as a separate line (lowest per-lb rate on 41 but
highest all-in); CVR folds cages into 41 (higher rate, lowest all-in).
Camblin folds too, higher. Per-item best picks Nucor on 41 — the EP-6
inversion — while the group subtotal must rank CVR first."""
import pytest

from estimating_tools.quotespace.conditions import QuoteConditionRecord
from estimating_tools.spreads.conditions import apply_conditions
from estimating_tools.spreads.level import build_spread

ITEMS = [
    {"id": 1, "project_bid_item_id": 41, "item_number": "41",
     "schedule_name": "A", "item_code": None},
    {"id": 2, "project_bid_item_id": 35, "item_number": "35",
     "schedule_name": "A", "item_code": None},
]
BID_ITEMS = [
    {"id": 41, "description": "Bar Reinforcing Steel", "unit": "LB",
     "quantity": "54500"},
    {"id": 35, "description": "Pile Cages", "unit": "LS", "quantity": "1"},
]
QUOTES = [
    {"id": 10, "vendor_id": 100, "vendor_name": "Nucor"},
    {"id": 11, "vendor_id": 200, "vendor_name": "CVR"},
    {"id": 12, "vendor_id": 300, "vendor_name": "Camblin"},
]
LINES = {
    # Nucor: 1.96/lb on 41 + cages separate 42_902 -> all-in 149_722
    10: [{"id": 1, "work_package_item_id": 1, "unit_price": "1.96",
          "quantity": "54500", "amount": None, "is_included": True},
         {"id": 2, "work_package_item_id": 2, "unit_price": "42902",
          "quantity": "1", "amount": None, "is_included": True}],
    # CVR: 2.4771/lb folded -> all-in 135_002 (lowest); no line on 35
    11: [{"id": 3, "work_package_item_id": 1, "unit_price": "2.4771",
          "quantity": "54500", "amount": None, "is_included": True}],
    # Camblin: 2.4991/lb folded -> 136_200; no line on 35
    12: [{"id": 4, "work_package_item_id": 1, "unit_price": "2.4991",
          "quantity": "54500", "amount": None, "is_included": True}],
}


def _cond(vendor, vendor_id, tags, flag=None, **kw):
    return QuoteConditionRecord(
        work_package={"name": "Rebar"},
        vendor={"org_name": vendor, "bm_vendor_id": vendor_id},
        separate_acceptance_permitted=flag, scope_tags=tags, **kw)


CAGES_SEP = [{"group": "cages",
              "items": [{"schedule": "A", "item_number": "35"}],
              "treatment": "separate", "folded_into": None}]
CAGES_FOLD = [{"group": "cages",
               "items": [{"schedule": "A", "item_number": "35"}],
               "treatment": "folded",
               "folded_into": {"schedule": "A", "item_number": "41"}}]


def _spread():
    return build_spread(ITEMS, BID_ITEMS, QUOTES, LINES)


def _conditions(nucor_flag=False, cvr_flag=False, camblin_flag=None):
    return [_cond("Nucor", 100, CAGES_SEP, flag=nucor_flag),
            _cond("CVR", 200, CAGES_FOLD, flag=cvr_flag),
            _cond("Camblin", 300, CAGES_FOLD, flag=camblin_flag)]


def test_empty_conditions_changes_nothing():
    import dataclasses
    plain, conditioned = _spread(), apply_conditions(_spread(), [])
    assert dataclasses.asdict(plain) == dataclasses.asdict(conditioned)


def test_group_basis_and_subtotals_catch_the_inversion():
    s = apply_conditions(_spread(), _conditions())
    [g] = s.scope_groups
    assert g.name == "cages"
    assert sorted(g.basis_row_ids) == [1, 2]
    assert g.subtotals[100] == pytest.approx(106820 + 42902)   # Nucor all-in
    assert g.subtotals[200] == pytest.approx(2.4771 * 54500)   # CVR all-in
    assert g.best_vendor_id == 200                             # NOT Nucor
    # per-item best is suppressed on basis rows
    for row in s.rows:
        assert row.best_vendor_id is None
        for c in row.cells.values():
            assert c.not_comparable


def test_folded_coverage_counts_toward_subtotal_and_full_coverage():
    s = apply_conditions(_spread(), _conditions())
    # CVR has no cell on row 2 but folds it into row 1 -> still a subtotal
    assert s.scope_groups[0].subtotals[200] is not None
    assert s.obtainable_single_vendor["vendor_id"] == 200
    assert s.obtainable_single_vendor["total"] == pytest.approx(2.4771 * 54500)


def test_best_of_breed_uses_group_winner_and_is_annotated():
    s = apply_conditions(_spread(), _conditions())
    # only rows are the basis rows -> best_of_breed == group winner subtotal
    assert s.best_of_breed_total == pytest.approx(2.4771 * 54500)
    # winner CVR has flag False -> annotated; every winner flagged -> suppressed
    assert {a["vendor_id"] for a in s.best_of_breed_annotations} == {200}
    assert s.best_of_breed_suppressed is True


def test_obtainable_best_mix_two_candidates():
    # CVR permits splits -> eligible for group win -> mix == its subtotal
    s = apply_conditions(_spread(), _conditions(cvr_flag=True))
    assert s.obtainable_best_mix == pytest.approx(2.4771 * 54500)
    assert s.best_of_breed_suppressed is False
    # nobody permits and nobody unknown-covers -> flag-False full-coverage
    # vendors still compete as whole-package candidates
    s2 = apply_conditions(_spread(), _conditions(camblin_flag=False))
    assert s2.obtainable_best_mix == pytest.approx(2.4771 * 54500)  # CVR whole


def test_unknown_acceptance_warning():
    s = apply_conditions(_spread(), _conditions(cvr_flag=None))
    kinds = {w["kind"] for w in s.condition_warnings}
    assert "unknown_acceptance" in kinds


def test_possible_scope_fold_flags_untagged_no_bid_mix():
    # drop all tags: CVR/Camblin no_bid row 2 with no tag explaining it
    conds = [_cond("Nucor", 100, [], flag=False)]
    s = apply_conditions(_spread(), conds)
    folds = [w for w in s.condition_warnings if w["kind"] == "possible_scope_fold"]
    assert folds and folds[0]["work_package_item_id"] == 2
    assert set(folds[0]["vendors"]) == {200, 300}


def test_tagged_no_bid_is_not_flagged():
    s = apply_conditions(_spread(), _conditions())
    assert not [w for w in s.condition_warnings
                if w["kind"] == "possible_scope_fold"]


def test_apply_conditions_exported_at_package_root():
    from estimating_tools import spreads
    assert spreads.apply_conditions is apply_conditions
    assert "apply_conditions" in spreads.__all__


def test_vendor_matched_by_name_when_no_bm_id():
    conds = [_cond("nucor", None, CAGES_SEP, flag=False)]
    conds[0].vendor.pop("bm_vendor_id", None)
    s = apply_conditions(_spread(), conds)
    assert s.scope_groups  # matched by casefold display name


# --- overlapping-basis fixture: cages AND mesh folded into item 41 ---------
# Two vendors: Nucor prices 41/35/36 separately (all-in 340); CVR folds both
# scopes into 41 (all-in 150). Row 41 sits in BOTH group bases — counting it
# once is the whole point.

ITEMS_M = [
    {"id": 1, "project_bid_item_id": 41, "item_number": "41",
     "schedule_name": "A", "item_code": None},
    {"id": 2, "project_bid_item_id": 35, "item_number": "35",
     "schedule_name": "A", "item_code": None},
    {"id": 3, "project_bid_item_id": 36, "item_number": "36",
     "schedule_name": "A", "item_code": None},
]
BID_ITEMS_M = [
    {"id": 41, "description": "Bar Reinforcing Steel", "unit": "LS",
     "quantity": "1"},
    {"id": 35, "description": "Pile Cages", "unit": "LS", "quantity": "1"},
    {"id": 36, "description": "Mesh", "unit": "LS", "quantity": "1"},
]
QUOTES_M = [
    {"id": 10, "vendor_id": 100, "vendor_name": "Nucor"},
    {"id": 11, "vendor_id": 200, "vendor_name": "CVR"},
]
LINES_M = {
    10: [{"id": 1, "work_package_item_id": 1, "unit_price": "100",
          "quantity": "1", "amount": None, "is_included": True},
         {"id": 2, "work_package_item_id": 2, "unit_price": "120",
          "quantity": "1", "amount": None, "is_included": True},
         {"id": 3, "work_package_item_id": 3, "unit_price": "120",
          "quantity": "1", "amount": None, "is_included": True}],
    11: [{"id": 4, "work_package_item_id": 1, "unit_price": "150",
          "quantity": "1", "amount": None, "is_included": True}],
}

MESH_SEP = [{"group": "mesh",
             "items": [{"schedule": "A", "item_number": "36"}],
             "treatment": "separate", "folded_into": None}]
MESH_FOLD = [{"group": "mesh",
              "items": [{"schedule": "A", "item_number": "36"}],
              "treatment": "folded",
              "folded_into": {"schedule": "A", "item_number": "41"}}]


def test_overlapping_group_bases_merge_and_count_shared_row_once():
    s = build_spread(ITEMS_M, BID_ITEMS_M, QUOTES_M, LINES_M)
    s = apply_conditions(s, [
        _cond("Nucor", 100, CAGES_SEP + MESH_SEP, flag=True),
        _cond("CVR", 200, CAGES_FOLD + MESH_FOLD, flag=True)])
    [g] = s.scope_groups
    assert g.name == "cages + mesh"
    assert sorted(g.basis_row_ids) == [1, 2, 3]
    assert any("merged for comparison" in w for w in g.warnings)
    assert g.subtotals[100] == pytest.approx(340)
    assert g.subtotals[200] == pytest.approx(150)
    assert g.best_vendor_id == 200
    # the shared row 41 is summed once: bob == the real all-in winner
    # subtotal, and the mix can never beat the obtainable single vendor
    assert s.best_of_breed_total == pytest.approx(150)
    assert s.obtainable_best_mix == pytest.approx(150)
    assert s.obtainable_best_mix <= s.obtainable_single_vendor["total"]


def test_transitive_overlaps_merge_into_one_group():
    items = ITEMS_M + [{"id": 4, "project_bid_item_id": 37,
                        "item_number": "37", "schedule_name": "A",
                        "item_code": None}]
    bid_items = BID_ITEMS_M + [{"id": 37, "description": "Dowels",
                                "unit": "LS", "quantity": "1"}]
    lines = {10: LINES_M[10] + [{"id": 9, "work_package_item_id": 4,
                                 "unit_price": "60", "quantity": "1",
                                 "amount": None, "is_included": True}]}
    s = build_spread(items, bid_items, [QUOTES_M[0]], lines)

    def _sep(group, *nums):
        return {"group": group, "treatment": "separate", "folded_into": None,
                "items": [{"schedule": "A", "item_number": n} for n in nums]}

    # cages∩ties on 41, mesh∩ties on 36, cages∩mesh = ∅ — "ties" sorts last,
    # so the merge must union two already-separate groups transitively
    s = apply_conditions(s, [_cond("Nucor", 100, [
        _sep("cages", "35", "41"), _sep("mesh", "36", "37"),
        _sep("ties", "41", "36")], flag=True)])
    [g] = s.scope_groups
    assert g.name == "cages + mesh + ties"
    assert sorted(g.basis_row_ids) == [1, 2, 3, 4]


def test_unresolved_item_key_warns_on_group():
    conds = [_cond("Nucor", 100, [
        {"group": "cages", "treatment": "separate", "folded_into": None,
         "items": [{"schedule": "A", "item_number": "35"},
                   {"schedule": "A", "item_number": "99"}]}], flag=True)]
    s = apply_conditions(_spread(), conds)
    [g] = s.scope_groups
    assert g.basis_row_ids == [2]          # the typo'd key shrinks, loudly
    assert any("a::99" in w and "not in this package" in w
               for w in g.warnings)


def test_fully_unresolved_group_warns_and_is_not_built():
    conds = [_cond("Nucor", 100, [
        {"group": "ghost", "treatment": "separate", "folded_into": None,
         "items": [{"schedule": "Z", "item_number": "9"}]}], flag=True)]
    s = apply_conditions(_spread(), conds)
    assert not s.scope_groups
    [w] = [w for w in s.condition_warnings
           if w["kind"] == "unresolved_group"]
    assert w["group"] == "ghost" and w["keys"] == ["z::9"]


def test_group_winner_tie_breaks_on_lowest_vendor_id():
    # equal fold prices; vendor order reversed so insertion order would
    # otherwise hand the tie to the higher vendor_id
    lines = {qid: [dict(ln) for ln in lns] for qid, lns in LINES.items()}
    lines[12][0]["unit_price"] = "2.4771"
    s = build_spread(ITEMS, BID_ITEMS, list(reversed(QUOTES)), lines)
    s = apply_conditions(s, _conditions())
    assert s.scope_groups[0].best_vendor_id == 200


def test_mix_none_reason_coverage_incomplete():
    items = ITEMS + [{"id": 3, "project_bid_item_id": 36, "item_number": "36",
                      "schedule_name": "A", "item_code": None}]
    bid_items = BID_ITEMS + [{"id": 36, "description": "Mesh", "unit": "LS",
                              "quantity": "1"}]
    s = build_spread(items, bid_items, QUOTES, LINES)   # nobody quotes 36
    s = apply_conditions(s, _conditions(nucor_flag=None, cvr_flag=None))
    assert s.obtainable_best_mix is None
    assert s.obtainable_best_mix_reason == "coverage"


def test_mix_none_reason_flags():
    # each vendor covers only one row and both forbid separate acceptance:
    # every row has a price, but none that respects the flags
    lines = {10: [LINES[10][0]], 11: [{"id": 5, "work_package_item_id": 2,
                                       "unit_price": "40000", "quantity": "1",
                                       "amount": None, "is_included": True}]}
    s = build_spread(ITEMS, BID_ITEMS, QUOTES[:2], lines)
    s = apply_conditions(s, [_cond("Nucor", 100, [], flag=False),
                             _cond("CVR", 200, [], flag=False)])
    assert s.obtainable_best_mix is None
    assert s.obtainable_best_mix_reason == "flags"


def test_alternate_cell_does_not_count_as_coverage():
    # CVR's line on item 35 is a priced ALTERNATE, not a base bid; CVR still covers
    # item 35 here via the CAGES_FOLD tag (folded into its item-41 bid), so this
    # checks the alternate line ITSELF contributes nothing to that coverage or to
    # the group/obtainable math -- the base-only numbers are identical to the
    # un-alternated fixture, only `has_alternates` and the gap differ.
    base = apply_conditions(build_spread(ITEMS, BID_ITEMS, QUOTES, LINES), _conditions())
    lines = {qid: [dict(ln) for ln in lns] for qid, lns in LINES.items()}
    lines[11].append({"id": 99, "work_package_item_id": 2, "unit_price": "1000",
                      "quantity": "1", "amount": None, "is_included": False,
                      "is_alternate": True})
    s = apply_conditions(build_spread(ITEMS, BID_ITEMS, QUOTES, lines), _conditions())
    assert s.has_alternates is True and base.has_alternates is False
    assert s.scope_groups[0].subtotals == base.scope_groups[0].subtotals
    assert s.obtainable_single_vendor == base.obtainable_single_vendor
    assert s.obtainable_best_mix == base.obtainable_best_mix
    assert {"vendor_id": 200, "work_package_item_id": 2, "reason": "alternate"} in s.gaps
