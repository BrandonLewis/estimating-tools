"""Excel's value model for the evaluator.

A value is ``None`` (a blank cell), a ``float``, a ``str``, a ``bool`` or an
:class:`Err`. This module holds the coercions arithmetic, text and logic use,
Excel's comparison order, and the SUMIF/COUNTIF criteria. Anything the
evaluator will not decide raises :class:`Unsupported`, and the cell gets no
cached value: a value is never guessed.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Err:
    """An Excel error value (``#N/A``, ``#DIV/0!``, ...)."""
    code: str

    def __str__(self) -> str:
        return self.code


DIV0, NA, VALUE, REF, NAME, NUM, NULL = (
    Err(code) for code in ("#DIV/0!", "#N/A", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!"))
ERRORS = {e.code: e for e in (DIV0, NA, VALUE, REF, NAME, NUM, NULL)}


class Unsupported(Exception):
    """The formula needs something the evaluator does not do."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Missing:
    """An argument left empty, as in ``IF(A1,,1)``."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()

_NUMERIC = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def number_text(n: float) -> str:
    """A number as Excel's General format shows it (15 significant digits)."""
    if float(n).is_integer() and abs(n) < 1e15:
        return str(int(n))
    return f"{n:.15g}"


def to_number(v):
    """``v`` as a number for arithmetic; an error is returned unchanged."""
    if isinstance(v, Err):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if is_number(v):
        return float(v)
    text = v.strip()
    return float(text) if _NUMERIC.match(text) else VALUE


def to_text(v):
    """``v`` as text for ``&``; an error is returned unchanged."""
    if isinstance(v, Err):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if is_number(v):
        return number_text(v)
    return v


def to_bool(v):
    """``v`` as a logical value; an error is returned unchanged."""
    if isinstance(v, Err):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if is_number(v):
        return v != 0
    upper = v.strip().upper()
    if upper in ("TRUE", "FALSE"):
        return upper == "TRUE"
    return VALUE


def _rank(v) -> int:
    if isinstance(v, bool):
        return 2
    if isinstance(v, str):
        return 1
    return 0


def _blank_as(other):
    if isinstance(other, bool):
        return False
    if isinstance(other, str):
        return ""
    return 0.0


def compare(a, b):
    """-1, 0 or 1 in Excel's order (numbers < text < logicals; text without
    regard to case; a blank is 0, "" or FALSE beside its partner), or the
    first error."""
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    if a is None:
        a = _blank_as(b)
    if b is None:
        b = _blank_as(a)
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 1:
        a, b = a.lower(), b.lower()
    return (a > b) - (a < b)


@functools.lru_cache(maxsize=256)
def wildcard(pattern: str) -> re.Pattern:
    """A compiled pattern for Excel's ``*``, ``?`` and ``~`` escapes."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "~" and i + 1 < len(pattern) and pattern[i + 1] in "*?~":
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "*" else "." if ch == "?" else re.escape(ch))
        i += 1
    return re.compile("".join(out), re.IGNORECASE | re.DOTALL)


_OPS = ("<=", ">=", "<>", "<", ">", "=")
_TEST = {"=": lambda c: c == 0, "<>": lambda c: c != 0, "<": lambda c: c < 0,
         ">": lambda c: c > 0, "<=": lambda c: c <= 0, ">=": lambda c: c >= 0}


def criterion(c):
    """A predicate for a SUMIF/COUNTIF criterion (a number, a logical, or
    text such as ``">0"``, ``"<>x"`` or ``"a*"``). Raises ``Unsupported``
    for a blank criterion, whose meaning differs by Excel version."""
    if isinstance(c, Err):
        raise Unsupported("an error as a criterion")
    if c is None:
        raise Unsupported("a blank criterion")
    if isinstance(c, bool) or is_number(c):
        op, operand = "=", (c if isinstance(c, bool) else float(c))
    else:
        op = next((o for o in _OPS if c.startswith(o)), None)
        text = c[len(op):] if op else c
        op = op or "="
        number = to_number(text) if text.strip() else None
        upper = text.strip().upper()
        if is_number(number):
            operand = number
        elif upper in ("TRUE", "FALSE"):
            operand = upper == "TRUE"
        else:
            operand = text
    return lambda v: _matches(v, op, operand)


def _matches(v, op, operand) -> bool:
    if isinstance(v, Err):
        return False
    if isinstance(operand, str):
        if operand == "":
            empty = v is None or v == ""
            if op == "=":
                return empty
            if op == "<>":
                return not empty
            return False
        if op in ("=", "<>"):
            hit = isinstance(v, str) and wildcard(operand).fullmatch(v) is not None
            return hit if op == "=" else not hit
        return isinstance(v, str) and _TEST[op](compare(v, operand))
    if isinstance(operand, bool):
        hit = isinstance(v, bool) and v == operand
        if op == "=":
            return hit
        if op == "<>":
            return not hit
        return isinstance(v, bool) and _TEST[op](compare(v, operand))
    if isinstance(v, str):
        number = to_number(v)
        v = number if is_number(number) else v
    if not is_number(v) or isinstance(v, bool):
        return op == "<>"
    return _TEST[op](compare(float(v), operand))
