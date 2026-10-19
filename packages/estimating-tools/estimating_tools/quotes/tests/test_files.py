import json

import pytest

from estimating_tools.quotes.files import (
    QuoteFileError, load_quote_file, load_quotes, quote_file_slug, write_quote_file)
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine

REBAR = {"vendor_name": "Example Rebar Co", "is_dbe": False, "work_package_name": "Reinforcing steel",
         "lines": [{"schedule_name": "Base", "item_number": "61", "unit_price": 2.05, "is_included": True},
                   {"schedule_name": "Base", "item_number": "62", "unit_price": 3.40, "is_included": True}],
         "conditions": {"Sales tax included": "yes", "Freight to site": "yes"}}


def _put(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_rebar_example_shape(tmp_path):
    q = load_quote_file(_put(tmp_path / "rebar.json", REBAR))
    assert q.vendor_name == "Example Rebar Co" and q.work_package_name == "Reinforcing steel"
    assert [l.item_number for l in q.lines] == ["61", "62"]
    assert q.lines[0].unit_price == 2.05 and q.lines[0].line_name is None
    assert q.conditions == {"Sales tax included": "yes", "Freight to site": "yes"}
    assert q.surcharge is None and q.quote_date is None and q.quote_ref is None


def test_load_new_fields_and_coercion(tmp_path):
    data = {**REBAR, "surcharge": 0.04, "quote_date": "2026-10-20", "quote_ref": "Q-7",
            "conditions": {"Days": 30, "Tax": True},
            "lines": [{"schedule_name": "Base", "item_number": "61", "amount": 10, "line_name": "Epoxy"},
                      {"schedule_name": "Base", "item_number": "62", "folded_into": "Epoxy"}]}
    q = load_quote_file(_put(tmp_path / "q.json", data))
    assert q.surcharge == 0.04 and q.quote_date == "2026-10-20" and q.quote_ref == "Q-7"
    assert q.conditions == {"Days": "30", "Tax": "True"}
    assert q.lines[0].line_name == "Epoxy" and q.lines[1].folded_into == "Epoxy"


def test_unknown_keys_refused(tmp_path):
    p = _put(tmp_path / "q.json", {**REBAR, "bogus": 1})
    with pytest.raises(QuoteFileError, match=r"q\.json: unknown key 'bogus'"):
        load_quote_file(p)
    bad = {**REBAR, "lines": [{"schedule_name": "B", "item_number": "1", "unit_price": 1, "nope": 2}]}
    with pytest.raises(QuoteFileError, match="unknown key 'nope'"):
        load_quote_file(_put(tmp_path / "l.json", bad))


def test_line_without_price_refused_unless_excluded_or_folded(tmp_path):
    base = {"schedule_name": "B", "item_number": "1"}
    with pytest.raises(QuoteFileError, match=r"q\.json: line 2 has no price"):
        load_quote_file(_put(tmp_path / "q.json", {**REBAR, "lines": [
            {**base, "unit_price": 1}, base]}))
    ok = {**REBAR, "lines": [{**base, "is_included": False}, {**base, "folded_into": "x"}]}
    assert len(load_quote_file(_put(tmp_path / "ok.json", ok)).lines) == 2


def test_bad_types_refused(tmp_path):
    with pytest.raises(QuoteFileError, match="quote_date must be YYYY-MM-DD"):
        load_quote_file(_put(tmp_path / "a.json", {**REBAR, "quote_date": "10/20/2026"}))
    with pytest.raises(QuoteFileError, match="surcharge"):
        load_quote_file(_put(tmp_path / "b.json", {**REBAR, "surcharge": "4%"}))
    with pytest.raises(QuoteFileError, match="conditions"):
        load_quote_file(_put(tmp_path / "c.json", {**REBAR, "conditions": ["x"]}))
    (tmp_path / "d.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(QuoteFileError, match=r"d\.json"):
        load_quote_file(tmp_path / "d.json")


def test_load_quotes_order_and_example_skipped(tmp_path):
    _put(tmp_path / "b.json", {**REBAR, "quote_date": "2026-10-02"})
    _put(tmp_path / "a.json", {**REBAR, "quote_date": "2026-10-09"})
    _put(tmp_path / "c.json", REBAR)
    _put(tmp_path / "z.example.json", REBAR)
    (tmp_path / "README.md").write_text("x")
    got = load_quotes(tmp_path)
    assert [q.quote_date for q in got] == [None, "2026-10-02", "2026-10-09"]
    assert load_quotes(tmp_path / "missing") == []


def test_write_round_trip(tmp_path):
    q = CanonicalQuote(vendor_name="Dirt Movers", work_package_name="Hauling", conditions={},
                       quote_date="2026-10-20", surcharge=0.05,
                       lines=[QuoteLine("Base", "5", unit_price=4.5, line_name="Haul")])
    p = tmp_path / "out.json"
    write_quote_file(p, q)
    text = p.read_text(encoding="utf-8")
    assert text.endswith("\n") and '"conditions": {}' in text and "quote_ref" not in text
    assert list(json.loads(text))[:2] == ["vendor_name", "work_package_name"]
    assert load_quote_file(p) == q


def test_slug():
    assert quote_file_slug("Dirt Movers", "Hauling") == "dirt-movers--hauling.json"
    assert quote_file_slug("A&B  Co.", "Rebar / Epoxy") == "a-b-co--rebar-epoxy.json"


def _bad_line(**field):
    return {**REBAR, "lines": [REBAR["lines"][0], {**REBAR["lines"][1], **field}]}


@pytest.mark.parametrize("field,value,message", [
    ("is_included", "yes", "line 2: is_included must be true or false"),
    ("is_included", None, "line 2: is_included must be true or false"),
    ("is_alternate", 1, "line 2: is_alternate must be true or false"),
    ("unit_price", "3.40", "line 2: unit_price must be a number"),
    ("unit_price", True, "line 2: unit_price must be a number"),
    ("amount", float("nan"), "line 2: amount must be a number"),
    ("quantity", float("inf"), "line 2: quantity must be a number"),
    ("item_number", 62, "line 2: item_number must be a string"),
    ("schedule_name", None, "line 2: schedule_name must be a string"),
    ("line_name", 7, "line 2: line_name must be a string"),
    ("folded_into", ["Epoxy"], "line 2: folded_into must be a string"),
    ("exclusion_notes", False, "line 2: exclusion_notes must be a string"),
])
def test_line_field_types_are_checked(tmp_path, field, value, message):
    path = _put(tmp_path / "q.json", _bad_line(**{field: value}))
    with pytest.raises(QuoteFileError) as err:
        load_quote_file(path)
    assert str(err.value) == f"{path}: {message}"


@pytest.mark.parametrize("field,value,message", [
    ("is_dbe", "no", "is_dbe must be true or false"),
    ("amount", "8740", "amount must be a number"),
    ("surcharge", float("nan"), "surcharge must be a number"),
    ("vendor_id", 3.5, "vendor_id must be an integer"),
    ("vendor_id", True, "vendor_id must be an integer"),
    ("vendor_name", 12, "vendor_name must be a string"),
    ("work_package_name", None, "work_package_name must be a string"),
    ("quote_ref", 7, "quote_ref must be a string"),
    ("notes", ["a"], "notes must be a string"),
    ("contact_info", {"a": 1}, "contact_info must be a string"),
])
def test_header_field_types_are_checked(tmp_path, field, value, message):
    path = _put(tmp_path / "q.json", {**REBAR, field: value})
    with pytest.raises(QuoteFileError) as err:
        load_quote_file(path)
    assert str(err.value) == f"{path}: {message}"


def test_optional_fields_may_be_null(tmp_path):
    data = {**REBAR, "vendor_id": None, "notes": None, "amount": None, "quote_ref": None,
            "lines": [{**REBAR["lines"][0], "line_name": None, "quantity": None},
                      REBAR["lines"][1]]}
    q = load_quote_file(_put(tmp_path / "q.json", data))
    assert q.vendor_id is None and q.lines[0].line_name is None
    assert load_quote_file(_put(tmp_path / "v.json", {**REBAR, "vendor_id": 42})).vendor_id == 42
