"""Deterministic comparability scoring + suggested range (Phase 5 spec).

Pure function of (records, target): same inputs, same output. The skill
layer presents the result; the estimator confirms every price. No
escalation by default — ages are surfaced instead (profile seam
``estimating.escalation_rate_annual`` applies a flat annual rate if set).
"""
from __future__ import annotations

import math
from datetime import date

OUTCOME_WEIGHT = {"actualized": 1.0, "awarded": 0.9, "bid": 0.75,
                  "competitor_bid": 0.6, "estimated": 0.5}
RECENCY_HALF_LIFE_YEARS = 3.0     # weight halves every 3 years of age
QUANTITY_HALF_RATIO = 4.0         # weight halves per 4x quantity difference
REGION_MISMATCH_WEIGHT = 0.7
THIN_HISTORY = 3


def record_price(rec: dict) -> float | None:
    outcome = rec.get("outcome")
    if outcome in ("awarded", "bid", "competitor_bid"):
        return rec.get("unit_price_bid")
    if outcome == "actualized":
        return rec.get("unit_cost_actual") or rec.get("unit_cost_estimated")
    return rec.get("unit_cost_estimated")


def _age_years(bid_date: str | None, as_of: date) -> float:
    # The unknown-date default (one half-life = 3.0y) also drives escalation
    # when the escalation_rate seam is active — an undated record escalates
    # as if it were 3 years old.
    if not bid_date:
        return RECENCY_HALF_LIFE_YEARS      # unknown age: one half-life penalty
    try:
        d = date.fromisoformat(str(bid_date)[:10])
    except ValueError:
        return RECENCY_HALF_LIFE_YEARS
    return max((as_of - d).days, 0) / 365.25


def _sort_date_key(bid_date: str | None):
    """Key that sorts ascending yet orders newest-first, missing last.

    A plain date/ordinal can't be negated as a string, so use the
    negated ordinal (an int) instead; a leading flag pushes missing/
    unparseable dates after every real date regardless of ordinal sign.
    """
    if not bid_date:
        return (1, 0)
    try:
        d = date.fromisoformat(str(bid_date)[:10])
    except ValueError:
        return (1, 0)
    return (0, -d.toordinal())


def _weight(rec: dict, *, quantity: float | None, region: str, as_of: date) -> float:
    w = OUTCOME_WEIGHT.get(rec.get("outcome"), 0.5)
    w *= 0.5 ** (_age_years(rec.get("bid_date"), as_of) / RECENCY_HALF_LIFE_YEARS)
    rq = rec.get("quantity")
    # log-ratio needs both positive; deduct/adjustment rows carry negative qty
    if quantity and rq and quantity > 0 and rq > 0:
        w *= 0.5 ** abs(math.log(rq / quantity, QUANTITY_HALF_RATIO))
    if region and rec.get("region") and \
            str(rec["region"]).strip().lower() != region.strip().lower():
        w *= REGION_MISMATCH_WEIGHT
    return w


def _weighted_pct(comps: list[dict], q: float) -> float:
    """Price at cumulative-weight fraction q, over comps sorted by price.

    Standard weighted-quantile step function: walk prices ascending,
    accumulating weight, and return the first price whose cumulative
    weight reaches the target fraction of total weight. For an odd
    number of equal-weight comps this lands exactly on the middle price
    at q=0.5, matching the classic unweighted median.
    """
    ordered = sorted(comps, key=lambda c: c["unit_price"])
    weights = [c["weight"] for c in ordered]
    total = sum(weights)
    if total <= 0:
        # Weights are rounded to 6 decimals, so very old records can all
        # land at 0.0 — fall back to the unweighted step-quantile rather
        # than skewing every percentile to the max price.
        weights = [1.0] * len(ordered)
        total = float(len(ordered))
    target = q * total
    cum = 0.0
    for w, c in zip(weights, ordered):
        cum += w
        if cum >= target:
            return c["unit_price"]
    return ordered[-1]["unit_price"]


def suggest(records: list[dict], *, quantity: float | None, unit: str,
            region: str = "", as_of: date | None = None,
            escalation_rate: float = 0.0) -> dict:
    as_of = as_of or date.today()
    comps, excluded = [], []
    for rec in records:
        price = record_price(rec)
        if price is None:
            excluded.append({"reason": "no price", "record": rec})
            continue
        if price <= 0:
            excluded.append({"reason": "non-positive price", "record": rec})
            continue
        rec_unit = str(rec.get("unit") or "").strip()
        if unit:
            if not rec_unit:
                excluded.append({"reason": "missing unit", "record": rec})
                continue
            if rec_unit.upper() != unit.strip().upper():
                excluded.append({"reason": "unit mismatch", "record": rec})
                continue
        age = _age_years(rec.get("bid_date"), as_of)
        if escalation_rate:
            price = price * (1.0 + escalation_rate) ** age
        comps.append({
            "unit_price": round(price, 2),
            "weight": round(_weight(rec, quantity=quantity, region=region,
                                    as_of=as_of), 6),
            "age_years": round(age, 2),
            "outcome": rec.get("outcome"),
            "bidder": rec.get("bidder", ""),
            "quantity": rec.get("quantity"),
            "unit": rec.get("unit", ""),
            "region": rec.get("region", ""),
            "bid_date": rec.get("bid_date"),
            "project_ref": rec.get("project_ref", ""),
        })
    # Single deterministic sort: weight desc primary, bid_date desc
    # secondary, unit_price asc tertiary.
    comps.sort(key=lambda c: (-c["weight"], _sort_date_key(c["bid_date"]),
                              c["unit_price"]))
    if not comps:
        return {"status": "no_history", "n": 0, "comparables": [],
                "excluded": excluded}
    return {
        "status": "ok" if len(comps) >= THIN_HISTORY else "thin",
        "n": len(comps),
        "suggested": {"p25": _weighted_pct(comps, 0.25),
                      "median": _weighted_pct(comps, 0.50),
                      "p75": _weighted_pct(comps, 0.75)},
        "comparables": comps,
        "excluded": excluded,
    }
