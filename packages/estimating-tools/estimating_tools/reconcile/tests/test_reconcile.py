"""Tests for contract-vs-estimate reconciliation (#206)."""
from __future__ import annotations

import pytest

from estimating_tools.reconcile import (
    LineItem, reconcile_contract_vs_estimate, to_markdown, to_rows,
)

# BM holds estimate at COST unit price; contract holds the SELL unit price.
BM = [
    LineItem(item="67", description="Structural Concrete, Bridge", unit="CY",
             quantity=2868, unit_price=938.77),   # ~22% under contract
    LineItem(item="81", description="Bar Reinforcing Steel", unit="LB",
             quantity=1182427, unit_price=1.42),  # ~13% under contract
    LineItem(item="199", description="24in Seismic Expansion", unit="EA",
             quantity=1, unit_price=52000.0),      # BM only
]
CONTRACT = [
    LineItem(item="67", description="Structural Concrete, Bridge", unit="CY",
             quantity=2868, unit_price=1150.0),
    LineItem(item="81", description="Bar Reinforcing Steel", unit="LB",
             quantity=1182427, unit_price=1.60),
    LineItem(item="192", description="Mobilization", unit="LS",
             quantity=1, unit_price=1250000.0),    # contract only
]


def _recon(**kw):
    return reconcile_contract_vs_estimate(BM, CONTRACT, markup=0.13, **kw)


def test_matched_line_math():
    r = _recon()
    line = next(x for x in r.lines if x.item == "67")
    assert line.status == "matched"
    assert line.bm_cost_total == pytest.approx(2868 * 938.77)
    assert line.contract_total == pytest.approx(2868 * 1150.0)
    assert line.bm_sell_total == pytest.approx(2868 * 938.77 * 1.13)
    assert line.margin == pytest.approx(line.contract_total - line.bm_cost_total)
    assert line.margin_pct == pytest.approx(line.margin / line.contract_total)
    assert line.effective_markup == pytest.approx(1150.0 / 938.77 - 1)


def test_contract_only_is_full_margin():
    r = _recon()
    line = next(x for x in r.lines if x.item == "192")
    assert line.status == "contract_only"
    assert line.bm_unit_cost is None and line.bm_cost_total is None
    assert line.contract_total == pytest.approx(1250000.0)
    assert line.margin == pytest.approx(1250000.0)   # no BM cost -> all margin
    assert line.margin_pct == pytest.approx(1.0)


def test_bm_only_is_flagged_for_removal():
    r = _recon()
    line = next(x for x in r.lines if x.item == "199")
    assert line.status == "bm_only"
    assert line.contract_unit_price is None and line.contract_total is None
    assert line.bm_cost_total == pytest.approx(52000.0)


def test_effective_markup_flag_band():
    # flag when eff. markup is outside [5%, 30%]
    r = _recon(flag_low=0.05, flag_high=0.30)
    m67 = next(x for x in r.lines if x.item == "67")   # ~22% -> inside band
    m81 = next(x for x in r.lines if x.item == "81")   # ~12.7% -> inside band
    assert not m67.flag and not m81.flag
    r2 = _recon(flag_low=0.15, flag_high=0.20)         # tighter band
    m81b = next(x for x in r2.lines if x.item == "81")  # 12.7% < 15% -> flag
    assert m81b.flag


def test_totals_and_blended_margin():
    r = _recon()
    bm_cost = 2868 * 938.77 + 1182427 * 1.42            # matched only
    contract = 2868 * 1150.0 + 1182427 * 1.60 + 1250000.0
    assert r.bm_cost_total == pytest.approx(bm_cost)
    assert r.contract_total == pytest.approx(contract)
    assert r.margin == pytest.approx(contract - bm_cost)
    assert r.margin_pct == pytest.approx((contract - bm_cost) / contract)
    assert (r.matched, r.contract_only, r.bm_only) == (2, 1, 1)


def test_accepts_dict_rows():
    r = reconcile_contract_vs_estimate(
        [{"item": "1", "quantity": 2, "unit_price": 100.0}],
        [{"item": "1", "quantity": 2, "unit_price": 130.0}],
        markup=0.0)
    line = r.lines[0]
    assert line.margin == pytest.approx(2 * 130.0 - 2 * 100.0)


def test_ordering_is_deterministic_numeric():
    r = _recon()
    matched_contract = [x.item for x in r.lines if x.status != "bm_only"]
    assert matched_contract == ["67", "81", "192"]   # numeric sort, not "192"<"67"
    assert r.lines[-1].item == "199"                 # bm_only last


def test_to_rows_and_markdown():
    r = _recon()
    rows = to_rows(r)
    assert rows[0][0] == "Item"                       # header
    assert "Eff. markup" in rows[0] and "Status" in rows[0]
    # the matched row surfaces effective markup + status
    m67 = next(row for row in rows[1:] if row[0] == "67")
    status_idx = rows[0].index("Status")
    assert m67[status_idx] == "matched"
    md = to_markdown(r)
    assert "Contract vs Estimate" in md
    assert "IN CONTRACT, NOT IN ESTIMATE" in md       # the add-scope section
    assert "IN ESTIMATE, NOT IN CONTRACT" in md       # the remove-scope section
    assert "TOTAL" in md


def test_reconcile_rejects_duplicate_items():
    dup = [LineItem(item="1", quantity=1, unit_price=10.0),
           LineItem(item="1", quantity=2, unit_price=20.0)]
    with pytest.raises(ValueError, match="duplicate item"):
        reconcile_contract_vs_estimate([], dup)
    with pytest.raises(ValueError, match="duplicate item"):
        reconcile_contract_vs_estimate(dup, [])


def test_numeric_equal_ids_order_is_stable():
    # "02" and "2" are numerically equal; order must not depend on input order
    c1 = [LineItem(item="2", quantity=1, unit_price=1.0),
          LineItem(item="02", quantity=1, unit_price=1.0)]
    c2 = list(reversed(c1))
    order1 = [x.item for x in reconcile_contract_vs_estimate([], c1).lines]
    order2 = [x.item for x in reconcile_contract_vs_estimate([], c2).lines]
    assert order1 == order2 == ["02", "2"]


def test_markdown_escapes_pipe_in_cells():
    c = [LineItem(item="1", description="Concrete | Bridge", unit="CY",
                  quantity=1, unit_price=100.0)]
    md = to_markdown(reconcile_contract_vs_estimate([], c))
    assert r"Concrete \| Bridge" in md                # escaped, not two columns
