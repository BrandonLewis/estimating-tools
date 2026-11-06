"""The worksheet functions the builders emit, over evaluated arguments.

An argument is a scalar value, a :class:`Range` (read lazily, so INDEX pulls
one cell and SUM pulls them all) or ``MISSING``. A function returns a value
or an ``Err``; it raises ``Unsupported`` for a form it does not do. IF and
IFERROR are not here: they evaluate their branches lazily, in the evaluator.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from estimating_tools.xlcalc.values import (
    DIV0, MISSING, NA, NUM, REF, VALUE, Err, Unsupported, compare, criterion, is_number,
    to_bool, to_number, wildcard)


#: The last row of a sheet: a whole-column reference reaches it.
MAX_ROW = 1_048_576


class Range:
    """A rectangle of one sheet, 1-based and inclusive. ``reader`` gives the
    cell grid: ``reader.cell(sheet, row, col)`` and
    ``reader.block(sheet, top, left, bottom, right)`` (rows of values, which
    stop at the sheet's last used row: ``values`` can be shorter than
    ``height * width``, and the missing cells are blank)."""

    def __init__(self, reader, sheet, top, left, bottom, right):
        self.reader, self.sheet = reader, sheet
        self.top, self.left, self.bottom, self.right = top, left, bottom, right

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    def at(self, i: int, j: int):
        """The value at row ``i``, column ``j`` of the range (1-based)."""
        return self.reader.cell(self.sheet, self.top + i - 1, self.left + j - 1)

    def rows(self) -> list:
        return self.reader.block(self.sheet, self.top, self.left, self.bottom, self.right)

    def values(self) -> list:
        return [v for row in self.rows() for v in row]

    def resized(self, height: int, width: int) -> "Range":
        return Range(self.reader, self.sheet, self.top, self.left,
                     self.top + height - 1, self.left + width - 1)

    def scalar(self):
        if self.height == 1 and self.width == 1:
            return self.at(1, 1)
        raise Unsupported("a range where one value is needed")


class _Raise(Exception):
    def __init__(self, err: Err):
        self.err = err


def scalar(a):
    """An argument as one value (a one-cell range is its cell)."""
    if isinstance(a, Range):
        return a.scalar()
    return None if a is MISSING else a


def _number(a) -> float:
    n = to_number(scalar(a))
    if isinstance(n, Err):
        raise _Raise(n)
    return n


def _int(a) -> int:
    return int(math.trunc(_number(a)))


def _numbers(args) -> list:
    """SUM/MIN/MAX operands: numbers in ranges (text, logicals and blanks
    skipped), direct arguments coerced; the first error raises."""
    out = []
    for a in args:
        if isinstance(a, Range):
            for v in a.values():
                if isinstance(v, Err):
                    raise _Raise(v)
                if is_number(v):
                    out.append(float(v))
        elif a is MISSING:
            out.append(0.0)
        else:
            out.append(_number(a))
    return out


def _sum(args, here):
    return math.fsum(_numbers(args))


def _min(args, here):
    nums = _numbers(args)
    return min(nums) if nums else 0.0


def _max(args, here):
    nums = _numbers(args)
    return max(nums) if nums else 0.0


def _count(args, here):
    n = 0
    for a in args:
        if isinstance(a, Range):
            n += sum(1 for v in a.values() if is_number(v))
        elif a is not MISSING and not isinstance(a, Err) and is_number(to_number(a)):
            n += 1
    return float(n)


def _logicals(args) -> list:
    out = []
    for a in args:
        if isinstance(a, Range):
            for v in a.values():
                if isinstance(v, Err):
                    raise _Raise(v)
                if isinstance(v, bool) or is_number(v):
                    out.append(bool(v))
        else:
            b = to_bool(scalar(a))
            if isinstance(b, Err):
                raise _Raise(b)
            out.append(b)
    if not out:
        raise _Raise(VALUE)
    return out


def _and(args, here):
    return all(_logicals(args))


def _or(args, here):
    return any(_logicals(args))


def _not(args, here):
    b = to_bool(scalar(args[0]))
    return b if isinstance(b, Err) else not b


def _abs(args, here):
    return abs(_number(args[0]))


def _int_fn(args, here):
    return float(math.floor(_number(args[0])))


def _mod(args, here):
    n, d = _number(args[0]), _number(args[1])
    if d == 0:
        return DIV0
    return n - d * math.floor(n / d)


def _decimal(x: float) -> Decimal:
    return Decimal(repr(float(x)))


def _round(args, here):
    x, digits = _number(args[0]), _int(args[1])
    quantum = Decimal(1).scaleb(-digits)
    return float((_decimal(x) / quantum).quantize(Decimal(1), ROUND_HALF_UP) * quantum)


def _ceiling(args, here):
    if len(args) < 2:
        raise Unsupported("CEILING with one argument")
    x, sig = _number(args[0]), _number(args[1])
    if sig == 0 or x == 0:
        return 0.0
    if x > 0 and sig < 0:
        return NUM
    steps = (_decimal(x) / _decimal(sig)).to_integral_value(rounding="ROUND_CEILING")
    return float(steps * _decimal(sig))


def _index(args, here):
    rng = args[0]
    if not isinstance(rng, Range):
        raise Unsupported("INDEX of a value")
    r = _int(args[1])
    c = _int(args[2]) if len(args) > 2 and args[2] is not MISSING else None
    if c is None:
        if rng.height == 1:
            r, c = 1, r
        elif rng.width == 1:
            c = 1
        else:
            raise Unsupported("INDEX of a block with one index")
    if r == 0 or c == 0:
        raise Unsupported("INDEX of a whole row or column")
    if r < 0 or c < 0:
        return VALUE
    if r > rng.height or c > rng.width:
        return REF
    return rng.at(r, c)


def _equal(a, b) -> bool:
    if isinstance(b, str) and isinstance(a, str):
        return wildcard(b).fullmatch(a) is not None
    return a is not None and compare(a, b) == 0


def _position(items: list, v, mode: int):
    """MATCH's 1-based position of ``v`` in ``items``, or ``NA``."""
    if v is None:
        return NA
    if mode == 0:
        for i, x in enumerate(items, start=1):
            if not isinstance(x, Err) and _equal(x, v):
                return i
        return NA
    found = None
    for i, x in enumerate(items, start=1):
        if x is None or isinstance(x, Err) or isinstance(x, bool) != isinstance(v, bool) \
                or isinstance(x, str) != isinstance(v, str):
            continue
        c = compare(x, v)
        if (c <= 0) if mode > 0 else (c >= 0):
            found = i
        else:
            break
    return NA if found is None else found


