"""Build + validate the git-ignored D84 wingwall steel catalog from the D85
(Type E stepped wingwall) and D86A (warped wingwall + stiffening beam) DXFs.

TYPE E (D85) "TABLE OF REINFORCEMENT FOR TYPE E WINGWALLS" is a clean column
grid keyed by wall height H: "k" BAR No./SPACING (stem verticals) and "L" BAR
No./NUMBER EACH WALL (wall-top horizontals), same `cell_at` grid-snap pattern
used for the box-culvert and headwall catalogs.

WARPED WALL (D86A) "WALL DIMENSIONS AND REINFORCING" is a column grid keyed by
H, with three stacked FRONT/REAR face-bar row-pairs (one per face slope) plus
a "D" AT CUTOFF WALL / "D" AT CULVERT dimension row. The face-slope labels use
glyph 0x82 for one-half and 0x83 for three-quarters (NOT the 0x81 = one-half
glyph the "D" dimensions use two rows down) -- we decode each context with its
own fraction map and locate the FRONT/REAR row bands by fixed y-offset from
each slope label, so the grouping doesn't depend on assuming a label order.

STIFFENING BEAM (D86A) "STIFFENING BEAM DIMENSIONS AND REINFORCING" is NOT a
grid keyed to the H/L header: its TOTAL n-#m / "A"= / "B"= callouts sit inside
a schematic "typical layout of wall reinforcing" detail positioned wherever it
fit on the sheet, unrelated to the L-column x-coordinates above it. Only 4
distinct TOTAL regions exist on the whole sheet (confirmed verbatim below) and
we cannot recover which L/H cells fall in which region from geometry alone.
Per the R20 Task 8 plan this is an accepted hand-reduction: each is mapped to
a defensible per-L height breakpoint (monotonically increasing bar size as L
grows), and the 4 TOTAL strings are still gated against the raw DXF text so a
sheet revision that changes the callouts will fail this script instead of
silently drifting.

    python scripts/dxf_build_wingwall_tables.py <d085.dxf> <d086a.dxf> <out.yaml> [--write]
"""
import re
import sys
from pathlib import Path

import ezdxf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "bimforge"))
from bimforge.author.box_section import parse_bar_spec  # noqa: E402
from bimforge.author.wingwall_steel import (  # noqa: E402
    WingwallSteel, parse_bar_size, parse_bar_total)

# ---------------------------------------------------------------- DXF I/O --

def _iter(c, depth=0):
    for e in c:
        dt = e.dxftype()
        if dt in ("TEXT", "MTEXT"):
            yield e
        elif dt == "INSERT" and depth < 4:
            yield from _iter(e.virtual_entities(), depth + 1)


def load_cells(dxf):
    """(x, y, raw_text) for every TEXT/MTEXT, undecoded -- fraction glyphs are
    context-dependent (0x81 for D-dims, 0x82/0x83 for slope labels) so we keep
    the raw bytes and decode per-field."""
    d = ezdxf.readfile(str(dxf))
    out = []
    for e in _iter(d.modelspace()):
        if not hasattr(e.dxf, "insert"):
            continue
        t = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
        t = t.replace("%%u", "").replace("%%U", "").strip()
        if t:
            out.append((round(e.dxf.insert.x, 1), round(e.dxf.insert.y, 1), t))
    return out


def cell_at(cells, cx, cy, xw, yw):
    best, bd = "", 1e9
    for x, y, t in cells:
        if abs(x - cx) < xw and abs(y - cy) < yw:
            dd = abs(x - cx) + abs(y - cy) * 3
            if dd < bd:
                best, bd = t, dd
    return best


def _header_row_y(cells, pattern, x_filter=lambda x: True):
    """y of the densest cluster of cells whose text fullmatches `pattern`."""
    ys = sorted(y for x, y, t in cells if x_filter(x) and re.fullmatch(pattern, t))
    if not ys:
        raise ValueError(f"no header cells found for {pattern!r}")
    best_y, best_n = ys[0], 0
    for y0 in ys:
        n = sum(1 for y in ys if abs(y - y0) < 3)
        if n > best_n:
            best_n, best_y = n, y0
    return best_y


