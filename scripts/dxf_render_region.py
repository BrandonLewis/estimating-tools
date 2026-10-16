"""Render an explicit modelspace rectangle of a DXF to PNG at high DPI.

    python render_region.py <dxf> <out.png> <xmin> <ymin> <xmax> <ymax> [dpi]
"""
import sys
import matplotlib; matplotlib.use("Agg")
import ezdxf, matplotlib.pyplot as plt
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

dxf, out = sys.argv[1], sys.argv[2]
xmin, ymin, xmax, ymax = map(float, sys.argv[3:7])
dpi = int(sys.argv[7]) if len(sys.argv) > 7 else 200

d = ezdxf.readfile(dxf); msp = d.modelspace()

# MULTILEADER entities with a zero-length dogleg crash the drawing frontend
# (ZeroDivisionError in normalize); they are annotation, so purge them from
# modelspace and every block definition before rendering the geometry.
for layout in (msp, *(d.blocks[b.name] for b in d.blocks)):
    for ml in list(layout.query("MULTILEADER MLEADER")):
        try:
            layout.delete_entity(ml)
        except Exception:
            pass

w = (xmax - xmin); h = (ymax - ymin)
fig, ax = plt.subplots(figsize=(min(40, w / 12 + 6), min(30, h / 12 + 4)))
Frontend(RenderContext(d), MatplotlibBackend(ax)).draw_layout(msp)
ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax); ax.set_axis_off()
fig.patch.set_facecolor("white"); ax.set_facecolor("white")
fig.savefig(out, dpi=dpi, bbox_inches="tight", facecolor="white")
print("saved", out)
