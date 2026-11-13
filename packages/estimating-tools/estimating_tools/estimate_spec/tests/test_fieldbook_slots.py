"""Tasks are keyed by slot (fieldbook spec, "Build from the read model"):
in a build from the read model, two tasks with one cost code are two
blocks, each with its own recap row; two with one slot are refused, naming
the key. A spec keeps one task per cost code in an item (spec read-back
keys a task by its code): ``test_fieldbook_pack``."""
from __future__ import annotations

import copy

import pytest

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import identity
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.estimate_spec.tests._fieldbook import (example_spec, fieldbook_pack,
                                                             rows_of_kind)

ITEM2 = "2 - 8IN MAIN"


def _two_on_one_code():
    spec = example_spec()
    labor = spec["items"][1]["labor"]
    second = copy.deepcopy(labor[0])
    second["slot"] = "03"
    second["description"] = "Trench excavation, second heading"
    labor.append(second)
    return spec


def _from_the_read_model(config):
    """``config`` built as a build from the read model is (stamped with the
    golden payload): no spec schema, no one-task-per-code rule."""
    base = identity.Baseline(payload=X.payload(), host=X.HOST, exported_at=X.EXPORTED_AT)
    return B.generate(config, fieldbook_pack(), exchange=base)


def test_two_tasks_with_one_cost_code_build_as_two_blocks():
    ws = _from_the_read_model(_two_on_one_code())[ITEM2]
    tasks = rows_of_kind(ws, "TASK")
    assert [ws[f"A{r}"].value for r in tasks] == ["02-100", "02-200", "02-100"]
    recap = rows_of_kind(ws, "RECAP")
    assert [ws[f"A{r}"].value for r in recap] == [f"=$A${r}" for r in tasks]
    subtotals = rows_of_kind(ws, "SUBTOTAL")
    assert [ws[f"P{r}"].value for r in recap] == [f"=$P${r}" for r in subtotals]


def test_two_tasks_with_one_slot_are_refused():
    spec = _two_on_one_code()
    spec["items"][1]["labor"][2]["slot"] = "01"
    with pytest.raises(ValueError, match=r"task\[01\]"):
        _from_the_read_model(spec)
