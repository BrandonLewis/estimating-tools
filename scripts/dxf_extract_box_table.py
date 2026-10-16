"""Grid-extract a Caltrans D80/D81 box-culvert dimension+reinforcement table.

The table is column-major by (SPAN x HEIGHT x MAX-COVER); each column carries
ROOF/WALLS/INVERT thicknesses, a/b/e bar size+spacing, DIM B, CONCRETE CF/LF,
REINFORCEMENT LB/LF, soil pressures. Cells are individual TEXT/MTEXT entities;
we snap them to a grid of column x-centres (from the MAX-EARTH-COVER row) and
row y-bands (from the left-hand row labels). Fraction glyph 0x81 -> .5.

    python scripts/dxf_extract_box_table.py <dxf>
"""
import sys
import ezdxf
from ezdxf.tools.text import plain_text


def clean(s: str) -> str:
    return (plain_text(s).replace("%%u", "").replace("%%U", "")
            .replace("\x81", ".5").replace("\n", " ").strip())


def it(c, depth=0):
    for e in c:
        dt = e.dxftype()
        if dt in ("TEXT", "MTEXT"):
            yield e
        elif dt == "INSERT" and depth < 4:
            yield from it(e.virtual_entities(), depth + 1)


d = ezdxf.readfile(sys.argv[1])
cells = []
for e in it(d.modelspace()):
    if not hasattr(e.dxf, "insert"):
        continue
    t = clean(e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text)
    if t:
        cells.append((round(e.dxf.insert.x, 1), round(e.dxf.insert.y, 1), t))

# Each of the two size ranges is a separate table block; split by the two
# "MAXIMUM EARTH COVER" label rows (their y anchors the column grid).
cover_label_ys = sorted((y for x, y, t in cells if t == "MAXIMUM EARTH COVER"),
                        reverse=True)

# dy measured from the MAXIMUM-EARTH-COVER row (calibrated off one column)
ROWS = [("SPAN", 31), ("HEIGHT", 16), ("COVER", 0), ("ROOF", -14.4),
        ("WALLS", -28.6), ("INVERT", -43.4), ("a_size", -57.3), ("a_sp", -71.6),
        ("b_size", -85.7), ("b_sp", -99.7), ("e_size", -113.7), ("e_sp", -128.8),
        ("DIMB", -140.4), ("CONC_cflf", -161.1), ("REINF_lblf", -178.3)]


def col_centres(cover_y):
    xs = sorted(x for x, y, t in cells
                if abs(y - cover_y) < 4 and t in ("10'", "20'"))
    return xs


def cell_at(cx, cy, xw=22, yw=7):
    best, bd = "", 1e9
    for x, y, t in cells:
        if abs(x - cx) < xw and abs(y - cy) < yw:
            dd = abs(x - cx) + abs(y - cy) * 3
            if dd < bd:
                best, bd = t, dd
    return best


for ti, cover_y in enumerate(cover_label_ys):
    xs = col_centres(cover_y)
    print(f"\n===== BOX-CULVERT TABLE {ti}  ({len(xs)} columns) top row y={cover_y} =====")
    grid = {}
    for name, dy in ROWS:
        grid[name] = [cell_at(cx, cover_y + dy) for cx in xs]
    # header rows span/height are wider-pitched; read them per column too
    for name in ("SPAN", "HEIGHT", "COVER", "ROOF", "WALLS", "INVERT",
                 "a_size", "a_sp", "b_size", "b_sp", "e_size", "e_sp",
                 "DIMB", "CONC_cflf", "REINF_lblf"):
        print(f"  {name:11s}: " + " ".join(f"{v:>6}" for v in grid[name]))
