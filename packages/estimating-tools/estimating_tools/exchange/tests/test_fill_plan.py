"""Where a fill puts every row (``fill.plan``): HeavyBook's order (item, its
element quantities, its activities depth first, each as its block),
variants, outline levels, the block map, display rows -- on HeavyBook's
fixture payload through the test pack's declaration."""
from __future__ import annotations

import copy
from decimal import Decimal

import pytest
import yaml

from estimating_tools.exchange import model
from estimating_tools.exchange.declaration import load
from estimating_tools.exchange.fill import lint as L
from estimating_tools.exchange.fill.plan import FillRefused, layout
from estimating_tools.exchange.tests import _template as T
from estimating_tools.heavybook.tests import _readback as H


@pytest.fixture
def packed(tmp_path):
    d = T.make(tmp_path / "pack")
    decl = load(yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8")))
    return decl, L.check(d / "template.xlsx", decl).protos


def test_the_rows_follow_heavybooks_order(packed):
    decl, protos = packed
    wb = model.parse(H.fixture_doc())
    rows = layout(decl, "estimate", wb, protos)
    first = [(r.kind, getattr(r.obj, "id", None)) for r in rows[:16]]
    assert first == [("ITEM", 1), ("ELEMENT_QTY", None),
                     ("ACTIVITY", 1), ("START", None), ("RESOURCE", 1), ("END", None),
                     ("ACTIVITY", 2), ("START", None), ("RESOURCE", 2), ("RESOURCE", 3),
                     ("END", None),
                     ("ACTIVITY", 3), ("START", None), ("RESOURCE", 4), ("END", None),
                     ("ACTIVITY", 4)]
    assert len(rows) == 42                    # HeavyBook's Cost Report: rows 5..46


def test_a_stepped_activity_is_copied_from_its_variant(packed):
    decl, protos = packed
    wb = model.parse(H.fixture_doc())
    rows = layout(decl, "estimate", wb, protos)
    at = next(i for i, r in enumerate(rows) if r.kind == "ACTIVITY" and r.obj.id == 4)
    block = rows[at:at + 7]
    assert [r.kind for r in block] == ["ACTIVITY", "STEPS", "STEP", "START", "RESOURCE",
                                       "RESOURCE", "END"]
    stepped = protos["stepped"]
    assert [r.proto_row for r in block] == [stepped.first + n for n in (0, 1, 2, 3, 4, 4, 5)]
    assert all(r.stepped for r in block)
    # The owner and markers stand for their prototype rows; the sample rows don't.
    assert block[0].block == ((stepped.first, at), (stepped.first + 1, at + 1),
                              (stepped.first + 3, at + 3), (stepped.first + 5, at + 6))


def test_a_required_step_block_is_in_the_plain_prototype_and_steps_every_activity(tmp_path):
    """A required STEP block needs no variant: the plain ``activity``
    prototype holds STEPS and a sample STEP (the test pack's stepped rows),
    the lint reads its D as the stepped shifts formula, not the
    ``duration_shifts`` input, and every activity -- with steps or without
    -- is laid out from it, stepped."""
    doc = copy.deepcopy(T.DECLARATION)
    doc["sheets"]["estimate"]["blocks"]["steps"]["optional"] = False
    doc["prototypes"]["activity"] = doc["prototypes"].pop("stepped")
    d = T.make(tmp_path / "pack", declaration=doc)
    decl = load(yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8")))
    protos = L.check(d / "template.xlsx", decl).protos
    assert "stepped" not in protos
    rows = layout(decl, "estimate", model.parse(H.fixture_doc()), protos)
    at = next(i for i, r in enumerate(rows) if r.kind == "ACTIVITY" and r.obj.id == 1)
    assert [r.kind for r in rows[at:at + 5]] == ["ACTIVITY", "STEPS", "START", "RESOURCE", "END"]
    at = next(i for i, r in enumerate(rows) if r.kind == "ACTIVITY" and r.obj.id == 4)
    assert [r.kind for r in rows[at:at + 7]] == ["ACTIVITY", "STEPS", "STEP", "START",
                                                 "RESOURCE", "RESOURCE", "END"]
    assert all(r.stepped for r in rows if r.kind == "ACTIVITY")


def test_outline_levels_follow_the_tree(packed):
    decl, protos = packed
    wb = model.parse(H.fixture_doc())
    rows = layout(decl, "estimate", wb, protos)
    levels = {(r.kind, r.obj.id): r.level for r in rows
              if r.kind in ("ITEM", "ACTIVITY") and r.obj is not None}
    assert levels[("ITEM", 1)] == 0
    assert levels[("ACTIVITY", 2)] == 1 and levels[("ACTIVITY", 3)] == 2   # 3 is 2's child
    assert [r.level for r in rows if r.kind == "ELEMENT_QTY"] == [1, 1]


def test_a_display_sheet_has_one_row_per_share(packed):
    decl, protos = packed
    wb = model.parse(H.fixture_doc())
    rows = layout(decl, "shares", wb, protos)
    assert [(r.kind, r.obj.activity_id, r.obj.item_id) for r in rows][4:6] == [
        ("SHARE", 5, 1), ("SHARE", 5, 2)]


def test_quantities_that_pay_no_item_sit_under_a_group_row(packed):
    decl, protos = packed
    doc = H.fixture_doc()
    for e in doc["elements"]:
        for q in e["quantities"]:
            q["pay_item_id"] = None
    rows = layout(decl, "estimate", model.parse(doc), protos)
    assert [r.kind for r in rows[-3:]] == ["GROUP", "ELEMENT_QTY", "ELEMENT_QTY"]
    without = copy.deepcopy(decl.raw)
    without["sheets"]["estimate"]["rows"] = ["ITEM", "ELEMENT_QTY"]
    without["sheets"]["estimate"]["blocks"]["activity"]["within"] = ["ITEM"]
    with pytest.raises(FillRefused, match="2 element quantities pay no item"):
        layout(load(without), "estimate", model.parse(doc), protos)
