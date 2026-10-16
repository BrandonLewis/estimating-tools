"""Reinforcing-steel (rebar) data model: ASTM A615 bar sizes and bar sets.

Pure: stdlib only. Drafting/detailing (bend shapes, placement drawings) is out
of scope here — ACI 315 bend shapes are a later phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: ASTM A615 imperial ("#") bar sizes: number -> (nominal diameter in, area in^2,
#: nominal weight lb/ft). Standard reference values.
BAR_SIZES: dict[int, tuple[float, float, float]] = {
    3: (0.375, 0.11, 0.376),
    4: (0.500, 0.20, 0.668),
    5: (0.625, 0.31, 1.043),
    6: (0.750, 0.44, 1.502),
    7: (0.875, 0.60, 2.044),
    8: (1.000, 0.79, 2.670),
    9: (1.128, 1.00, 3.400),
    10: (1.270, 1.27, 4.303),
    11: (1.410, 1.56, 5.313),
    14: (1.693, 2.25, 7.650),
    18: (2.257, 4.00, 13.600),
}


@dataclass(frozen=True)
class BarSize:
    """One reinforcing bar size (imperial ``#`` designation)."""

    number: int

    def __post_init__(self) -> None:
        if self.number not in BAR_SIZES:
            raise ValueError(
                f"unknown bar size #{self.number}; "
                f"ASTM A615 sizes: {sorted(BAR_SIZES)}"
            )

    @property
    def diameter_in(self) -> float:
        return BAR_SIZES[self.number][0]

    @property
    def area_in2(self) -> float:
        return BAR_SIZES[self.number][1]

    @property
    def weight_lb_per_ft(self) -> float:
        return BAR_SIZES[self.number][2]

    def __str__(self) -> str:
        return f"#{self.number}"


@dataclass
class Rebar:
    """A single reinforcing bar or a repeated set of bars."""

    size: BarSize
    length_ft: float
    count: int = 1
    mark: Optional[str] = None
    spacing_in: Optional[float] = None

    @property
    def total_weight_lb(self) -> float:
        return self.size.weight_lb_per_ft * self.length_ft * self.count
