"""Tension development and lap-splice lengths — SIMPLIFIED method, an
ESTIMATING AID (bar cut-length/weight takeoffs), not a design tool.

Method: ACI 318-19 Table 25.4.2.3 "simplified" tier assuming clear
spacing/cover conditions are met (the common cast-in-place case):
    ld = fy * psi_t * psi_e / (25 * lambda * sqrt(fc')) * db     (#6 and smaller)
    ld = fy * psi_t * psi_e / (20 * lambda * sqrt(fc')) * db     (#7 and larger)
with sqrt(fc') <= 100 psi (ACI 25.4.1.4), ld >= 12 in, psi_t (top bar) = 1.3,
psi_e (epoxy) = 1.5 (worst case; ACI allows 1.2 with cover >= 3db and clear
spacing >= 6db), psi_t*psi_e <= 1.7, psi_g (grade, Table 25.4.2.5) =
1.0/1.15/1.3 for Grade <=60/80/100 keyed off fy, lambda (lightweight)
= 0.75.
Laps: Class B = 1.3*ld (default per ACI 315 practice), Class A = max(ld, 12);
laps here use the 12-in-floored ld (Table 25.5.2.1 technically laps the
unfloored 25.4.2.1(a) value) — conservative by <= 3.6 in on small bars.
Factors are taken worst-case, BUT the spacing/cover assumption is the
favorable Table 25.4.2.3 row — congested details (cover/spacing condition
not met) develop 1.5x longer than this aid reports; design governs final
detailing."""
from __future__ import annotations

import math

from estimating_tools.rebar.model import BarSize


def development_length_in(size: BarSize, *, fc_psi: float, fy_psi: float = 60000.0,
                          top_bar: bool = False, epoxy: bool = False,
                          lightweight: bool = False) -> float:
    if fc_psi <= 0:
        raise ValueError(f"fc_psi must be positive, got {fc_psi}")
    sqrt_fc = min(math.sqrt(fc_psi), 100.0)
    psi = min((1.3 if top_bar else 1.0) * (1.5 if epoxy else 1.0), 1.7)
    # psi_g (grade factor, ACI 318-19 Table 25.4.2.5): 1.0 for Grade 60 and
    # below, 1.15 for Grade 80, 1.3 for Grade 100 — without it a Grade 80 fy
    # under-predicts ld ~13% vs code (the one non-conservative path; fixed).
    psi_g = 1.0 if fy_psi <= 60000.0 else (1.15 if fy_psi <= 80000.0 else 1.3)
    lam = 0.75 if lightweight else 1.0   # lambda divides: lightweight LENGTHENS ld
    denom = 25.0 if size.number <= 6 else 20.0
    ld = fy_psi * psi * psi_g / (denom * sqrt_fc * lam) * size.diameter_in
    return max(ld, 12.0)


def lap_length_in(size: BarSize, *, fc_psi: float, fy_psi: float = 60000.0,
                  top_bar: bool = False, epoxy: bool = False,
                  lightweight: bool = False, splice_class: str = "B") -> float:
    ld = development_length_in(size, fc_psi=fc_psi, fy_psi=fy_psi,
                               top_bar=top_bar, epoxy=epoxy,
                               lightweight=lightweight)
    if splice_class == "B":
        return 1.3 * ld
    if splice_class == "A":
        return max(ld, 12.0)
    raise ValueError(f"splice class must be 'A' or 'B', got {splice_class!r}")
