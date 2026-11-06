"""The cached values agree with pycel on every formula of the real books.

pycel is the test-only oracle (``estimate_spec/tests/_formula_eval.py``): it
fails under CI when missing, so this cannot pass by not running. Coverage
is asserted first, so it cannot pass by caching nothing either.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.utils.datetime import to_excel

from estimating_tools import xlcalc
from estimating_tools.estimate_spec.tests._formula_eval import _ast_str_shim, _require_pycel

ROOT = Path(__file__).resolve().parents[2]
FIELDBOOK = ROOT / "estimate_spec" / "packs" / "fieldbook" / "examples"
HEAVYBOOK = ROOT / "heavybook" / "tests" / "fixtures" / "workbook.json"


def _fieldbook(name, tmp_path):
    from estimating_tools.estimate_spec.build import build
    out = tmp_path / f"{name}.xlsx"
    build(str(FIELDBOOK / f"{name}.estimate.yaml"), str(out))
    return out


def _heavybook(tmp_path):
    from estimating_tools.heavybook import build, style
    doc = json.loads(HEAVYBOOK.read_text(encoding="utf-8"))
    book = build.build(doc, style=style.load_style(), exported_at="2026-10-20T09:00:00Z",
                       host="www.bidsheet.ai")
    out = tmp_path / "heavybook.xlsx"
    build.save(book, out)
    return out


def _agrees(ours, theirs) -> bool:
    # Read back through openpyxl: a number in a date-formatted cell comes
    # back as a datetime, and an empty text result (``<v/>``) as None.
    if isinstance(ours, (dt.datetime, dt.date)):
        ours = to_excel(ours)
    if ours is None and theirs == "":
        return True
    if theirs is None:
        theirs = "" if isinstance(ours, str) else 0
    if isinstance(ours, bool) or isinstance(theirs, bool):
        return type(ours) is type(theirs) and ours == theirs
    if isinstance(ours, (int, float)) and isinstance(theirs, (int, float)):
        return abs(ours - theirs) <= 1e-9 * max(1.0, abs(theirs))
    return str(ours) == str(theirs)


def assert_agrees_with_pycel(path: Path) -> int:
    """Every formula cell of ``path`` is cached and equals pycel's value.
    Returns the number of formulas checked."""
    compiler_cls = _require_pycel()
    report = xlcalc.cache_values(path)
    assert report.formulas > 0
    assert report.cached == report.formulas, report.summary()
    formulas = load_workbook(path)
    values = load_workbook(path, data_only=True)
    xl = compiler_cls(filename=str(path))
    wrong = []
    with _ast_str_shim():
        for ws in formulas.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if c.data_type != "f":
                        continue
                    ours = values[ws.title][c.coordinate].value
                    theirs = xl.evaluate(f"'{ws.title}'!{c.coordinate}")
                    if not _agrees(ours, theirs):
                        wrong.append(f"{ws.title}!{c.coordinate}: {ours!r} != pycel {theirs!r}")
    assert not wrong, "\n".join(wrong[:20])
    return report.formulas


@pytest.mark.parametrize("name", ["demo-pipeline", "demo-packages"])
def test_fieldbook_examples(name, tmp_path):
    assert assert_agrees_with_pycel(_fieldbook(name, tmp_path)) > 500


def test_heavybook_fixture(tmp_path):
    assert assert_agrees_with_pycel(_heavybook(tmp_path)) > 700


def _uncached(path: Path) -> list:
    """Formula cells of ``path`` with no cached value (an empty-text result,
    which openpyxl reads back as None, is not counted)."""
    from estimating_tools.xlcalc.book import Book
    from estimating_tools.xlcalc.evaluate import evaluate

    values = load_workbook(path, data_only=True)
    return [(sheet, row, col) for (sheet, row, col), want in evaluate(Book.load(path)).items()
            if values[sheet].cell(row, col).value is None and want != ""]


def test_the_builders_cache_their_values_themselves(tmp_path):
    # No cache_values call here: est-estimate build and the HeavyBook save do it.
    assert _uncached(_fieldbook("demo-pipeline", tmp_path)) == []
    assert _uncached(_heavybook(tmp_path)) == []
