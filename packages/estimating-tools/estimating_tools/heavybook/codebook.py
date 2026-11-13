"""What a book the retired code writers built (pack version 1) looks like:
the constants HeavyBook's support for such books still needs -- its stamp's
layout version (``pack.detect``), the declaration a layout-2 or step-2a
stamp is upgraded to (``declaration.generate``), its Checks rows
(``refresh``, ``legacy_checks``). Nothing here builds a book."""
from __future__ import annotations

LAYOUT_VERSION = 3
HEADER_ROW = 4
FIRST_ROW = 5
TEMPLATE_NAMES = {"activity": "hc.tpl.activity", "stepped": "hc.tpl.stepped",
                  "resource": "hc.tpl.resource", "step": "hc.tpl.step",
                  "member": "hc.tpl.member"}
#: Checks statuses by what Estimate Navigator shows, matched on the status's
#: first word (``CHANGED -- re-export to reweight`` is a fail).
NAVIGATOR_STATUSES = {"pass": ["OK"], "fail": ["DIFF", "CHANGED"], "info": ["export"]}
#: Per sheet, the row kinds whose owner tag is a formula (the id at the row
#: the sheet's owner-row helper names), never a stored id.
DERIVED = {"cost_report": ("STEP", "RESOURCE", "STEPS", "START", "END"),
           "crews": ("MEMBER", "NOTE", "CREW_END")}
END_CUE = "insert lines above"
CREW_END_CUE = "insert members above"
LIBRARY_BANNER = "Library crew -- an edit copies it into this estimate."
RATE_TITLES = {"labor": "Labor rates", "equipment": "Equipment rates",
               "material": "Material costs"}