def _header_cols(cells, pattern, x_filter=lambda x: True):
    header_y = _header_row_y(cells, pattern, x_filter)
    cols = sorted({(x, t.rstrip("'")) for x, y, t in cells
                   if x_filter(x) and re.fullmatch(pattern, t) and abs(y - header_y) < 6})
    return header_y, cols


def _norm_bar(s: str) -> str:
    """'#4 @ 12' / '#4   @ 12' -> '#4@12'."""
    return re.sub(r"\s+", "", s)


def _dim_in(s: str) -> float:
    """"D" dims use glyph 0x81 for one-half: '6\x81"' -> 6.5, '1\'-1\x81"' -> 13.5."""
    s = s.replace("\x81", ".5").replace('"', "").strip()
    if "'-" in s:
        f, i = s.split("'-")
        return round(float(f) * 12.0 + float(i), 2)
    return round(float(s), 2)


def _slope_key(s: str) -> str:
    """Face-slope labels use 0x82 for one-half, 0x83 for three-quarters (never
    0x81 here): '\x82:1' -> '0.5:1', '\x83:1' -> '0.75:1', '1\x82:1' -> '1.5:1'."""
    m = re.fullmatch(r"(\d*)([\x82\x83]):1", s.strip())
    if not m:
        raise ValueError(f"unparseable slope label {s!r}")
    whole = int(m.group(1)) if m.group(1) else 0
    frac = 0.5 if m.group(2) == "\x82" else 0.75
    return f"{whole + frac:g}:1"


# -------------------------------------------------------------- D85 Type E --

def build_type_e(cells):
    header_y, cols = _header_cols(cells, r"\d+'")
    rows = [("k_bar", -14.3, 4.0), ("k_sp", -28.75, 3.0),
             ("L_bar", -43.2, 3.0), ("L_num", -56.0, 3.0)]
    group = {}
    for cx, hkey in cols:
        vals = {name: cell_at(cells, cx, header_y + dy, xw=14, yw=yw)
                 for name, dy, yw in rows}
        k_sp = vals["k_sp"].replace("@", "").strip()
        group[hkey] = {
            "k_bar": f"{vals['k_bar']}@{k_sp}",
            "L_bar": vals["L_bar"],
            "L_each_wall": int(vals["L_num"]),
        }
    return group


GT_TYPE_E = {
    "3":  {"k_bar": "#4@12", "L_bar": "#5", "L_each_wall": 2},
    "4":  {"k_bar": "#4@12", "L_bar": "#5", "L_each_wall": 2},
    "5":  {"k_bar": "#5@12", "L_bar": "#6", "L_each_wall": 3},
    "6":  {"k_bar": "#5@10", "L_bar": "#6", "L_each_wall": 3},
    "7":  {"k_bar": "#5@9",  "L_bar": "#7", "L_each_wall": 3},
    "8":  {"k_bar": "#5@8",  "L_bar": "#7", "L_each_wall": 3},
    "10": {"k_bar": "#5@7",  "L_bar": "#7", "L_each_wall": 3},
    "12": {"k_bar": "#5@5",  "L_bar": "#7", "L_each_wall": 3},
    "14": {"k_bar": "#5@4",  "L_bar": "#7", "L_each_wall": 3},
}


# -------------------------------------------------------- D86A warped wall --

def build_warped_wall(cells):
    header_y, cols = _header_cols(cells, r"\d+'", x_filter=lambda x: x < -100)
    slope_labels = [(x, y, t) for x, y, t in cells
                     if re.fullmatch(r"\d*[\x82\x83]:1", t)]
    d_cutoff_y = next(y for x, y, t in cells if t == '"D" AT CUTOFF WALL')
    d_culvert_y = next(y for x, y, t in cells if t == '"D" AT CULVERT')

    group = {hkey: {} for _, hkey in cols}
    slopes_by_h = {hkey: {} for _, hkey in cols}
    for _lx, ly, ltext in slope_labels:
        slope = _slope_key(ltext)
        for cx, hkey in cols:
            front = _norm_bar(cell_at(cells, cx, ly + 6.8, xw=25, yw=3.0))
            rear = _norm_bar(cell_at(cells, cx, ly - 6.7, xw=25, yw=2.5))
            slopes_by_h[hkey][slope] = {"front": front, "rear": rear}

    for cx, hkey in cols:
        group[hkey] = {
            "D_cutoff_in": _dim_in(cell_at(cells, cx, d_cutoff_y, xw=25, yw=3.0)),
            "D_culvert_in": _dim_in(cell_at(cells, cx, d_culvert_y, xw=25, yw=3.0)),
            "slopes": slopes_by_h[hkey],
        }
    return group


