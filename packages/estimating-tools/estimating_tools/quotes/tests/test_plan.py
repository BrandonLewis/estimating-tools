from estimating_tools.quotes.model import CanonicalQuote, QuoteLine
from estimating_tools.quotes.plan import QuotePlan, plan_quote


def _sample() -> CanonicalQuote:
    return CanonicalQuote(
        vendor_name="Acme Striping",
        work_package_name="Striping",
        amount=125000.0,
        is_dbe=True,
        lines=[
            QuoteLine(schedule_name="Base Bid", item_number="40", unit_price=2.5, quantity=1000.0),
            QuoteLine(schedule_name="Base Bid", item_number="41", amount=8000.0),
            # excluded line (vendor not bidding it)
            QuoteLine(schedule_name="Base Bid", item_number="42", is_included=False,
                      exclusion_notes="not in our scope"),
            # same item_number, different schedule -> kept distinct
            QuoteLine(schedule_name="Additive Alt 1", item_number="40", unit_price=3.1),
        ],
    )


def test_quote_header_omits_none_optionals_keeps_vendor_and_dbe():
    plan = plan_quote(_sample())
    assert isinstance(plan, QuotePlan)
    assert plan.work_package_name == "Striping"
    assert plan.quote_header == {"vendor_name": "Acme Striping", "amount": 125000.0, "is_dbe": True}
    # no vendor_id / notes / contact_info keys (they were None)
    assert "vendor_id" not in plan.quote_header and "notes" not in plan.quote_header


def test_quote_header_threads_vendor_id_when_set():
    q = CanonicalQuote(vendor_name="Acme Striping", work_package_name="Striping",
                       vendor_id=42, is_dbe=True)
    header = plan_quote(q).quote_header
    assert header["vendor_id"] == 42
    assert header["vendor_name"] == "Acme Striping" and header["is_dbe"] is True


def test_bid_item_refs_distinct_first_seen():
    plan = plan_quote(_sample())
    assert plan.bid_item_refs == [
        {"schedule_name": "Base Bid", "item_number": "40"},
        {"schedule_name": "Base Bid", "item_number": "41"},
        {"schedule_name": "Base Bid", "item_number": "42"},
        {"schedule_name": "Additive Alt 1", "item_number": "40"},
    ]


def test_lines_carry_price_inclusion_and_schedule():
    plan = plan_quote(_sample())
    # all 4 lines emitted, including the excluded one
    assert [(l["schedule_name"], l["item_number"], l["is_included"]) for l in plan.lines] == [
        ("Base Bid", "40", True),
        ("Base Bid", "41", True),
        ("Base Bid", "42", False),
        ("Additive Alt 1", "40", True),
    ]
    assert plan.lines[0]["unit_price"] == 2.5 and plan.lines[0]["quantity"] == 1000.0
    assert plan.lines[1]["amount"] == 8000.0
    assert plan.lines[2]["exclusion_notes"] == "not in our scope"


def test_optional_line_fields_omitted_when_none():
    plan = plan_quote(_sample())
    # line 0 has unit_price+quantity but no amount/exclusion_notes -> those keys absent
    assert "amount" not in plan.lines[0] and "exclusion_notes" not in plan.lines[0]


# ---- alternate lines (BidManager #1486 A2) ----


def test_alternate_line_both_included_and_alternate_coerces_is_included_false():
    # is_alternate wins: the payload is always is_included=False, is_alternate=True,
    # even when the extracted line set is_included=True by mistake.
    q = CanonicalQuote(
        vendor_name="Acme Striping", work_package_name="Striping",
        lines=[QuoteLine(schedule_name="Base Bid", item_number="50",
                         unit_price=4.0, is_included=True, is_alternate=True)],
    )
    plan = plan_quote(q)
    assert plan.lines[0]["is_included"] is False
    assert plan.lines[0]["is_alternate"] is True


def test_alternate_line_payload_sends_not_included_and_alternate():
    q = CanonicalQuote(
        vendor_name="Acme Striping", work_package_name="Striping",
        lines=[QuoteLine(schedule_name="Base Bid", item_number="50",
                         unit_price=4.0, is_included=False, is_alternate=True)],
    )
    plan = plan_quote(q)
    assert plan.lines[0]["is_included"] is False
    assert plan.lines[0]["is_alternate"] is True


def test_ordinary_line_payload_omits_is_alternate_key():
    # payloads for ordinary (non-alternate) lines are unchanged: no is_alternate key
    plan = plan_quote(_sample())
    for line in plan.lines:
        assert "is_alternate" not in line


