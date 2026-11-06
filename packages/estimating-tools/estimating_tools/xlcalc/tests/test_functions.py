from __future__ import annotations

import pytest

from estimating_tools.xlcalc import values as V
from estimating_tools.xlcalc.tests._calc import calc


@pytest.mark.parametrize("formula,want", [
    ("=1+2*3", 7.0), ("=-2^2", 4.0), ("=2^-1", 0.5), ("=10%", 0.1), ('="a"&1.5', "a1.5"),
    ('="A"="a"', True), ("=1<\"a\"", True), ("=1/0", V.DIV0), ('="x"+1', V.VALUE),
    ("=A1+1", 1.0), ("=A1", 0.0), ('=A1=""', True), ("=A1=0", True),
])
def test_operators(formula, want):
    assert calc(formula) == want


@pytest.mark.parametrize("formula,want", [
    ("=ROUND(2.5,0)", 3.0), ("=ROUND(-2.5,0)", -3.0), ("=ROUND(1.005,2)", 1.01),
    ("=ROUND(1234.5,-2)", 1200.0), ("=ROUND(0.1+0.2,10)", 0.3),
    ("=CEILING(2.1,0.5)", 2.5), ("=CEILING(-2.1,0.5)", -2.0), ("=CEILING(-2.1,-0.5)", -2.5),
    ("=CEILING(2.1,-1)", V.NUM), ("=CEILING(0.3,0.1)", 0.3),
    ("=INT(-1.5)", -2.0), ("=MOD(-1,3)", 2.0), ("=MOD(1,0)", V.DIV0), ("=ABS(-4)", 4.0),
    ("=NOT(0)", True), ("=AND(1,TRUE)", True), ("=OR(0,FALSE)", False),
])
def test_math_and_logic(formula, want):
    assert calc(formula) == want


def test_sum_min_max_count_skip_text_in_ranges_and_propagate_errors():
    cells = {"A1": 1, "A2": "x", "A3": True, "A4": 4}
    assert calc("=SUM(A1:A5)", **cells) == 5.0
    assert calc("=MIN(A1:A5)", **cells) == 1.0
    assert calc("=MAX(A1:A5,10)", **cells) == 10.0
    assert calc("=COUNT(A1:A5)", **cells) == 2.0
    assert calc("=MAX(B1:B3)") == 0.0
    assert calc("=SUM(A1:A2)", A1=1, A2="=1/0") == V.DIV0


def test_if_takes_one_branch_and_iferror_catches():
    assert calc("=IF(1,2)") == 2.0
    assert calc("=IF(0,2)") is False
    assert calc("=IF(0,2,)") == 0.0
    assert calc("=IF(1,5,1/0)") == 5.0
    assert calc("=IF(NA(),1,2)") == V.NA
    assert calc("=IFERROR(1/0,7)") == 7.0
    assert calc("=IFERROR(3,7)") == 3.0
    assert calc("=ISNA(NA())") is True
    assert calc("=ISNUMBER(1/0)") is False
    assert calc('=ISTEXT("a")') is True
    assert calc("=ISNUMBER(A1)", A1="3") is False


def test_sumif_and_countif():
    cells = {"A1": "pipe", "A2": "Pipe 2", "A3": "box", "B1": 10, "B2": 5, "B3": 7}
    assert calc('=SUMIF(A1:A3,"pipe*",B1:B3)', **cells) == 15.0
    assert calc('=SUMIF(B1:B3,">6")', **cells) == 17.0
    assert calc('=SUMIF(A1:A3,"box",B1)', **cells) == 7.0
    assert calc('=COUNTIF(A1:A3,"<>box")', **cells) == 2.0
    assert calc('=SUMIF(A1:A3,"pipe",B1:B3)', **{**cells, "B1": "=1/0"}) == V.DIV0


def test_lookups():
    cells = {"A1": 1, "A2": 3, "A3": 5, "B1": "one", "B2": "three", "B3": "five"}
    assert calc("=VLOOKUP(3,A1:B3,2,FALSE)", **cells) == "three"
    assert calc("=VLOOKUP(4,A1:B3,2)", **cells) == "three"
    assert calc("=VLOOKUP(4,A1:B3,2,FALSE)", **cells) == V.NA
    assert calc("=VLOOKUP(3,A1:B3,3,FALSE)", **cells) == V.REF
    assert calc('=MATCH("FIVE",B1:B3,0)', **cells) == 3.0
    assert calc("=MATCH(4,A1:A3)", **cells) == 2.0
    assert calc("=MATCH(0,A1:A3)", **cells) == V.NA
    assert calc("=INDEX(B1:B3,2)", **cells) == "three"
    assert calc("=INDEX(A1:B3,3,2)", **cells) == "five"
    assert calc("=INDEX(A1:A3,4)", **cells) == V.REF
    assert calc("=INDEX(A:A,2)", **cells) == 3.0


def test_row():
    assert calc("=ROW()") == 99.0
    assert calc("=ROW(C7:D9)") == 7.0


def test_wrong_argument_counts_are_value_errors():
    assert calc("=ROUND(1)") == V.VALUE
    assert calc("=NA(1)") == V.VALUE
