"""Earthwork volume and mass-haul math — pure functions, feet in, CY out.

Ported from two jobs where the arithmetic was proven the hard way:

- bridge-pilot ``build_exback_takeoff.py``: the benched
  excavation trio — neat prism, one-face lay-back wedge, and the all-round
  benched pit taken as an INCREMENT over its own neat prism (returning the
  pit raw double-counts the pay volume).
- canal-job sheet CS26 (revised Addendum No. 2): the consolidation-factor
  mass haul — 640,600 CY of cut against 537,200 CY of neat fill reads as a
  103,400 CY net export until the 25% consolidation factor turns the fill into
  716,200 CY of required borrow and flips the job to a 75,600 CY net import.

Convention note (do not mix these):

- CONSOLIDATION (shrinkage) factor ``f``: borrow shrinks by ``f`` when
  compacted, so required borrow = neat fill / (1 - f). This is the canal-job
  CS26 arithmetic (537,200 / 0.75 = 716,266.7, published rounded 716,200).
- BULKING (swell) factor is the OTHER convention — bank volume swells to
  loose volume, loose = bank * (1 + swell). That one sizes trucks, not fill.
  ``fill_required_cy`` uses consolidation/division, never neat * (1 + f).

No I/O, no Excel — stdlib only. Every function takes feet and returns cubic
yards (or CY-denominated dicts).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence

__all__ = [
    "prism_cy",
    "wedge_cy",
    "bench_increment_cy",
    "fill_required_cy",
    "mass_haul",
]


def prism_cy(length_ft: float, width_ft: float, depth_ft: float) -> float:
    """Neat rectangular prism in CY: length * width * depth / 27.

    The pay-line dig — identical to the RW/exback sheets' volume formula
    (bridge-pilot column math: B*F*G*H/27).
    """
    return length_ft * width_ft * depth_ft / 27.0


def wedge_cy(length_ft: float, depth_ft: float, run_ft: float) -> float:
    """One-face lay-back wedge in CY: a triangular run x rise along the length.

    length * run * depth / 2 / 27 — the unpaid extra when one face of the cut
    is sloped back ``run_ft`` over the full ``depth_ft``. Like every bench
    figure in this module, it is the increment OVER the neat prism, not a
    volume that contains it.
    """
    return length_ft * run_ft * depth_ft / 2.0 / 27.0


def bench_increment_cy(
    length_ft: float, width_ft: float, depth_ft: float, run_ft: float
) -> float:
    """All-round benched pit LESS its own neat prism — the bench INCREMENT, CY.

    The prismatoid rule ``depth/3 * (A0 + A1 + sqrt(A0*A1))`` gives the whole
    pit (A0 the neat bottom, A1 the laid-back top opening at +2*run each way),
    and the whole pit already contains the neat prism listed on its own row.
    Returning it raw double-counts the pay volume: on bridge-pilot, Bent 2 came out
    640 CY against a real dig of 372. Every bench figure therefore means the
    same thing — the unpaid extra over the pay line — whether it is a one-face
    wedge (:func:`wedge_cy`) or this all-round pit.

    Context: benches exist because OSHA Subpart P caps unprotected slopes
    (Type A soil: 3/4H:1V for both sloping and benching); on (F) final-pay
    items the plan quantity is not re-measured, so the bench earns nothing
    and is priced as hours and equipment only.
    """
    a0 = length_ft * width_ft
    a1 = (length_ft + 2.0 * run_ft) * (width_ft + 2.0 * run_ft)
    pit_cf = depth_ft / 3.0 * (a0 + a1 + math.sqrt(a0 * a1))
    neat_cf = length_ft * width_ft * depth_ft
    return (pit_cf - neat_cf) / 27.0


def fill_required_cy(neat_fill_cy: float, consolidation: float) -> float:
    """Borrow/loose CY required to build ``neat_fill_cy`` of compacted fill.

    CONSOLIDATION (shrinkage) convention — DIVISION: the placed material
    shrinks by ``consolidation`` when compacted, so
    ``required = neat / (1 - consolidation)``. canal-job CS26:
    537,200 CY neat at 25% consolidation -> 537,200 / 0.75 = 716,266.7 CY
    (published rounded 716,200). Do NOT confuse this with the bulking/swell
    convention (``neat * (1 + f)``) — that sizes loose truck volume off bank
    measure and gives a materially smaller (wrong) fill requirement here.

    ``consolidation`` is a fraction in [0, 1): pass 0.25 for 25%, not 25.
    """
    if consolidation < 0:
        raise ValueError(
            f"consolidation must be non-negative, got {consolidation}"
        )
    if consolidation >= 1:
        raise ValueError(
            "consolidation is a fraction in [0, 1) — pass 0.25 for 25%, "
            f"not {consolidation}"
        )
    return neat_fill_cy / (1.0 - consolidation)


def mass_haul(
    reaches: Sequence[Dict[str, Any]], consolidation: float
) -> Dict[str, Any]:
    """Reach-by-reach cut/fill balance with a consolidation factor, in CY.

    ``reaches`` is a list of ``{"name", "cut_cy", "fill_cy"}`` dicts (fill is
    NEAT/compacted CY as published on the earthwork summary sheet). Each
    output reach carries ``raw_net_cy`` (cut - fill; positive = surplus to
    haul away), ``fill_required_cy`` (neat fill grossed up by the
    consolidation factor — see :func:`fill_required_cy` for the
    division-not-multiplication convention), and ``net_import_cy``
    (required fill - cut; positive = must import). ``totals`` sums all four
    plus cut/fill, with the same explicit ``net_import_cy`` sign convention.

    Why this exists: raw volumes can lie about the job. canal-job CS26 read as
    a 103,400 CY net EXPORT on raw cut/fill, but the 25% consolidation factor
    flipped it to a 75,600 CY net IMPORT — and the reach imbalance (Reach 2
    short 65,100 CY against surpluses miles away in Reaches 1 and 4) meant
    the mass-haul plan, not the dig, set the price. Haul distance, not
    excavation, is the cost driver.
    """
    out_reaches: List[Dict[str, Any]] = []
    total_cut = 0.0
    total_fill = 0.0
    for reach in reaches:
        cut = float(reach["cut_cy"])
        fill = float(reach["fill_cy"])
        required = fill_required_cy(fill, consolidation)
        out_reaches.append({
            "name": reach["name"],
            "cut_cy": cut,
            "fill_cy": fill,
            "raw_net_cy": cut - fill,
            "fill_required_cy": required,
            "net_import_cy": required - cut,
        })
        total_cut += cut
        total_fill += fill
    total_required = fill_required_cy(total_fill, consolidation)
    return {
        "consolidation": consolidation,
        "reaches": out_reaches,
        "totals": {
            "cut_cy": total_cut,
            "fill_cy": total_fill,
            "raw_net_cy": total_cut - total_fill,
            "fill_required_cy": total_required,
            "net_import_cy": total_required - total_cut,
        },
    }
