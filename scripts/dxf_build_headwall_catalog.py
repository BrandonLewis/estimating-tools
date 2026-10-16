"""Build + validate the git-ignored D89 pipe-headwall design-H catalog.

The "REINFORCED CONCRETE HEADWALL" table stores one multi-line MTEXT per column
(B3-wall lineage); each column's lines are, in order:

    H, T, W, C, B, F, "c" bar, "d" bar, Conc CY/LF, Reinf LB/LF, <case>, <case>

We read those column MTEXTs (all sharing a table row y), parse the fields, and
gate every row on `W == C + B` and `T*(H+1)+W*F ~= Conc_CY_LF*27` (the section
concrete incl. the 1'-0" stem extension). Emits:

    headwall:
      "3-11": {T_ft, W_ft, C_ft, B_ft, F_ft, c, d, conc_cy_lf, reinf_lb_lf}

    python scripts/dxf_build_headwall_catalog.py <d089a.dxf> <out.yaml> [--write]
"""
import re
import sys
from pathlib import Path

import ezdxf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "bimforge"))
from bimforge.author.headwall_section import HeadwallSection, _parse_h_key  # noqa: E402

TABLE_ROW_Y = -191.3        # y of the design-H table's column MTEXTs on D89A
FIELDS = ("H", "T", "W", "C", "B", "F", "c", "d", "conc", "reinf")


def _iter(c, depth=0):
    for e in c:
        dt = e.dxftype()
        if dt in ("TEXT", "MTEXT"):
            yield e
        elif dt == "INSERT" and depth < 5:
            try:
                ves = list(e.virtual_entities())
            except Exception:
                ves = []
            yield from _iter(ves, depth + 1)


def _ft(s: str) -> float:
    """'3'-11"' / '10"' / '1'-0"' -> feet."""
    s = s.replace("\x81", ".5").strip()
    m = re.fullmatch(r"(?:(\d+)'-)?(\d+(?:\.\d+)?)\"?", s)
    if not m:
        raise ValueError(f"unparseable dim {s!r}")
    ft = float(m.group(1)) if m.group(1) else 0.0
    inch = float(m.group(2))
    if m.group(1) is None:            # bare number is inches (e.g. 10")
        return inch / 12.0
    return ft + inch / 12.0


def _h_key(s: str) -> str:
    s = s.replace("\x81", ".5").strip().rstrip('"')
    f, i = s.split("'-")
    return f"{int(f)}-{i}"


def _bar(s: str) -> str:
    return s.replace("\x81", ".5").replace(" ", "").strip()


def load_columns(dxf):
    d = ezdxf.readfile(str(dxf))
    cols = []
    for e in _iter(d.modelspace()):
        if e.dxftype() != "MTEXT" or not hasattr(e.dxf, "insert"):
            continue
        if abs(e.dxf.insert.y - TABLE_ROW_Y) > 5:
            continue
        try:
            lines = [ln for ln in e.plain_text(split=True) if ln.strip()]
        except Exception:
            continue
        if len(lines) >= 10 and "'-" in lines[0]:
            cols.append((round(e.dxf.insert.x, 1), lines))
    cols.sort()
    return cols


def build_group(cols):
    group = {}
    for _x, lines in cols:
        key = _h_key(lines[0])
        group[key] = {
            "T_ft": round(_ft(lines[1]), 4),
            "W_ft": round(_ft(lines[2]), 4),
            "C_ft": round(_ft(lines[3]), 4),
            "B_ft": round(_ft(lines[4]), 4),
            "F_ft": round(_ft(lines[5]), 4),
            "c": _bar(lines[6]),
            "d": _bar(lines[7]),
            "conc_cy_lf": float(lines[8].strip()),
            "reinf_lb_lf": int(float(lines[9].strip())),
        }
    return group


def validate(group):
    bad = []
    tbl = {"headwall": group}
    for key, row in group.items():
        if abs(row["W_ft"] - (row["C_ft"] + row["B_ft"])) > 0.02:
            bad.append((key, "W!=C+B", row["W_ft"], row["C_ft"] + row["B_ft"]))
        sec = HeadwallSection(_parse_h_key(key), tbl)
        if abs(sec.section_area_sf - row["conc_cy_lf"] * 27.0) > 0.2:
            bad.append((key, "area!=conc*27",
                        round(sec.section_area_sf, 2), row["conc_cy_lf"] * 27.0))
    return bad


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    dxf, out = Path(argv[1]), Path(argv[2])
    group = build_group(load_columns(dxf))
    bad = validate(group)
    print(f"headwall rows: {len(group)}   validation failures: {len(bad)}")
    for b in bad[:20]:
        print("  ", b)
    if bad:
        return 1
    if "--write" in argv:
        out.write_text(yaml.safe_dump({"headwall": group}, sort_keys=True),
                       encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
