"""Compute every formula cell of a :class:`Book` once.

No recursion between cells: computing a cell that reads a formula cell not
yet computed raises :class:`Need`, the driver pushes that cell (every
missing cell of a range at once) on an explicit stack and retries, so a
chain of ten thousand formulas cannot overflow Python's stack. A cell found
on the stack while it is being computed is circular. A cell that fails, and
every cell that reads it, is :class:`Failed` with a reason, and gets no
cached value.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from estimating_tools.xlcalc import parse as P
from estimating_tools.xlcalc.functions import MAX_ROW, Range, call, scalar
from estimating_tools.xlcalc.values import (
    DIV0, ERRORS, MISSING, NUM, Err, Unsupported, compare, to_bool, to_number, to_text)


@dataclass(frozen=True)
class Failed:
    reason: str


class Need(Exception):
    """Formula cells that must be computed first."""

    def __init__(self, keys):
        super().__init__(len(keys))
        self.keys = keys


_DEPENDS = "depends on an unevaluated cell"
_COMPARE = {"=": lambda c: c == 0, "<>": lambda c: c != 0, "<": lambda c: c < 0,
            ">": lambda c: c > 0, "<=": lambda c: c <= 0, ">=": lambda c: c >= 0}


class Evaluator:
    def __init__(self, book):
        self.book = book
        self.results = {}
        self._trees = {}
        self._blocks = {}

    # -- the cells a formula reads ---------------------------------------

    def _value(self, key):
        r = self.results[key]
        if isinstance(r, Failed):
            raise Unsupported(_DEPENDS)
        return r

    def cell(self, sheet, row, col):
        key = (sheet, row, col)
        if key in self.book.formulas:
            if key not in self.results:
                raise Need((key,))
            return self._value(key)
        return self.book.constants.get(key)

    def block(self, sheet, top, left, bottom, right):
        """The rows of a rectangle down to the sheet's last used row (the
        rows below are blank; a reader that counts blanks pads them).

        One block is kept per column span and top, the longest read so
        far: HeavyBook's owner-row helper reads ``AJ$4:AJ{r-1}`` on every
        row, so a longer read computes only its new rows and the book
        retains one list per span, not one per row."""
        bottom = min(bottom, self.book.height(sheet))
        if bottom < top:
            return []
        line = (sheet, top, left, right)
        known = self._blocks.get(line)
        done = top - 1
        if known is not None:
            done += len(known)
            if done >= bottom:
                return known if done == bottom else known[:bottom - top + 1]
        formulas, results = self.book.formulas, self.results
        missing = [(sheet, r, c) for r in range(done + 1, bottom + 1)
                   for c in range(left, right + 1)
                   if (sheet, r, c) in formulas and (sheet, r, c) not in results]
        if missing:
            raise Need(tuple(missing))
        constants = self.book.constants
        new = [[self._value((sheet, r, c)) if (sheet, r, c) in formulas
                else constants.get((sheet, r, c)) for c in range(left, right + 1)]
               for r in range(done + 1, bottom + 1)]
        rows = new if known is None else known + new
        self._blocks[line] = rows
        return rows

    # -- the driver --------------------------------------------------------

    def run(self) -> dict:
        for key in self.book.formulas:
            if key in self.results:
                continue
            # ``waiting``: cells attempted and waiting on others -- the path
            # from ``key`` to the top. A cell pushed but not yet attempted is
            # not on that path, so needing it again is no cycle.
            stack, waiting = [key], set()
            while stack:
                k = stack[-1]
                if k in self.results:
                    stack.pop()
                    waiting.discard(k)
                    continue
                try:
                    self.results[k] = self._compute(k)
                except Need as need:
                    waiting.add(k)
                    for n in reversed(need.keys):     # the first missing cell on top
                        if n in self.results:
                            continue
                        if n in waiting:
                            self.results[n] = Failed("circular")
                        else:
                            stack.append(n)
                except Unsupported as exc:
                    self.results[k] = Failed(exc.reason)
                except ArithmeticError as exc:  # e.g. ROUND(1,30): decimal precision
                    self.results[k] = Failed(f"arithmetic error ({type(exc).__name__})")
                except RecursionError:
                    self.results[k] = Failed("nested too deeply")
        return self.results

    def _compute(self, key):
        text = self.book.formulas[key]
        if text is None:
            raise Unsupported("array formula")
        tree = self._trees.get(key)
        if tree is None:
            try:
                tree = P.parse(text)
            except P.FormulaError:
                raise Unsupported("parse error") from None
            self._trees[key] = tree
        v = scalar(self.eval(tree, key))
        return 0.0 if v is None else v

    # -- expressions -------------------------------------------------------

    def eval(self, node, here):
        kind = type(node)
        if kind is P.Num or kind is P.Str or kind is P.Bool:
            return node.value
        if kind is P.Ref:
            return self._range(node, here)
        if kind is P.Name:
            ref = self.book.names.get((here[0], node.name)) or self.book.names.get(node.name)
            if ref is None:
                raise Unsupported(f"unknown name {node.name}")
            return self._range(ref, here)
        if kind is P.Call:
            return self._call(node, here)
        if kind is P.Binary:
            return self._binary(node, here)
        if kind is P.Unary:
            n = to_number(scalar(self.eval(node.operand, here)))
            return n if isinstance(n, Err) or node.op == "+" else -n
        if kind is P.Percent:
            n = to_number(scalar(self.eval(node.operand, here)))
            return n if isinstance(n, Err) else n / 100
        if kind is P.ErrorLit:
            err = ERRORS.get(node.code)
            if err is None:
                raise Unsupported(f"unknown error {node.code}")
            return err
        raise Unsupported("an empty argument outside a call")

    def _range(self, ref, here):
        sheet = ref.sheet or here[0]
        if sheet not in self.book.heights:
            raise Unsupported(f"unknown sheet {sheet}")
        if ref.top is None:
            return Range(self, sheet, 1, ref.left, MAX_ROW, ref.right)
        return Range(self, sheet, ref.top, ref.left, ref.bottom, ref.right)

    def _arg(self, node, here):
        return MISSING if node is P.MISSING_ARG else self.eval(node, here)

    def _call(self, node, here):
        name, args = node.name, node.args
        if name == "IF":
            if not 1 <= len(args) <= 3:
                return ERRORS["#VALUE!"]
            test = to_bool(scalar(self._arg(args[0], here)))
            if isinstance(test, Err):
                return test
            pick = 1 if test else 2
            if pick >= len(args):
                return False
            chosen = args[pick]
            return 0.0 if chosen is P.MISSING_ARG else self.eval(chosen, here)
        if name == "IFERROR":
            if len(args) != 2:
                return ERRORS["#VALUE!"]
            value = scalar(self._arg(args[0], here))
            if isinstance(value, Err):
                return scalar(self._arg(args[1], here))
            return value
        return call(name, [self._arg(a, here) for a in args], here)

    def _binary(self, node, here):
        a = scalar(self.eval(node.left, here))
        b = scalar(self.eval(node.right, here))
        op = node.op
        if op == "&":
            ta, tb = to_text(a), to_text(b)
            if isinstance(ta, Err):
                return ta
            return tb if isinstance(tb, Err) else ta + tb
        if op in _COMPARE:
            c = compare(a, b)
            return c if isinstance(c, Err) else _COMPARE[op](c)
        x, y = to_number(a), to_number(b)
        if isinstance(x, Err):
            return x
        if isinstance(y, Err):
            return y
        if op == "+":
            r = x + y
        elif op == "-":
            r = x - y
        elif op == "*":
            r = x * y
        elif op == "/":
            if y == 0:
                return DIV0
            r = x / y
        else:
            try:
                r = math.pow(x, y)
            except (OverflowError, ValueError):
                return NUM
        return r if math.isfinite(r) else NUM


def evaluate(book) -> dict:
    """``{(sheet, row, col): value or Failed}`` for every formula cell."""
    return Evaluator(book).run()