# ---- render_quote_plan tests (Phase 3) ----

from estimating_tools.quotes.plan import QuotePlan, render_quote_plan


def test_render_quote_plan_shape():
    plan = QuotePlan(
        work_package_name="Concrete Package",
        quote_header={"vendor_name": "ACME Concrete", "is_dbe": False, "amount": 45250.00},
        bid_item_refs=[{"schedule_name": "Base Bid", "item_number": "10"}],
        lines=[{"schedule_name": "Base Bid", "item_number": "10", "is_included": True,
                "unit_price": 175.00, "quantity": 258.0}],
    )
    out = render_quote_plan(plan)
    assert out.startswith("# Quote plan\n\n")
    assert "1 line item across 1 bid item" in out
    assert "\n## Work package + quote header\n\n" in out
    assert "\n## Bid item refs\n\n" in out
    assert "\n## Line items\n\n" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")
    assert "175.00" in out                                        # format_money used
    assert "ACME Concrete" in out


def test_render_quote_plan_empty():
    plan = QuotePlan()
    out = render_quote_plan(plan)
    assert out.startswith("# Quote plan\n\n")
    assert "0 line items across 0 bid items" in out
    assert out.endswith("Confirm to write to BidSheet.ai.")


def test_render_quote_plan_escapes_pipe():
    plan = QuotePlan(work_package_name="wp|1")
    out = render_quote_plan(plan)
    assert "wp\\|1" in out


def test_render_quote_plan_marks_alternate_line():
    plan = QuotePlan(
        work_package_name="Concrete Package",
        quote_header={"vendor_name": "ACME Concrete", "is_dbe": False},
        bid_item_refs=[{"schedule_name": "Base Bid", "item_number": "10"}],
        lines=[{"schedule_name": "Base Bid", "item_number": "10", "is_included": False,
                "is_alternate": True, "unit_price": 175.00, "quantity": 258.0}],
    )
    out = render_quote_plan(plan)
    assert "is_alternate" in out
    assert "True" in out


def test_render_quote_plan_ordinary_line_shows_alternate_false():
    plan = QuotePlan(
        lines=[{"schedule_name": "Base Bid", "item_number": "10", "is_included": True}],
    )
    out = render_quote_plan(plan)
    assert "False" in out


def test_two_lines_on_one_bid_item_sum_into_one_amount():
    q = CanonicalQuote(vendor_name="V", work_package_name="P", lines=[
        QuoteLine(schedule_name="Base", item_number="61", unit_price=2.0, quantity=100.0),
        QuoteLine(schedule_name="Base", item_number="61", amount=50.0),
        QuoteLine(schedule_name="Base", item_number="61", is_included=False),
        QuoteLine(schedule_name="Base", item_number="62", unit_price=3.0),
    ])
    plan = plan_quote(q)
    assert plan.bid_item_refs == [{"schedule_name": "Base", "item_number": "61"},
                                  {"schedule_name": "Base", "item_number": "62"}]
    assert plan.lines == [
        {"schedule_name": "Base", "item_number": "61", "is_included": True, "amount": 250.0},
        {"schedule_name": "Base", "item_number": "62", "is_included": True, "unit_price": 3.0},
    ]


def test_combining_base_and_alternate_lines_refuses_instead_of_dropping_the_alternate():
    import pytest
    quote = CanonicalQuote(vendor_name="Vendor", work_package_name="Package", lines=[
        QuoteLine(schedule_name="Base", item_number="1", amount=100),
        QuoteLine(schedule_name="Base", item_number="1", amount=50, is_alternate=True),
    ])
    with pytest.raises(ValueError, match="cannot combine base and alternate"):
        plan_quote(quote)


def test_combining_alternates_retains_their_prices():
    quote = CanonicalQuote(vendor_name="Vendor", work_package_name="Package", lines=[
        QuoteLine(schedule_name="Base", item_number="1", amount=100, is_alternate=True),
        QuoteLine(schedule_name="Base", item_number="1", unit_price=5, quantity=10,
                  is_alternate=True),
    ])
    (line,) = plan_quote(quote).lines
    assert line["is_alternate"] is True and line["is_included"] is False
    assert line["amount"] == 150


def test_combining_lines_refuses_a_partially_unextended_price():
    import pytest
    quote = CanonicalQuote(vendor_name="Vendor", work_package_name="Package", lines=[
        QuoteLine(schedule_name="Base", item_number="1", amount=100),
        QuoteLine(schedule_name="Base", item_number="1", unit_price=5),
    ])
    with pytest.raises(ValueError, match="needs an amount or quantity"):
        plan_quote(quote)
