"""The template build computes every value the code build computed, for the
fixture, the rate-linked, the edge and the implicit-total payloads (values
by row identity: ``_golden``), and nine edits read back exactly as they did
in the code-built book. A deliberate change updates the golden:
UPDATE_GOLDEN=1 pytest ... (say why in the commit)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.tests import _golden as G
from estimating_tools.heavybook.tests import _readback as H
from estimating_tools.heavybook.tests._edits import EDITS, read_after

AT = "2026-10-20T09:00:00Z"
DOCS = {"golden": H.fixture_doc, "linked": H.linked_doc, "edge": H.edge_doc,
        "implicit": H.implicit_doc}
EDITS_GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "edits.json"


def _build(tmp_path, doc, name):
    out = tmp_path / name
    hb_pack.pack().build(doc, out, options={"exported_at": AT, "host": "www.bidsheet.ai"})
    return out


@pytest.mark.parametrize("label", sorted(DOCS))
def test_every_value_is_the_code_builds(tmp_path, label):
    book = G.identities(_build(tmp_path, DOCS[label](), f"{label}.xlsx"))
    golden = G.load()
    if os.environ.get("UPDATE_GOLDEN"):
        golden[label] = book
        G.GOLDEN.write_bytes((json.dumps(golden, indent=1, sort_keys=True) + "\n").encode())
    assert G.differences(golden[label], book) == []


@pytest.mark.parametrize("name", sorted(EDITS))
def test_an_edit_reads_back_as_it_did_in_the_code_built_book(tmp_path, name):
    got = read_after(EDITS[name], _build(tmp_path, H.fixture_doc(), "book.xlsx"))
    assert got == json.loads(EDITS_GOLDEN.read_text(encoding="utf-8"))[name]


def test_a_price_on_an_excluded_item_is_a_difference(tmp_path):
    """The code build left the excluded item's price and total blank; a
    number there is a pricing regression, not a new helper column."""
    book = G.identities(_build(tmp_path, H.fixture_doc(), "golden.xlsx"))
    golden = G.load()["golden"]
    assert G.differences(golden, book) == []
    row = book["Bid Form"]["ITEM_BID:5"]
    assert "H" not in row and "I" not in row
    row["H"], row["I"] = 999.0, 999.0
    assert G.differences(golden, book) == [
        "Bid Form ITEM_BID:5 H: golden None, book 999.0",
        "Bid Form ITEM_BID:5 I: golden None, book 999.0"]


def test_a_new_helper_column_is_not_a_difference(tmp_path):
    book = G.identities(_build(tmp_path, H.fixture_doc(), "golden.xlsx"))
    book["Bid Form"]["ITEM_BID:5"]["ZZ"] = 1.0
    assert G.differences(G.load()["golden"], book) == []