GT_WALL = {
    "8":  {"D_cutoff_in": 6.5, "D_culvert_in": 6.5},
    "10": {"D_cutoff_in": 6.5, "D_culvert_in": 6.5},
    "12": {"D_cutoff_in": 6.5, "D_culvert_in": 6.5},
    "14": {"D_cutoff_in": 8.0, "D_culvert_in": 8.5},
    "16": {"D_cutoff_in": 8.5, "D_culvert_in": 10.0},
    "18": {"D_cutoff_in": 10.0, "D_culvert_in": 11.5},
    "20": {"D_cutoff_in": 11.5, "D_culvert_in": 13.5},
}
GT_WALL_H_ORDER = ["8", "10", "12", "14", "16", "18", "20"]
GT_WALL_SLOPES = {
    "0.5:1": {
        "front": ["#4@12", "#4@7", "#5@7", "#5@5", "#6@6", "#7@7", "#7@6"],
        "rear":  ["#4@12"] * 7,
    },
    "0.75:1": {
        "front": ["#4@12", "#4@12", "#4@8", "#4@8", "#4@8", "#4@6", "#4@6"],
        "rear":  ["#4@12", "#4@12", "#4@12", "#4@10", "#4@7", "#4@6", "#5@8"],
    },
    "1.5:1": {
        "front": ["#4@12"] * 7,
        "rear":  ["#4@8", "#4@8", "#4@5", "#5@6", "#6@7", "#6@6", "#7@6"],
    },
}
for _slope, _faces in GT_WALL_SLOPES.items():
    for _i, _h in enumerate(GT_WALL_H_ORDER):
        GT_WALL[_h].setdefault("slopes", {})[_slope] = {
            "front": _faces["front"][_i], "rear": _faces["rear"][_i]}


# ------------------------------------------------------- D86A stiffening beam
#
# Hand-reduced per R20 Task 8 plan escalation clause: the 4 TOTAL regions on
# the sheet, each covering the full tabulated H range (h_max: 20) for its L
# breakpoint. Bar size is monotonically non-decreasing as L grows. A_ft/B_ft
# are carried through for reference (from the sheet's "A"=/"B"= callouts) but
# are not independently gated here -- only the TOTAL bar-count strings, which
# are checked against the raw DXF text below.
BEAM_TOTALS = ("TOTAL 6-#6", "TOTAL 6-#7", "TOTAL 8-#8", "TOTAL 8-#9")
BEAM_BY_L = {
    "12": [{"h_max": 20, "kind": "none", "total": "6-#6"}],
    "14": [{"h_max": 20, "kind": "none", "total": "6-#6"}],
    "16": [{"h_max": 20, "total": "6-#7", "A_ft": 1.0, "B_ft": 0.75}],
    "20": [{"h_max": 20, "total": "6-#7", "A_ft": 1.0, "B_ft": 0.75}],
    "25": [{"h_max": 20, "total": "8-#8", "A_ft": 1.5, "B_ft": 1.0}],
    "30": [{"h_max": 20, "total": "8-#9", "A_ft": 1.833, "B_ft": 1.25}],
    "35": [{"h_max": 20, "total": "8-#9", "A_ft": 1.833, "B_ft": 1.25}],
    "40": [{"h_max": 20, "total": "8-#9", "A_ft": 1.833, "B_ft": 1.25}],
}


def check_beam_totals_present(cells):
    raw = {t for _x, _y, t in cells}
    return [tt for tt in BEAM_TOTALS if tt not in raw]


# -------------------------------------------------------------- validation --

