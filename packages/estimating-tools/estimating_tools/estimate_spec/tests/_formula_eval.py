"""Evaluate a built workbook's formulas in pure Python, with pycel.

pycel is a test-only dependency (the `test` extra). Missing it skips locally
but FAILS under CI (`CI=true`), so the evaluation tests can never pass by not
running. pycel 1.0b30 still builds `ast.Str`, which Python 3.12 deprecates
and 3.14 removes; `Evaluated` lends it a stand-in for the duration of each
evaluation only, never touching `ast` outside that call.

Only ever evaluate workbooks this test suite built itself: pycel compiles
formulas to Python, so a hostile workbook is code execution
(CVE-2024-53924). That is why pycel is a test extra, never in `all`.
"""
from __future__ import annotations

import ast
import contextlib
import os
from pathlib import Path

import pytest


def _require_pycel():
    try:
        import pycel  # noqa: F401
    except ImportError:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("pycel is required under CI (install estimating_tools[test])")
        pytest.skip("pycel not installed (pip install pycel)")
    from pycel import ExcelCompiler
    return ExcelCompiler


@contextlib.contextmanager
def _ast_str_shim():
    had = "Str" in vars(ast)
    old = vars(ast).get("Str")
    ast.Str = lambda s: ast.Constant(value=s)
    try:
        yield
    finally:
        if had:
            ast.Str = old
        else:
            del ast.Str


class Evaluated:
    """`ev["Sheet!A1"]` -> the cell's computed value."""

    def __init__(self, compiler):
        self._xl = compiler

    def __getitem__(self, address: str):
        sheet, _, cell = address.rpartition("!")
        with _ast_str_shim():
            return self._xl.evaluate(f"'{sheet}'!{cell}")


def evaluate(wb, tmp_path: Path) -> Evaluated:
    """Save `wb` under tmp_path and return its evaluator."""
    compiler_cls = _require_pycel()
    path = Path(tmp_path) / "evaluated.xlsx"
    wb.save(path)
    return Evaluated(compiler_cls(filename=str(path)))
