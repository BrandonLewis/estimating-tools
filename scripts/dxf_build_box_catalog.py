"""Build + validate the git-ignored box-culvert section catalog from the D80
(single) and D81 (double) DXFs.

Grid-extracts each sheet (see dxf_extract_box_table.py for the raw grid), then
reconstructs the span groups from the reliable HEIGHT row and emits the
per-earth-cover schema BoxCulvertSection consumes:

    single:                        # D81 -> double:
      "8x5":                       # span x height key (ft)
        covers:
          10: {wall_t_ft, top_slab_ft, bot_slab_ft, a, b, e, conc_cf_lf,
               lb_per_lf, interior_wall_t_ft?}
          20: {...}

Every row is gate-checked: BoxCulvertSection.area_sf() must equal the sheet's own
tabulated CONCRETE CF/LF (the box-culvert transcription check). Nothing is
written if any row misses by more than its tolerance.

    python scripts/dxf_build_box_catalog.py <d080.dxf> <d081.dxf> <out.yaml> [--write]

Sheet differences handled here:
- D81's rows are shifted (two extra interior-wall bar marks between e and the
  dims) and it doubles each cover-label text entity at the same x (de-duped).
- The D81 double box has a thinner shared *interior* wall than its earth-loaded
  exterior walls: 6" for spans <= 8', 8" for spans >= 10' (the two source
  sub-tables). With that rule the modeled area reproduces the tabulated CONCRETE
  CF/LF to within ~1.3 sf on every row (79/84 within 0.15 sf); the small
  residual is minor corner fillets / invert slope the section model omits.
"""
import sys
from pathlib import Path

import ezdxf
import yaml
from ezdxf.tools.text import plain_text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "bimforge"))
from bimforge.author.box_section import BoxCulvertSection  # noqa: E402

# row y-offsets from the MAXIMUM-EARTH-COVER label row, per sheet
ROWS_D80 = [("HEIGHT", 16), ("ROOF", -14.4), ("WALLS", -28.6), ("INVERT", -43.4),
            ("a_size", -57.3), ("a_sp", -71.6), ("b_size", -85.7), ("b_sp", -99.7),
            ("e_size", -113.7), ("e_sp", -128.8), ("CONC", -161.1), ("REINF", -178.3)]
ROWS_D81 = [("HEIGHT", 16), ("ROOF", -14.5), ("WALLS", -29.1), ("INVERT", -43.7),
            ("a_size", -58.2), ("a_sp", -72.9), ("b_size", -87.4), ("b_sp", -102.3),
            ("e_size", -116.7), ("e_sp", -131.6), ("CONC", -235.5), ("REINF", -252.8)]


def clean(s):
    return (plain_text(s).replace("%%u", "").replace("%%U", "")
            .replace("\x81", ".5").replace("\n", " ").strip())


def _iter(c, depth=0):
    for e in c:
        dt = e.dxftype()
        if dt in ("TEXT", "MTEXT"):
            yield e
        elif dt == "INSERT" and depth < 4:
            yield from _iter(e.virtual_entities(), depth + 1)


def load_cells(dxf):
    d = ezdxf.readfile(str(dxf))
    out = []
    for e in _iter(d.modelspace()):
        if not hasattr(e.dxf, "insert"):
            continue
        t = clean(e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text)
        if t:
            out.append((round(e.dxf.insert.x, 1), round(e.dxf.insert.y, 1), t))
    return out


def cell_at(cells, cx, cy, xw=22, yw=7):
    best, bd = "", 1e9
    for x, y, t in cells:
        if abs(x - cx) < xw and abs(y - cy) < yw:
            dd = abs(x - cx) + abs(y - cy) * 3
            if dd < bd:
                best, bd = t, dd
    return best


def _num_in(txt):                       # '7.5"' / '10"' -> feet
    return float(txt.replace('"', "").strip()) / 12.0


def _bar(size, sp):
    return f"{size}@{sp.replace(chr(34), '').strip()}"


def build_group(cells, rows, interior_in=None):
    """interior_in: callable span_ft -> interior wall inches, or None (uniform)."""
    cover_ys = sorted({y for x, y, t in cells if t == "MAXIMUM EARTH COVER"},
                      reverse=True)
    group = {}
    for cover_y in cover_ys:
        xs = sorted({x for x, y, t in cells                    # de-dup doubled x
                     if abs(y - cover_y) < 4 and t in ("10'", "20'")})
        col = {name: [cell_at(cells, cx, cover_y + dy) for cx in xs]
               for name, dy in rows}
        covers = [cell_at(cells, cx, cover_y) for cx in xs]
        span_lbls = [t.replace("'", "") for x, y, t in
                     sorted(c for c in cells if abs(c[1] - (cover_y + 31)) < 5
                            and c[2].endswith("'"))]
        span_seq, seen = [], set()
        for v in span_lbls:
            if v not in seen:
                span_seq.append(v)
                seen.add(v)
        gidx, prev_h = -1, None
        for i, hs in enumerate(col["HEIGHT"]):
            h = hs.replace("'", "")
            if not h:
                continue
            if prev_h is None or float(h) < float(prev_h):     # new span group
                gidx += 1
            prev_h = h
            span = span_seq[gidx]
            key = f"{span}x{h}"
            cov = int(covers[i].replace("'", ""))
            entry = {
                "wall_t_ft": round(_num_in(col["WALLS"][i]), 4),
                "top_slab_ft": round(_num_in(col["ROOF"][i]), 4),
                "bot_slab_ft": round(_num_in(col["INVERT"][i]), 4),
                "a": _bar(col["a_size"][i], col["a_sp"][i]),
                "b": _bar(col["b_size"][i], col["b_sp"][i]),
                "e": _bar(col["e_size"][i], col["e_sp"][i]),
                "conc_cf_lf": float(col["CONC"][i]),
                "lb_per_lf": int(float(col["REINF"][i])),
            }
            if interior_in is not None:
                entry["interior_wall_t_ft"] = round(interior_in(float(span)) / 12.0, 4)
            group.setdefault(key, {"covers": {}})["covers"][cov] = entry
    return group


def validate(group, cells_n, tol):
    bad = []
    tbl = {"single" if cells_n == 1 else "double": group}
    for key, row in group.items():
        s, h = (float(v) for v in key.split("x"))
        for cov in row["covers"]:
            sec = BoxCulvertSection(cells_n, s, h, float(cov), tbl)
            if abs(sec.area_sf() - sec.conc_cf_lf) > tol:
                bad.append((key, cov, round(sec.area_sf(), 2), sec.conc_cf_lf))
    return bad


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    d80, d81, out = Path(argv[1]), Path(argv[2]), Path(argv[3])
    single = build_group(load_cells(d80), ROWS_D80)
    double = build_group(load_cells(d81), ROWS_D81,
                         interior_in=lambda s: 6.0 if s <= 8 else 8.0)
    bad_s = validate(single, 1, tol=0.15)
    bad_d = validate(double, 2, tol=1.5)
    print(f"single rows: {len(single)}  area!=conc (>0.15): {len(bad_s)}")
    print(f"double rows: {len(double)}  area!=conc (>1.5): {len(bad_d)}")
    for tag, bad in (("single", bad_s), ("double", bad_d)):
        for b in bad[:20]:
            print(f"  {tag}", b)
    if bad_s or bad_d:
        return 1
    if "--write" in argv:
        out.write_text(yaml.safe_dump({"single": single, "double": double},
                                      sort_keys=True), encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
