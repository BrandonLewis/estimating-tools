from __future__ import annotations

import pytest

from estimating_tools.xlcalc import values as V


def test_number_coercion():
    assert V.to_number(None) == 0.0
    assert V.to_number(True) == 1.0
    assert V.to_number(" 2.5 ") == 2.5
    assert V.to_number("abc") is V.VALUE
    assert V.to_number(V.NA) is V.NA


def test_text_coercion_uses_general_format():
    assert V.to_text(3.0) == "3"
    assert V.to_text(0.1 + 0.2) == "0.3"
    assert V.to_text(None) == ""
    assert V.to_text(False) == "FALSE"


def test_bool_coercion():
    assert V.to_bool(None) is False
    assert V.to_bool(2.0) is True
    assert V.to_bool("true") is True
    assert V.to_bool("yes") is V.VALUE


@pytest.mark.parametrize("a,b,want", [
    (1.0, 2.0, -1), ("abc", "ABC", 0), (5.0, "a", -1), ("a", True, -1),
    (None, 0.0, 0), (None, "", 0), (None, None, 0), (None, False, 0),
])
def test_compare_orders_like_excel(a, b, want):
    assert V.compare(a, b) == want


def test_compare_propagates_errors():
    assert V.compare(V.DIV0, 1.0) is V.DIV0


@pytest.mark.parametrize("crit,cell,hit", [
    (">0", 5.0, True), (">0", -1.0, False), (">0", None, False), (">0", "x", False),
    ("<>x", "X", False), ("<>x", None, True), ("=", None, True), ("=", "a", False),
    ("", None, True), ("<>", "a", True), ("<>", None, False),
    ("a*", "ABC", True), ("a?c", "abc", True), ("a~*", "a*", True), ("a~*", "ab", False),
    (3.0, 3.0, True), (3.0, "3", True), (3.0, None, False), ("3", 3.0, True),
    ("<>3", None, True), (True, True, True), (True, 1.0, False),
])
def test_criterion(crit, cell, hit):
    assert V.criterion(crit)(cell) is hit


def test_criterion_never_matches_an_error_cell():
    assert V.criterion(">0")(V.NA) is False