def validate(type_e, wall, beam_by_l, d86_cells):
    bad = []

    for h, row in GT_TYPE_E.items():
        got = type_e.get(h)
        if got != row:
            bad.append(("type_e", h, got, row))

    for h, row in GT_WALL.items():
        got = wall.get(h)
        if got is None:
            bad.append(("wall", h, None, row))
            continue
        if got["D_cutoff_in"] != row["D_cutoff_in"] or got["D_culvert_in"] != row["D_culvert_in"]:
            bad.append(("wall D", h, (got["D_cutoff_in"], got["D_culvert_in"]),
                        (row["D_cutoff_in"], row["D_culvert_in"])))
        for slope, spec in row["slopes"].items():
            got_slope = got["slopes"].get(slope)
            if got_slope != spec:
                bad.append(("wall slope", (h, slope), got_slope, spec))

    for h in wall:
        got_slopes = set(wall[h].get("slopes", {}).keys())
        if got_slopes != {"0.5:1", "0.75:1", "1.5:1"}:
            bad.append(("wall slope keys", h, sorted(got_slopes),
                        "{'0.5:1', '0.75:1', '1.5:1'}"))

    for h, row in type_e.items():
        try:
            parse_bar_spec(row["k_bar"])
            parse_bar_size(row["L_bar"])
        except ValueError as exc:
            bad.append(("type_e parse", h, str(exc), None))

    for h, row in wall.items():
        for slope, spec in row["slopes"].items():
            try:
                parse_bar_spec(spec["front"])
                parse_bar_spec(spec["rear"])
            except ValueError as exc:
                bad.append(("wall parse", (h, slope), str(exc), None))

    missing_totals = check_beam_totals_present(d86_cells)
    if missing_totals:
        bad.append(("beam totals missing from DXF text", None, missing_totals, BEAM_TOTALS))

    l_keys_sorted = sorted(beam_by_l, key=float)
    prev_size = 0
    for l in l_keys_sorted:
        for reg in beam_by_l[l]:
            try:
                _n, size = parse_bar_total(reg["total"])
            except ValueError as exc:
                bad.append(("beam parse", l, str(exc), None))
                continue
            if size < prev_size:
                bad.append(("beam monotonic", l, size, f">= {prev_size}"))
            prev_size = max(prev_size, size)

    return bad


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    d85, d86, out = Path(argv[1]), Path(argv[2]), Path(argv[3])

    d85_cells = load_cells(d85)
    d86_cells = load_cells(d86)

    type_e = build_type_e(d85_cells)
    wall = build_warped_wall(d86_cells)
    beam_by_l = BEAM_BY_L

    bad = validate(type_e, wall, beam_by_l, d86_cells)
    print(f"type_e rows: {len(type_e)}   wall rows: {len(wall)}   "
          f"beam L-breakpoints: {len(beam_by_l)}   validation failures: {len(bad)}")
    for b in bad[:40]:
        print("  ", b)
    if bad:
        return 1

    # sanity: the emitted table must actually construct + round-trip a lookup
    steel = {"type_e": type_e, "warped": {"wall": wall, "beam": {"by_l": beam_by_l}}}
    ws = WingwallSteel(steel)
    ws.type_e(3.0); ws.type_e(14.0)
    ws.warped_wall(8.0, "0.5:1"); ws.warped_wall(20.0, "1.5:1")
    ws.beam_region(12.0, 20.0); ws.beam_region(35.0, 20.0)

    if "--write" in argv:
        header = (
            "# Caltrans D84 wingwall reinforcement steel catalog.\n"
            "# Auto-generated by scripts/dxf_build_wingwall_tables.py from\n"
            "# data/caltrans-2025/dxf/2025__d085.dxf (Type E) and\n"
            "# data/caltrans-2025/dxf/2025__d086a.dxf (warped wall + beam).\n"
            "#\n"
            "# type_e and warped.wall are grid-extracted from the sheets' tables and\n"
            "# validated row-for-row against transcribed ground truth.\n"
            "#\n"
            "# warped.beam.by_l is a HAND-REDUCED approximation of the sheet's H x L\n"
            "# stiffening-beam staircase: the TOTAL/A/B callouts sit inside a\n"
            "# schematic detail, not a grid keyed to the L header, so the exact\n"
            "# staircase could not be recovered from geometry. The 4 distinct TOTAL\n"
            "# bar-count regions on the sheet (gated against the raw DXF text) are\n"
            "# mapped to conservative per-L height breakpoints, monotonically\n"
            "# increasing in bar size as L grows. See the module docstring.\n"
        )
        out.write_text(header + yaml.safe_dump({"steel": steel}, sort_keys=True),
                       encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
