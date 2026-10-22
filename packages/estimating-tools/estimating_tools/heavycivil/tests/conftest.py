from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "workbook.json"


@pytest.fixture
def doc():
    """A fresh copy of the BidSheet.ai fixture payload (tests may mutate it)."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def book(doc):
    from estimating_tools.heavycivil import build, style
    return build.build(doc, style=style.load_style(), exported_at="2026-10-20T09:00:00Z",
                       host="www.bidsheet.ai")


@pytest.fixture
def evaluated(book, tmp_path):
    """The built book's formulas evaluated by pycel (``ev["Sheet!A1"]``)."""
    from estimating_tools.estimate_spec.tests._formula_eval import evaluate
    return evaluate(book, tmp_path)
