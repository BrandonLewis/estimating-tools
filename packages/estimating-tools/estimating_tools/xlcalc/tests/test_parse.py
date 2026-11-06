from __future__ import annotations

import pytest

from estimating_tools.xlcalc import parse as P


def test_precedence_and_associativity():
    assert P.parse("=1+2*3") == P.Binary("+", P.Num(1.0), P.Binary("*", P.Num(2.0), P.Num(3.0)))
    assert P.parse("=8-2-1") == P.Binary("-", P.Binary("-", P.Num(8.0), P.Num(2.0)), P.Num(1.0))
    assert P.parse('="a"&1=1') == P.Binary(
        "=", P.Binary("&", P.Str("a"), P.Num(1.0)), P.Num(1.0))


def test_negation_binds_tighter_than_power_and_percent_is_postfix():
    assert P.parse("=-2^2") == P.Binary("^", P.Unary("-", P.Num(2.0)), P.Num(2.0))
    assert P.parse("=5%") == P.Percent(P.Num(5.0))


def test_calls_with_empty_and_nested_arguments():
    node = P.parse("=IF(A1,,SUM(B1:B3))")
    assert node == P.Call("IF", (P.Ref(None, 1, 1, 1, 1), P.MISSING_ARG,
                                 P.Call("SUM", (P.Ref(None, 1, 2, 3, 2),))))
    assert P.parse("=NA()") == P.Call("NA", ())


def test_literals():
    assert P.parse('="say ""hi"""') == P.Str('say "hi"')
    assert P.parse("=TRUE") == P.Bool(True)
    assert P.parse("=#N/A") == P.ErrorLit("#N/A")


@pytest.mark.parametrize("text,ref", [
    ("A1", P.Ref(None, 1, 1, 1, 1)),
    ("$B$2:C3", P.Ref(None, 2, 2, 3, 3)),
    ("C3:B2", P.Ref(None, 2, 2, 3, 3)),
    ("Rates!A:A", P.Ref("Rates", None, 1, None, 1)),
    ("'Cost Report'!$X$5", P.Ref("Cost Report", 5, 24, 5, 24)),
    ("'it''s'!A1", P.Ref("it's", 1, 1, 1, 1)),
])
def test_references(text, ref):
    assert P.ref_or_name(text) == ref


def test_names():
    assert P.ref_or_name("Markup") == P.Name("MARKUP")
    assert P.ref_or_name("tbl.rates_2") == P.Name("TBL.RATES_2")


@pytest.mark.parametrize("formula", [
    "={1,2}", "=A1:INDEX(B:B,2)", "=1:3", "=SUM(A1 B1)", "=1+", "=SUM(1",
    "=Sheet1!#REF!", "=@A1",
])
def test_what_it_does_not_parse(formula):
    with pytest.raises(P.FormulaError):
        P.parse(formula)
