"""Rates: the library labour, equipment and material rates the payload
references. Read-only; the lookup source for crew members' library rates."""
from __future__ import annotations

from estimating_tools.heavycivil.columns import RT
from estimating_tools.heavycivil.sheets.common import apply_freeze_and_print, factory, put

_TITLES = {"labor": "Labor rates", "equipment": "Equipment rates", "material": "Material costs"}


def write_rates(ws, plan, wb, style):
    sf = factory(style)
    conf = style.sheets["rates"]
    ws.sheet_properties.tabColor = conf.get("tab_color")
    apply_freeze_and_print(ws, conf)
    for letter, key in ((RT.ID, "id"), (RT.NAME, "name"), (RT.UNIT, "unit"), (RT.RATE, "rate")):
        width = style.column("rates", key).get("width")
        if width:
            ws.column_dimensions[letter].width = width
    for r in plan.rates:
        if r.kind == "RATE_TITLE":
            put(ws, sf, f"{RT.ID}{r.row}", _TITLES[r.id], "label_bold")
        elif r.kind == "RATE_HEAD":
            for letter, key in ((RT.ID, "id"), (RT.NAME, "name"), (RT.UNIT, "unit"),
                                (RT.RATE, "rate")):
                put(ws, sf, f"{letter}{r.row}", style.column("rates", key)["heading"], "head")
        else:
            rate = r.obj
            put(ws, sf, f"{RT.ID}{r.row}", rate.id, "label")
            put(ws, sf, f"{RT.NAME}{r.row}", rate.name, "label")
            put(ws, sf, f"{RT.UNIT}{r.row}", rate.unit, "calc_text")
            put(ws, sf, f"{RT.RATE}{r.row}", rate.rate, "calc_rate")
