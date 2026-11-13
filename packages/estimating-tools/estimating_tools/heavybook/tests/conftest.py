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
def built(doc, tmp_path):
    """The fixture payload built by the heavybook pack (its path)."""
    from estimating_tools.heavybook.tests import _readback as H
    return H.build_book(doc, tmp_path / "book.xlsx")


@pytest.fixture
def book(built):
    from openpyxl import load_workbook
    return load_workbook(built)


@pytest.fixture
def evaluated(built):
    """The built book's values as its build cached them (xlcalc):
    ``ev["Sheet!A1"]``."""
    from openpyxl import load_workbook
    wb = load_workbook(built, data_only=True)
    return {f"{ws.title}!{c.coordinate}": c.value
            for ws in wb.worksheets for row in ws.iter_rows() for c in row}
