"""Assemble + validate the Caltrans D90 culvert-headwall catalog from the
sheet-FIXED rules transcribed off the D90 Standard Plan (DGN 2025__d090.dgn,
git-ignored; manifest data/caltrans-2025/manifest.json).

D90 fixes very little dimensionally. Note 4 states the wingwall elevation,
length and flare angle are varied by the Engineer in the field, and the
wall/footing dimensions (C,B,F,W) plus wall/footing reinforcing come from the
B3 Type-1 Standard Plans (B3-1A/1B/1C). So there is NO wingwall dimension table
or bar schedule to grid-snap here -- those are supplied per-structure in the
project spec. This builder encodes ONLY the FIXED rules the sheet does pin:

    d90:
      wingwall_types:  A/B straight, C is a wall; each references B3 Type-1
                       plans; Type C requires a barrier.
      loading_cases:   the three loading-case labels.
      pipe:            cover min/max, end fillet, RC-only distribution
                       reinforcing (metal pipe uses hook bolts).
      type_c_barrier:  Caltrans Type 836 (36in) per B11-80.
      wall_height_tolerance_ft: Note 5 tolerance before stepping to next H.
      design:          soil/material properties transcribed from the sheet.

SOURCES holds these transcribed constants. validate() REFUSES to write if any
fixed section is missing/None, so a broken edit cannot silently emit a partial
catalog.

    python scripts/dxf_build_d90_catalog.py [--write] [--out PATH]
"""
import sys
from pathlib import Path

import yaml

OUT = (Path(__file__).resolve().parents[1] / "data" / "caltrans-2025"
       / "tables" / "caltrans-d90-headwall.yaml")

# Comment header prepended by --write so a regenerate reproduces the committed
# file's provenance block (safe_dump would otherwise strip all comments).
HEADER = (
    "# Caltrans 2025 Standard Plan D90 -- Pipe Culvert Headwalls, Endwalls and\n"
    "# Wingwalls, Types A, B and C. Source DGN 2025__d090.dgn (git-ignored;\n"
    "# manifest data/caltrans-2025/manifest.json).\n"
    "#\n"
    "# D90 fixes very little dimensionally. Note 4: wingwall elevation, length and\n"
    "# flare angle are varied by the Engineer in the field. Wall/footing dimensions\n"
    "# C,B,F,W and wall/footing reinforcing come from the B3 Type-1 Standard Plans\n"
    "# (B3-1A/1B/1C). This catalog therefore encodes ONLY the sheet-FIXED rules;\n"
    "# wingwall geometry and the bar schedule are supplied per-structure in the\n"
    "# project spec (field-varied).\n")

# ---------------------------------------------------------------- SOURCES --
# The sheet-FIXED D90 rules, transcribed from the Standard Plan. These are the
# only values D90 pins; wingwall geometry + bar schedule are field-varied and
# supplied per-structure in the project spec.
SOURCES = {
    "wingwall_types": {
        "A": {"shape": "straight",
              "b3_plans": ["B3-1A", "B3-1B", "B3-1C"], "barrier": "none"},
        "B": {"shape": "straight",
              "b3_plans": ["B3-1A", "B3-1B", "B3-1C"],
              "barrier": "optional_case1"},
        "C": {"shape": "wall",
              "b3_plans": ["B3-1B", "B3-1C"], "barrier": "required"},
    },
    "loading_cases": ["1", "2", "3"],
    "pipe": {
        "cover_above_min_ft": 1.0,
        "cover_above_max_ft": 4.0,
        "end_fillet_r_in": 3.0,
        "distribution": {
            "material": "rc_only",
            "sizes": [6, 4],
            "note": ("Note 6: adjacent to each side of the pipe opening place "
                     "additional vertical bars bent into the footing, "
                     "equivalent to half of the cut-off main bars by the pipe "
                     "(see Section C-C / D-D)."),
        },
        "metal": "hook_bolts",
    },
    "type_c_barrier": {
        "barrier_type": "836",
        "h_ft": 3.0,
        "per_standard_plan": "B11-80",
    },
    "wall_height_tolerance_ft": 0.5,
    "design": {
        "soil_unit_weight_pcf": 120,
        "soil_phi_deg": 34,
        "fc_psi": 3600,
        "fy_psi": 60000,
    },
}


def _missing(obj):
    """True if any leaf is None or any container is empty (recursive)."""
    if isinstance(obj, dict):
        return not obj or any(_missing(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return len(obj) == 0 or any(_missing(v) for v in obj)
    return obj is None


def validate(sources):
    """Return a list of human-readable reasons the catalog cannot be written."""
    bad = []

    wt = sources.get("wingwall_types") or {}
    for typ in ("A", "B", "C"):
        entry = wt.get(typ)
        if not entry:
            bad.append(f"wingwall Type {typ} is missing")
            continue
        if not entry.get("shape"):
            bad.append(f"wingwall Type {typ} has no shape")
        if not entry.get("b3_plans"):
            bad.append(f"wingwall Type {typ} has no B3 Type-1 plan refs")
        if entry.get("barrier") is None:
            bad.append(f"wingwall Type {typ} has no barrier rule")

    tcb = sources.get("type_c_barrier") or {}
    if not tcb.get("barrier_type"):
        bad.append("Type C barrier type is missing")
    if tcb.get("h_ft") is None:
        bad.append("Type C barrier height (h_ft) is missing")

    pipe = sources.get("pipe") or {}
    dist = pipe.get("distribution") or {}
    if not dist.get("material"):
        bad.append("pipe distribution reinforcing material is missing")
    if not pipe.get("metal"):
        bad.append("pipe metal-pipe rule is missing")
    for k in ("cover_above_min_ft", "cover_above_max_ft", "end_fillet_r_in"):
        if pipe.get(k) is None:
            bad.append(f"pipe {k!r} is missing")
    if _missing(dist.get("sizes")):
        bad.append("pipe distribution sizes list is empty/None")

    if _missing(sources.get("loading_cases")):
        bad.append("loading_cases list is empty/un-transcribed")

    if sources.get("wall_height_tolerance_ft") is None:
        bad.append("wall_height_tolerance_ft is missing")

    design = sources.get("design") or {}
    for k in ("soil_unit_weight_pcf", "soil_phi_deg", "fc_psi", "fy_psi"):
        if design.get(k) is None:
            bad.append(f"design property {k!r} is missing")

    return bad


def assemble(sources):
    """Build the {'d90': {...}} catalog dict, refusing on any missing rule."""
    bad = validate(sources)
    if bad:
        raise ValueError(
            "refusing to build D90 catalog -- a fixed section is missing:\n  "
            + "\n  ".join(bad))
    return {"d90": sources}


def main(argv):
    print("D90 culvert-headwall catalog builder (fixed-rules)")
    print(f"  output: {OUT}")
    print("  transcribed SOURCES (fixed D90 rules to be written):")
    print(yaml.safe_dump({"d90": SOURCES}, sort_keys=False,
                         default_flow_style=False).rstrip())

    try:
        catalog = assemble(SOURCES)
    except ValueError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2

    if "--write" in argv:
        if "--out" in argv:
            i = argv.index("--out") + 1
            if i >= len(argv):
                print("\n--out requires a path argument", file=sys.stderr)
                return 2
            out = argv[i]
        else:
            out = OUT
        Path(out).write_text(
            HEADER + yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")
        print(f"\nwrote {out}")
    else:
        print("\nvalidation passed; re-run with --write to emit the catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
