"""Dump every TEXT/MTEXT entity (exploding block INSERTs) with position.

    python dump_text.py <dxf> [--multi]   # --multi shows per-line MTEXT split

Prints (x, y, text) sorted top-down then left-right, so table structure is
visible. Use to reverse-engineer a sheet's table layout before coding an
extractor path.
"""
import sys, re
import ezdxf
from ezdxf.tools.text import plain_text

MULTI = "--multi" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]


def clean(s):
    return plain_text(s).replace("%%u", "").replace("%%U", "").replace("%%d", "deg").strip()


def iter_e(container, depth=0):
    for e in container:
        dt = e.dxftype()
        if dt in ("TEXT", "MTEXT"):
            yield e
        elif dt == "INSERT" and depth < 4:
            yield from iter_e(e.virtual_entities(), depth + 1)


d = ezdxf.readfile(args[0])
rows = []
for e in iter_e(d.modelspace()):
    if not hasattr(e.dxf, "insert"):
        continue
    p = e.dxf.insert
    if e.dxftype() == "MTEXT":
        raw = e.plain_text(split=True) if MULTI else [e.plain_text().replace("\n", " | ")]
    else:
        raw = [e.dxf.text]
    for i, ln in enumerate(raw):
        t = clean(ln)
        if t:
            rows.append((round(p.y, 1), round(p.x, 1), t, "M" if e.dxftype() == "MTEXT" else "T", i))

rows.sort(key=lambda r: (-r[0], r[1]))
for y, x, t, k, i in rows:
    print(f"y={y:9.1f} x={x:9.1f} [{k}{i}] {t!r}")
