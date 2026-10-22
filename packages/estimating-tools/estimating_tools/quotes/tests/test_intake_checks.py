"""The two intake checks: a printed quote date reads as ISO or is refused, and a
line whose printed numbers disagree is flagged rather than silently stored."""
from __future__ import annotations

import pytest

from estimating_tools.quotes.intake.checks import (
    contradicts,
    normalize_date,
    normalize_date_verbose,
)


@pytest.mark.parametrize(
    "printed,iso",
    [
        ("2026-02-03", "2026-02-03"),          # already ISO, untouched
        ("1/15/2026", "2026-01-15"),
        ("01/13/2026", "2026-01-13"),
        ("12/31/2025", "2025-12-31"),
        ("02/03/26", "2026-02-03"),            # two-digit year
        ("1/28/20", "2020-01-28"),
        ("February 5, 2026", "2026-02-05"),
        ("February 2, 2026", "2026-02-02"),
        ("Feb 05, 2026", "2026-02-05"),
        ("Feb 5 2026", "2026-02-05"),
        ("5 February 2026", "2026-02-05"),
        ("2026/02/03", "2026-02-03"),
        ("2026.02.03", "2026-02-03"),
    ],
)
def test_normalises_a_printed_date(printed, iso):
    assert normalize_date(printed) == iso


@pytest.mark.parametrize(
    "printed",
    [
        None,
        "",
        "   ",
        "see attached",
        "30 days from date of issue",
        "2026",                    # a year is not a date
        "February 2026",           # no day
        "13/13/2026",              # neither part is a month
        "0/0/0000",
    ],
)
def test_refuses_what_it_cannot_read(printed):
    """NULL, not a guess."""
    assert normalize_date(printed) is None


def test_a_date_that_could_be_either_order_is_reported_ambiguous():
    """`03/04/2026` is March 4th under US convention and April 3rd elsewhere.
    The string alone cannot settle it, so the caller is told."""
    iso, ambiguous = normalize_date_verbose("03/04/2026")

    assert iso == "2026-03-04"
    assert ambiguous is True


def test_a_date_only_one_order_can_explain_is_not_ambiguous():
    """`01/13/2026` has no 13th month, so MM/DD is the only reading."""
    iso, ambiguous = normalize_date_verbose("01/13/2026")

    assert iso == "2026-01-13" and ambiguous is False


def test_a_spelled_month_is_never_ambiguous():
    iso, ambiguous = normalize_date_verbose("February 5, 2026")

    assert iso == "2026-02-05" and ambiguous is False


# (quantity, unit price, printed extension, is it a real contradiction?)
REAL = [
    # Sankofa quote 2: the extension is the rate, unmultiplied.
    (29300.0, 78.00, 78.00, True),
    # Associated Rebar: $28 out, and the grand total sums the wrong figure.
    (908.0, 28.63, 26024.0, True),
    # D&M Traffic: $3.77 out on thirteen units.
    (13.0, 153.58, 2000.31, True),
    # Miller Farms: a $2,000 transposition.
    (1.0, 89200.0, 91200.0, True),
    # Jarrett: 722,990 against 722,790.
    (1.0, 722990.0, 722790.0, True),
]

ROUNDING = [
    # Pacific Steel: $2.80 printed, ~$2.7974 charged.
    (8390.0, 2.80, 23470.0, False),
    (429.0, 36.56, 15685.0, False),
    (460.0, 230.59, 106070.0, False),
    (277.0, 653.56, 181037.0, False),
    # NRF Lathrop: extensions printed to the dollar.
    (429.0, 92.32, 39605.0, False),
    (277.0, 873.16, 241865.0, False),
    (1004.0, 187.29, 188039.0, False),
    # SDI: 829,755.00 computed, 829,766 printed.
    (4500.0, 184.39, 829766.0, False),
    # Exact.
    (100.0, 1.42, 142.0, False),
    (125000.0, 1.42, 177500.0, False),
]


@pytest.mark.parametrize("qty,price,ext,expected", REAL + ROUNDING)
def test_contradicts(qty, price, ext, expected):
    assert contradicts(qty, price, ext) is expected


def test_a_line_missing_either_number_cannot_contradict():
    """Only one printed number is not a disagreement."""
    assert contradicts(10.0, None, 500.0) is False
    assert contradicts(10.0, 50.0, None) is False
    assert contradicts(None, None, None) is False


def test_a_freight_rate_counts_toward_the_extension():
    assert contradicts(1128.6, 108.0, 142203.60, 18.0) is False
    assert contradicts(1128.6, 108.0, 142203.60) is True
