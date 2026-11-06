"""The contract tables patch and refresh read (step 3)."""
from __future__ import annotations

from estimating_tools.exchange import contract, model


def test_every_op_prefix_names_a_server_kind_and_a_row_kind():
    assert set(contract.OP_KINDS) == set(contract.OP_ROWS)
    assert set(contract.OP_ROWS.values()) <= set(contract.TAGS)


def test_creating_ops_make_growable_kinds():
    assert set(contract.CREATES.values()) <= set(contract.GROWABLE)


def test_ref_and_placement_attributes_are_read_model_attributes():
    assert isinstance(model.Resource.rate_link, property)
    assert "labor_rate_id" in model.Member.__dataclass_fields__
    assert set(contract.PLACEMENT["ACTIVITY"]) <= set(model.Activity.__dataclass_fields__)


def test_heavybook_declares_a_members_export_rate():
    from estimating_tools.heavybook.declaration import generate

    crews = generate()["sheets"]["crews"]
    assert crews["export_values"]["MEMBER"] == {"P": "effective_hourly_rate"}
