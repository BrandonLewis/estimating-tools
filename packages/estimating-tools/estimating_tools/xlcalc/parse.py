"""Formulas as syntax trees.

Tokens come from openpyxl's ``Tokenizer``; a precedence-climbing parser builds
the tree. Nothing here evaluates or compiles text, so a hostile formula is
only ever data. What the evaluator does not support (array constants, the
range and intersection operators, row ranges, structured and external
references) raises :class:`FormulaError`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl.formula import Tokenizer
from openpyxl.formula.tokenizer import Token


class FormulaError(ValueError):
    """The formula is not in the subset the evaluator reads."""


@dataclass(frozen=True)
class Num:
    value: float


@dataclass(frozen=True)
class Str:
    value: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class ErrorLit:
    code: str


@dataclass(frozen=True)
class Ref:
    """A cell or rectangle; ``top``/``bottom`` are None for whole columns.
    ``sheet`` None means the formula's own sheet."""
    sheet: str | None
    top: int | None
    left: int
    bottom: int | None
    right: int


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Percent:
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple


@dataclass(frozen=True)
class MissingArg:
    """An empty argument, as in ``IF(A1,,1)``."""


MISSING_ARG = MissingArg()

#: Infix operators by precedence (Excel's order; all left-associative).
_PREC = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3,
         "*": 4, "/": 4, "^": 5}

_MAX_COL, _MAX_ROW = 16384, 1048576
_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]+)$")
_COL = re.compile(r"^\$?([A-Za-z]{1,3})$")
_NAME = re.compile(r"^[A-Za-z_\\][A-Za-z0-9_.\\]*$")
_FUNC = re.compile(r"^[A-Z_][A-Z0-9._]*$")
_SHEET = re.compile(r"^(?:'((?:[^']|'')+)'|([^'!]+))!(.+)$")


def _col(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def _cell(text: str):
    m = _CELL.match(text)
    if not m:
        return None
    col, row = _col(m.group(1)), int(m.group(2))
    if col > _MAX_COL or not 1 <= row <= _MAX_ROW:
        return None
    return row, col


def _column(text: str):
    m = _COL.match(text)
    if not m:
        return None
    col = _col(m.group(1))
    return col if col <= _MAX_COL else None


def ref_or_name(text: str):
    """A ``Ref`` for ``A1``, ``A1:B2``, ``A:A`` (each optionally
    ``Sheet!``-qualified), a ``Name`` for a defined name, or
    ``FormulaError``."""
    sheet, body = None, text
    m = _SHEET.match(text)
    if m:
        sheet = m.group(1).replace("''", "'") if m.group(1) is not None else m.group(2)
        body = m.group(3)
    first, sep, second = body.partition(":")
    if sep:
        a, b = _cell(first), _cell(second)
        if a and b:
            return Ref(sheet, min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        ca, cb = _column(first), _column(second)
        if ca and cb:
            return Ref(sheet, None, min(ca, cb), None, max(ca, cb))
        raise FormulaError(f"unsupported reference {text!r}")
    cell = _cell(body)
    if cell:
        return Ref(sheet, cell[0], cell[1], cell[0], cell[1])
    if sheet is None and _NAME.match(body):
        return Name(body.upper())
    raise FormulaError(f"unsupported reference {text!r}")


def parse(formula: str):
    """The syntax tree of ``formula`` (with its leading ``=``)."""
    try:
        tokens = [t for t in Tokenizer(formula).items if t.type != Token.WSPACE]
    except Exception as exc:  # noqa: BLE001 -- the tokenizer raises bare errors
        raise FormulaError(f"cannot tokenize {formula!r}: {exc}") from exc
    parser = _Parser(tokens)
    node = parser.expression(0)
    if parser.peek() is not None:
        raise FormulaError(f"unexpected {parser.peek().value!r} in {formula!r}")
    return node


class _Parser:
    def __init__(self, tokens):
        self.tokens, self.i = tokens, 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self):
        t = self.peek()
        if t is None:
            raise FormulaError("the formula ends early")
        self.i += 1
        return t

    def expression(self, min_prec: int):
        left = self.unary()
        while True:
            t = self.peek()
            if t is None or t.type != Token.OP_IN:
                return left
            prec = _PREC.get(t.value)
            if prec is None:
                raise FormulaError(f"unsupported operator {t.value!r}")
            if prec < min_prec:
                return left
            self.next()
            left = Binary(t.value, left, self.expression(prec + 1))

    def unary(self):
        t = self.peek()
        if t is not None and t.type == Token.OP_PRE:
            self.next()
            if t.value not in ("+", "-"):
                raise FormulaError(f"unsupported prefix {t.value!r}")
            return Unary(t.value, self.unary())
        node = self.primary()
        while (t := self.peek()) is not None and t.type == Token.OP_POST:
            self.next()
            node = Percent(node)
        return node

    def primary(self):
        t = self.next()
        if t.type == Token.OPERAND:
            if t.subtype == Token.NUMBER:
                return Num(float(t.value))
            if t.subtype == Token.TEXT:
                return Str(t.value[1:-1].replace('""', '"'))
            if t.subtype == Token.LOGICAL:
                return Bool(t.value.upper() == "TRUE")
            if t.subtype == Token.ERROR:
                return ErrorLit(t.value.upper())
            if t.subtype == Token.RANGE:
                return ref_or_name(t.value)
        if t.type == Token.PAREN and t.subtype == Token.OPEN:
            node = self.expression(0)
            close = self.next()
            if close.type != Token.PAREN or close.subtype != Token.CLOSE:
                raise FormulaError("unbalanced parentheses")
            return node
        if t.type == Token.FUNC and t.subtype == Token.OPEN:
            name = t.value[:-1].upper()
            if not _FUNC.match(name):
                raise FormulaError(f"unsupported function reference {t.value!r}")
            return Call(name, tuple(self.arguments()))
        raise FormulaError(f"unexpected {t.value!r}")

    def arguments(self):
        args = []
        t = self.peek()
        if t is not None and t.type == Token.FUNC and t.subtype == Token.CLOSE:
            self.next()
            return args
        while True:
            t = self.peek()
            if t is not None and (t.type == Token.SEP and t.subtype == Token.ARG
                                  or t.type == Token.FUNC and t.subtype == Token.CLOSE):
                args.append(MISSING_ARG)
            else:
                args.append(self.expression(0))
            t = self.next()
            if t.type == Token.FUNC and t.subtype == Token.CLOSE:
                return args
            if not (t.type == Token.SEP and t.subtype == Token.ARG):
                raise FormulaError(f"unexpected {t.value!r} in an argument list")
