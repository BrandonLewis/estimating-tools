"""ITB markdown rendering (estimating_tools.quotespace.itb)."""
from estimating_tools.quotespace.itb import render_itb, vendor_slug

ITEMS = [
    {"schedule": "A", "item_number": "23",
     "description": "Structural Concrete, Bridge", "quantity": 210.0, "unit": "CY"},
    {"schedule": "A", "item_number": "24",
     "description": "Bar Reinforcing Steel", "quantity": 41500.0, "unit": "LB"},
]


def test_vendor_slug_is_filename_safe():
    assert vendor_slug("ACME Rebar & Sons, Inc.") == "acme-rebar-sons-inc"
    assert vendor_slug("  Basalt  Steel ") == "basalt-steel"


def test_vendor_slug_never_empty():
    # No ASCII alnum at all must not slug to "" (would write a hidden ".md").
    assert vendor_slug("!!!") == "vendor"
    assert vendor_slug("") == "vendor"


def test_render_contains_the_essentials():
    md = render_itb(
        project_name="Hwy 41 Culvert", package_name="Structural Concrete",
        vendor_name="ACME Rebar", contacts=["joe@acmerebar.com"],
        items=ITEMS, scope="Two headwalls per briefing.",
        letterhead="# Example Road Constructors", respond_by="2026-08-14")
    assert md.startswith("# Example Road Constructors")
    assert "Invitation to Bid" in md
    assert "Structural Concrete" in md and "Hwy 41 Culvert" in md
    assert "ACME Rebar" in md and "joe@acmerebar.com" in md
    assert "2026-08-14" in md
    assert "Two headwalls per briefing." in md
    # items table: header + both rows, quantities formatted plainly
    assert "| A | 23 | Structural Concrete, Bridge | 210 | CY |" in md
    assert "| A | 24 | Bar Reinforcing Steel | 41500 | LB |" in md


def test_pipe_in_cell_value_is_escaped():
    md = render_itb(project_name="P", package_name="W", vendor_name="V",
                    contacts=[], items=[{"schedule": "A", "item_number": "40",
                                         "description": "Guard | rail",
                                         "quantity": 100.0, "unit": "LF"}])
    assert "Guard \\| rail" in md          # cell escaped, row not broken
    assert "| Guard | rail |" not in md


def test_string_quantity_is_coerced():
    md = render_itb(project_name="P", package_name="W", vendor_name="V",
                    contacts=[], items=[{"schedule": "A", "item_number": "23",
                                         "description": "Str Conc",
                                         "quantity": "210", "unit": "CY"}])
    assert "| 210 | CY |" in md


def test_render_without_letterhead_or_scope_still_valid():
    md = render_itb(project_name="P", package_name="W", vendor_name="V",
                    contacts=[], items=ITEMS)
    assert md.lstrip().startswith("# Invitation to Bid")
    assert "Scope" not in md          # empty scope section omitted
    assert "Respond by" not in md     # no respond_by given
