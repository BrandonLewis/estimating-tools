"""Two checks run on every printed quote line before it is stored.

`normalize_date` makes a vendor's printed quote date comparable: it returns an
ISO date, or None when the text cannot be read without guessing, so a date
search never silently drops a quote. `contradicts` flags a line whose printed
quantity, unit price and extension disagree by more than display rounding can
explain, so the vendor's own numbers are reviewed rather than trusted.
"""
from __future__ import annotations

import re
from datetime import datetime

# ---------------------------------------------------------------- dates

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# Numeric, any of -/. as the separator, two- or four-digit year.
_NUMERIC_DATE = re.compile(r"^(\d{1,4})[-/.](\d{1,2})[-/.](\d{2,4})$")
_MONTHS = {
    m: i
    for i, name in enumerate(
        "january february march april may june july august september "
        "october november december".split(),
        start=1,
    )
    for m in (name, name[:3])
}
_SPELLED_DATE = re.compile(
    r"^(?:(?P<d1>\d{1,2})\s+)?(?P<mon>[A-Za-z]{3,9})\.?\s+"
    r"(?:(?P<d2>\d{1,2})\s*,?\s+)?(?P<year>\d{4})$"
)
# Two-digit years: a subcontractor quote is not from 1930, and one dated a
# little ahead of today is a typo, not a promise about the next century.
_CENTURY_PIVOT = 70


def _two_digit_year(y: int) -> int:
    return 1900 + y if y >= _CENTURY_PIVOT else 2000 + y


def _valid(y: int, m: int, d: int) -> bool:
    try:
        datetime(y, m, d)
    except ValueError:
        return False
    return True


def normalize_date_verbose(printed) -> tuple[str | None, bool]:
    """Return (ISO date or None, whether the reading needed a convention).

    A date that cannot be read without guessing comes back None rather than
    wrong. `search --since` compares dates as strings, so a quote stored as
    "1/15/2026" is silently dropped from a search for prices since 2025 --
    which tells the estimator nobody has quoted the work. NULL at least says
    "no date", and search counts those out loud.

    `ambiguous` is True when only the US month-first convention separates two
    readings ("03/04/2026"). Every vendor in this folder is a California
    subcontractor, so that convention is right; the caller flags the quote so
    the assumption is visible on the row rather than buried here.
    """
    if not printed or not str(printed).strip():
        return None, False
    raw = str(printed).strip()

    m = _ISO_DATE.match(raw)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        return (raw, False) if _valid(y, mo, d) else (None, False)

    m = _SPELLED_DATE.match(raw)
    if m:
        mon = _MONTHS.get(m.group("mon").lower())
        day = m.group("d1") or m.group("d2")
        if mon and day:
            y, d = int(m.group("year")), int(day)
            if _valid(y, mon, d):
                # A spelled month cannot be mistaken for a day.
                return f"{y:04d}-{mon:02d}-{d:02d}", False
        return None, False

    m = _NUMERIC_DATE.match(raw)
    if m:
        a, b, c = (int(g) for g in m.groups())
        if len(m.group(1)) == 4:                 # 2026/02/03
            return (
                (f"{a:04d}-{b:02d}-{c:02d}", False)
                if _valid(a, b, c) else (None, False)
            )
        year = c if len(m.group(3)) == 4 else _two_digit_year(c)
        us = _valid(year, a, b)                  # month first
        intl = _valid(year, b, a)                # day first
        if us:
            return f"{year:04d}-{a:02d}-{b:02d}", bool(intl and a != b)
        if intl:
            # Only one reading works, and it is not the US one: take it, and
            # say the convention mattered.
            return f"{year:04d}-{b:02d}-{a:02d}", True
    return None, False


def normalize_date(printed) -> str | None:
    """ISO date or None. See normalize_date_verbose for the reasoning."""
    return normalize_date_verbose(printed)[0]


# ----------------------------------------------------------- contradictions

# An extension printed to the dollar can be half a dollar off what the numbers
# behind it multiply to.
_ROUNDED_EXTENSION = 0.5
# How many decimals a printed unit price is assumed to carry when it has none
# of its own -- a whole-dollar rate is still usually a rounded one.
_MIN_PRICE_DECIMALS = 2
_MAX_PRICE_DECIMALS = 6


def _printed_decimals(value: float) -> int:
    """Decimals the vendor's printed unit price appears to carry.

    Read off the value rather than the page, because the page is long gone by
    the time this runs. A rate that reproduces exactly at two decimals was
    almost certainly printed at two.
    """
    for n in range(_MIN_PRICE_DECIMALS, _MAX_PRICE_DECIMALS + 1):
        if abs(round(value, n) - value) < 1e-12:
            return n
    return _MAX_PRICE_DECIMALS


def contradicts(quantity, unit_price, extension, freight=None) -> bool:
    """True when a line's two printed numbers cannot both be right.

    Not a cent-tight comparison. Vendors print unit prices rounded to the cent
    and extensions rounded to the dollar, so the numbers on the page routinely
    fail to reproduce each other by a few dollars while the vendor's own
    arithmetic is perfect: Pacific Steel print 8,390 CY at $2.80 extending to
    $23,470, which is $22 short of 8,390 x 2.80 and exactly right for the
    ~$2.7974 they actually charge.

    A cent-tight test flagged 42 quotes in this library, nearly all of them
    that. It buried the four real contradictions -- Sankofa's 29,300 x $78.00
    extending to $78 -- in noise, and a review queue that is mostly noise does
    not get worked.

    So the band is whatever rounding could account for: half a dollar for the
    extension, plus the quantity times half a unit of the last decimal the
    unit price appears to carry. Outside that, the vendor's numbers disagree
    and both are stored as printed for a human to judge.
    """
    if unit_price is None or extension is None:
        return False
    qty = 1.0 if quantity is None else float(quantity)
    price, ext = float(unit_price), float(extension)
    # A vendor may print two rates on one basis and one extension covering
    # both: Nucor Skyline quotes $108.00/cwt material beside $18.00/cwt
    # freight, and the printed extended price is the sum. Both are transcribed,
    # so both are used to check the extension -- and neither is ever combined
    # into a single stored rate the vendor did not print.
    rate = price + (0.0 if freight is None else float(freight))
    band = _ROUNDED_EXTENSION + abs(qty) * 0.5 * 10 ** -_printed_decimals(rate)
    return abs(qty * rate - ext) > band
