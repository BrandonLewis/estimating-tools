"""ACI standard bend diameters and hook dimensions — an ESTIMATING AID for
cut-length/weight takeoffs and IFC bar authoring, not a design tool.

Sources (cited per table): ACI 318-19 Table 25.3.1 (standard hooks for
development), Table 25.3.2 (stirrup/tie hooks); detailing practice per
ACI 315. All dimensions inches; db = nominal bar diameter."""
from __future__ import annotations

import math

from estimating_tools.rebar.model import BarSize

#: ACI 318-19 Table 25.3.1 — inside bend diameter, multiples of db
_BEND_DIA_DB = {3: 6, 4: 6, 5: 6, 6: 6, 7: 6, 8: 6, 9: 8, 10: 8, 11: 8, 14: 10, 18: 10}

#: hook type -> (extension rule) — see functions below
HOOKS = ("90", "180", "stirrup90", "stirrup135", "stirrup180")

_STIRRUP_MAX = 8  # Table 25.3.2 covers #3-#8


def bend_diameter_in(size: BarSize) -> float:
    """Inside bend diameter (in) per ACI 318-19 Table 25.3.1."""
    return _BEND_DIA_DB[size.number] * size.diameter_in


def hook_extension_in(size: BarSize, hook: str) -> float:
    """Straight extension beyond the bend (in) for a standard hook.

    90/180: Table 25.3.1 (12db; 180 -> max(4db, 2.5in)).
    stirrup90: Table 25.3.2 (#3-#5: 6db; #6-#8: 12db).
    stirrup135: 6db per Table 25.3.2, floored at 3in (the seismic-hook
    minimum, 25.3.4) — conservative for non-seismic ties.
    stirrup180: max(4db, 2.5in).
    """
    db = size.diameter_in
    if hook == "90":
        return 12 * db
    if hook == "180":
        return max(4 * db, 2.5)
    if hook.startswith("stirrup"):
        if size.number > _STIRRUP_MAX:
            raise ValueError(
                f"stirrup hooks apply to #3-#{_STIRRUP_MAX} (got {size})")
        if hook == "stirrup90":
            return 6 * db if size.number <= 5 else 12 * db
        if hook == "stirrup135":
            return max(6 * db, 3.0)
        if hook == "stirrup180":
            return max(4 * db, 2.5)
    raise ValueError(f"unknown hook type {hook!r} (expected one of {HOOKS})")


def hook_allowance_in(size: BarSize, hook: str) -> float:
    """Added bar length (in) a hook contributes to cut length: the bend arc
    (at centerline radius = (bend dia + db)/2) plus the straight extension.
    Conservative estimating allowance — detailers may use shop deductions."""
    angle_deg = {"90": 90.0, "180": 180.0, "stirrup90": 90.0,
                 "stirrup135": 135.0, "stirrup180": 180.0}[_check(hook)]
    r_cl = (bend_diameter_in(size) + size.diameter_in) / 2.0
    arc = math.radians(angle_deg) * r_cl
    return arc + hook_extension_in(size, hook)


def _check(hook: str) -> str:
    if hook not in HOOKS:
        raise ValueError(f"unknown hook type {hook!r} (expected one of {HOOKS})")
    return hook
