from estimating_tools.quotes.revision import QuoteLineDiff, diff_quote_lines


def _existing():
    # current revision's lines (decimal fields as strings, like the MCP returns)
    return [
        {"id": 1001, "work_package_item_id": 11, "unit_price": "10", "quantity": "100", "amount": "1000", "is_included": True, "exclusion_notes": ""},
        {"id": 1002, "work_package_item_id": 12, "unit_price": "20", "quantity": "50", "amount": "1000", "is_included": True, "exclusion_notes": ""},
    ]


def test_identical_capture_is_unchanged_noop():
    # planned equals existing (string "10" vs float 10.0 must NOT count as a change)
    planned = [
        {"work_package_item_id": 11, "unit_price": 10.0, "quantity": 100.0, "amount": 1000.0, "is_included": True, "exclusion_notes": ""},
        {"work_package_item_id": 12, "unit_price": 20.0, "quantity": 50.0, "amount": 1000.0, "is_included": True, "exclusion_notes": ""},
    ]
    d = diff_quote_lines(planned, _existing())
    assert isinstance(d, QuoteLineDiff)
    assert d.unchanged is True and d.changed == [] and d.added == []


def test_changed_unit_price_is_a_change_carrying_existing_id():
    planned = [
        {"work_package_item_id": 11, "unit_price": 9.0, "quantity": 100.0, "amount": 900.0, "is_included": True, "exclusion_notes": ""},
    ]
    d = diff_quote_lines(planned, _existing())
    assert d.unchanged is False
    assert len(d.changed) == 1 and d.added == []
    assert d.changed[0]["work_package_item_id"] == 11
    assert d.changed[0]["unit_price"] == 9.0
    assert d.changed[0]["existing_line_id"] == 1001          # so the skill can update it


def test_changed_inclusion_flag_is_a_change():
    planned = [
        {"work_package_item_id": 12, "unit_price": 20.0, "quantity": 50.0, "amount": 1000.0, "is_included": False, "exclusion_notes": "descoped"},
    ]
    d = diff_quote_lines(planned, _existing())
    assert d.unchanged is False and len(d.changed) == 1
    assert d.changed[0]["work_package_item_id"] == 12 and d.changed[0]["is_included"] is False


def test_added_line_has_no_existing_match():
    planned = [
        {"work_package_item_id": 99, "unit_price": 5.0, "quantity": 10.0, "amount": 50.0, "is_included": True, "exclusion_notes": ""},
    ]
    d = diff_quote_lines(planned, _existing())
    assert d.unchanged is False and d.changed == []
    assert len(d.added) == 1 and d.added[0]["work_package_item_id"] == 99


def test_existing_line_absent_from_planned_is_not_changed_or_added():
    # planned only touches item 11 (unchanged); item 12 exists but isn't planned -> not surfaced as change/add
    planned = [
        {"work_package_item_id": 11, "unit_price": 10.0, "quantity": 100.0, "amount": 1000.0, "is_included": True, "exclusion_notes": ""},
    ]
    d = diff_quote_lines(planned, _existing())
    assert d.changed == [] and d.added == []
    assert d.unchanged is True


def test_missing_or_none_fields_do_not_false_positive_a_change():
    # Existing line has "" exclusion_notes and string numerics; planned omits
    # exclusion_notes entirely (treated as "") and matches the numerics -> unchanged.
    existing = [
        {"id": 1001, "work_package_item_id": 11, "unit_price": "10", "quantity": "100", "amount": "1000", "is_included": True, "exclusion_notes": ""},
    ]
    planned = [
        # exclusion_notes key omitted (None) must equal existing ""; numerics equal
        {"work_package_item_id": 11, "unit_price": 10.0, "quantity": 100.0, "amount": 1000.0, "is_included": True},
    ]
    d = diff_quote_lines(planned, existing)
    assert d.unchanged is True and d.changed == [] and d.added == []

    # And an explicit None exclusion_notes vs existing "" is likewise unchanged.
    planned_none = [
        {"work_package_item_id": 11, "unit_price": 10.0, "quantity": 100.0, "amount": 1000.0, "is_included": True, "exclusion_notes": None},
    ]
    assert diff_quote_lines(planned_none, existing).unchanged is True


def test_planned_omitting_amount_vs_computed_existing_amount_is_noop():
    # The vendor gave a unit_price (no lump amount), so plan_quote omitted `amount`;
    # BidSheet.ai stored a COMPUTED amount on the line. An identical re-capture must be
    # a no-op, NOT a spurious revision.
    existing = [
        {"id": 1001, "work_package_item_id": 11, "unit_price": "10", "quantity": "100", "amount": "1000", "is_included": True, "exclusion_notes": ""},
    ]
    planned = [
        # amount key omitted entirely (as plan_quote does when amount is None)
        {"work_package_item_id": 11, "unit_price": 10.0, "quantity": 100.0, "is_included": True},
    ]
    d = diff_quote_lines(planned, existing)
    assert d.unchanged is True and d.changed == [] and d.added == []


def test_changed_amount_still_detected_when_planned_provides_it():
    # Guard against over-correction: when the capture DOES provide a differing amount, it is a change.
    existing = [
        {"id": 1001, "work_package_item_id": 11, "unit_price": "10", "quantity": "100", "amount": "1000", "is_included": True, "exclusion_notes": ""},
    ]
    planned = [
        {"work_package_item_id": 11, "unit_price": 10.0, "quantity": 100.0, "amount": 1200.0, "is_included": True},
    ]
    d = diff_quote_lines(planned, existing)
    assert d.unchanged is False and len(d.changed) == 1 and d.changed[0]["amount"] == 1200.0
