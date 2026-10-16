"""Coverage join + board rendering (estimating_tools.quotespace.coverage)."""
from estimating_tools.quotespace.coverage import build_coverage, render_coverage_md
from estimating_tools.quotespace.model import SolicitationRecord

PACKAGES = [
    {"name": "Structural Concrete", "strategy": "sub_out",
     "items": [{"schedule": "A", "item_number": "23", "description": "Str Conc"},
               {"schedule": "A", "item_number": "24", "description": "Rebar"}]},
    {"name": "Earthwork", "strategy": "self_perform",
     "items": [{"schedule": "A", "item_number": "10", "description": "Excavation"}]},
    {"name": "Guardrail", "strategy": "sub_out",
     "items": [{"schedule": "A", "item_number": "40", "description": "MGS"}]},
]


def _sent(vendor, items=None, status="sent"):
    return SolicitationRecord(
        work_package={"name": "Structural Concrete"},
        vendor={"org_name": vendor},
        items=items if items is not None else [],
        status=status, sent_at="2026-08-07" if status == "sent" else "")


def test_ladder_rungs():
    records = [_sent("ACME Rebar"), _sent("Basalt Steel")]
    quotes = [{"vendor_name": "Basalt Steel",
               "work_package_name": "Structural Concrete"}]
    allocations = [{"vendor_name": "Basalt Steel",
                    "schedule": "A", "item_number": "24"}]
    cov = build_coverage(records, PACKAGES, quotes=quotes,
                         allocations=allocations,
                         leveled=["Structural Concrete"])
    sc = next(p for p in cov["packages"] if p["name"] == "Structural Concrete")
    cells = {(i["key"], v): s for i in sc["items"]
             for v, s in i["cells"].items()}
    assert cells[("A::23", "ACME Rebar")] == "solicited"
    assert cells[("A::23", "Basalt Steel")] == "leveled"    # quoted + pkg leveled
    assert cells[("A::24", "Basalt Steel")] == "awarded"    # allocation wins


def test_declined_and_empty_items_covers_whole_package():
    records = [_sent("ACME Rebar", status="declined")]
    cov = build_coverage(records, PACKAGES)
    sc = next(p for p in cov["packages"] if p["name"] == "Structural Concrete")
    for item in sc["items"]:
        assert item["cells"]["ACME Rebar"] == "declined"


def test_item_scoped_solicitation_only_marks_its_items():
    records = [_sent("ACME Rebar", items=[{"schedule": "A", "item_number": "23"}])]
    cov = build_coverage(records, PACKAGES)
    sc = next(p for p in cov["packages"] if p["name"] == "Structural Concrete")
    by_key = {i["key"]: i for i in sc["items"]}
    assert by_key["A::23"]["cells"]["ACME Rebar"] == "solicited"
    assert "ACME Rebar" not in by_key["A::24"]["cells"]


def test_item_key_whitespace_is_stripped():
    # A journal record whose item keys carry stray whitespace still lands on
    # the package's A::23 cell instead of orphaning on " A ::23 ".
    records = [_sent("ACME Rebar", items=[{"schedule": " A ", "item_number": "23 "}])]
    cov = build_coverage(records, PACKAGES)
    sc = next(p for p in cov["packages"] if p["name"] == "Structural Concrete")
    by_key = {i["key"]: i for i in sc["items"]}
    assert by_key["A::23"]["cells"]["ACME Rebar"] == "solicited"


def test_gap_list_flags_unsolicited_sub_out_items_only():
    records = [_sent("ACME Rebar")]        # covers Structural Concrete only
    cov = build_coverage(records, PACKAGES)
    gap_keys = {g["key"] for g in cov["gap_items"]}
    assert gap_keys == {"A::40"}           # Guardrail uncovered; Earthwork is self_perform


def test_vendor_summary_counts():
    records = [_sent("ACME Rebar"), _sent("Basalt Steel", status="declined")]
    quotes = [{"vendor_name": "ACME Rebar",
               "work_package_name": "Structural Concrete"}]
    cov = build_coverage(records, PACKAGES, quotes=quotes)
    summary = {v["vendor"]: v for v in cov["vendor_summary"]}
    assert summary["ACME Rebar"] == {"vendor": "ACME Rebar", "solicited": 1,
                                     "received": 1, "declined": 0}
    assert summary["Basalt Steel"]["declined"] == 1


def test_received_without_solicitation_still_shows():
    # A vendor who quoted unasked appears as received.
    quotes = [{"vendor_name": "Walk-in Sub",
               "work_package_name": "Structural Concrete"}]
    cov = build_coverage([], PACKAGES, quotes=quotes)
    sc = next(p for p in cov["packages"] if p["name"] == "Structural Concrete")
    assert sc["items"][0]["cells"]["Walk-in Sub"] == "received"


def test_vendor_names_join_case_insensitively():
    # Journal spelling vs BM export spelling must land in ONE column.
    records = [_sent("ACME Rebar")]
    quotes = [{"vendor_name": "acme rebar",
               "work_package_name": "Structural Concrete"}]
    cov = build_coverage(records, PACKAGES, quotes=quotes)
    sc = next(p for p in cov["packages"] if p["name"] == "Structural Concrete")
    for item in sc["items"]:
        assert list(item["cells"]) == ["ACME Rebar"]  # first-seen display name
        assert item["cells"]["ACME Rebar"] == "received"
    assert [v["vendor"] for v in cov["vendor_summary"]] == ["ACME Rebar"]


def test_declined_vendor_who_quoted_anyway_shows_received():
    records = [_sent("ACME Rebar", status="declined")]
    quotes = [{"vendor_name": "ACME Rebar",
               "work_package_name": "Structural Concrete"}]
    cov = build_coverage(records, PACKAGES, quotes=quotes)
    sc = next(p for p in cov["packages"] if p["name"] == "Structural Concrete")
    for item in sc["items"]:
        assert item["cells"]["ACME Rebar"] == "received"
    summary = {v["vendor"]: v for v in cov["vendor_summary"]}
    assert summary["ACME Rebar"]["declined"] == 1
    assert summary["ACME Rebar"]["received"] == 1


def test_render_board_markdown():
    records = [_sent("ACME Rebar")]
    md = render_coverage_md(build_coverage(records, PACKAGES))
    assert "## Structural Concrete" in md
    assert "| A::23 |" in md and "solicited" in md
    assert "## Coverage gaps" in md and "A::40" in md


def test_render_escapes_pipes_in_descriptions():
    pkgs = [{"name": "Guardrail", "strategy": "sub_out",
             "items": [{"schedule": "A", "item_number": "40",
                        "description": "Guard | rail"}]}]
    records = [SolicitationRecord(work_package={"name": "Guardrail"},
                                  vendor={"org_name": "V"},
                                  status="sent", sent_at="2026-08-07")]
    md = render_coverage_md(build_coverage(records, pkgs))
    assert "Guard \\| rail" in md          # cell escaped, row not broken
    assert "| Guard | rail |" not in md