def _lookup(a):
    v = scalar(a)
    if isinstance(v, Err):
        raise _Raise(v)
    return v


def _match(args, here):
    v = _lookup(args[0])
    rng = args[1]
    if not isinstance(rng, Range) or (rng.height != 1 and rng.width != 1):
        return NA
    mode = 1 if len(args) < 3 or args[2] is MISSING else _int(args[2])
    found = _position(rng.values(), v, 0 if mode == 0 else (1 if mode > 0 else -1))
    return found if isinstance(found, Err) else float(found)


def _vlookup(args, here):
    v = _lookup(args[0])
    table = args[1]
    if not isinstance(table, Range):
        raise Unsupported("VLOOKUP over a value")
    col = _int(args[2])
    approx = True if len(args) < 4 or args[3] is MISSING else to_bool(scalar(args[3]))
    if isinstance(approx, Err):
        return approx
    if col < 1:
        return VALUE
    if col > table.width:
        return REF
    keys = [row[0] for row in table.resized(table.height, 1).rows()]
    found = _position(keys, v, 1 if approx else 0)
    return found if isinstance(found, Err) else table.at(found, col)


def _row(args, here):
    if not args or args[0] is MISSING:
        return float(here[1])
    if not isinstance(args[0], Range):
        return VALUE
    return float(args[0].top)


def _isnumber(args, here):
    return is_number(scalar(args[0]))


def _istext(args, here):
    return isinstance(scalar(args[0]), str)


def _isna(args, here):
    return scalar(args[0]) == NA


def _na(args, here):
    return NA


def _sumif(args, here):
    rng = args[0]
    if not isinstance(rng, Range):
        raise Unsupported("SUMIF over a value")
    test = criterion(scalar(args[1]))
    target = args[2] if len(args) > 2 and args[2] is not MISSING else rng
    if not isinstance(target, Range):
        raise Unsupported("SUMIF summing a value")
    target = target.resized(rng.height, rng.width)
    tests, sums = rng.values(), target.values()
    size = max(len(tests), len(sums))           # blank rows past either's data
    tests += [None] * (size - len(tests))
    sums += [None] * (size - len(sums))
    total = []
    for v, s in zip(tests, sums):
        if test(v):
            if isinstance(s, Err):
                return s
            if is_number(s):
                total.append(float(s))
    return math.fsum(total)


def _countif(args, here):
    rng = args[0]
    if not isinstance(rng, Range):
        raise Unsupported("COUNTIF over a value")
    test = criterion(scalar(args[1]))
    values = rng.values()
    blanks = rng.height * rng.width - len(values)   # past the sheet's data
    return float(sum(1 for v in values if test(v)) + (blanks if test(None) else 0))


#: name -> (function, fewest arguments, most arguments or None).
FUNCTIONS = {
    "SUM": (_sum, 1, None), "MIN": (_min, 1, None), "MAX": (_max, 1, None),
    "COUNT": (_count, 1, None), "AND": (_and, 1, None), "OR": (_or, 1, None),
    "NOT": (_not, 1, 1), "ABS": (_abs, 1, 1), "INT": (_int_fn, 1, 1), "MOD": (_mod, 2, 2),
    "ROUND": (_round, 2, 2), "CEILING": (_ceiling, 1, 2), "INDEX": (_index, 2, 3),
    "MATCH": (_match, 2, 3), "VLOOKUP": (_vlookup, 3, 4), "ROW": (_row, 0, 1),
    "ISNUMBER": (_isnumber, 1, 1), "ISTEXT": (_istext, 1, 1), "ISNA": (_isna, 1, 1),
    "NA": (_na, 0, 0), "SUMIF": (_sumif, 2, 3), "COUNTIF": (_countif, 2, 2),
}

#: Functions that see an error argument instead of returning it.
TAKES_ERRORS = {"ISNUMBER", "ISTEXT", "ISNA", "COUNT"}


def call(name: str, args: list, here):
    """Apply ``name`` to evaluated ``args``. An error in a direct argument is
    the result, except for the functions in ``TAKES_ERRORS``."""
    entry = FUNCTIONS.get(name)
    if entry is None:
        raise Unsupported(f"unknown function {name}")
    fn, low, high = entry
    if len(args) < low or (high is not None and len(args) > high):
        return VALUE
    if name not in TAKES_ERRORS:
        for a in args:
            if isinstance(a, Err):
                return a
    try:
        return fn(args, here)
    except _Raise as r:
        return r.err
