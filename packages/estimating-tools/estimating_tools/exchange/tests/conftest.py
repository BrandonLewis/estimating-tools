from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parents[2] / "heavybook" / "tests" / "fixtures" / "workbook.json"


@pytest.fixture
def doc():
    """A fresh copy of the BidSheet.ai fixture payload (tests may mutate it)."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))
