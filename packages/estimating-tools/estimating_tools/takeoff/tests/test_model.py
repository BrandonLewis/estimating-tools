import pytest

from estimating_tools.takeoff.model import CanonicalTakeoff, TakeoffRow, VALID_KINDS


def test_valid_row_holds_fields():
    r = TakeoffRow(description="Formwork", kind="quantity", quantity=500.0, unit="SF",
                   item_number="0301", schedule="A")
    assert r.kind == "quantity" and r.quantity == 500.0 and r.item_number == "0301"


def test_invalid_kind_raises():
    with pytest.raises(ValueError, match=r"widget|invalid takeoff kind"):
        TakeoffRow(description="x", kind="widget", quantity=1.0)


def test_valid_kinds_are_the_three():
    assert set(VALID_KINDS) == {"quantity", "material", "structure"}


def test_from_json_builds_rows():
    text = (
        '{"organization_id": 7, "project_ref": "RT-12", '
        '"rows": [{"description": "Formwork", "kind": "quantity", "quantity": 500, '
        '"unit": "SF", "item_number": "0301"}]}'
    )
    t = CanonicalTakeoff.from_json(text)
    assert t.organization_id == 7 and t.project_ref == "RT-12"
    assert len(t.rows) == 1 and isinstance(t.rows[0], TakeoffRow)
    assert t.rows[0].description == "Formwork" and t.rows[0].quantity == 500


def test_from_json_non_object_raises_valueerror():
    with pytest.raises(ValueError, match=r"object"):
        CanonicalTakeoff.from_json("[]")


def test_from_json_rows_not_list_raises_valueerror():
    with pytest.raises(ValueError, match=r"rows"):
        CanonicalTakeoff.from_json('{"organization_id": 7, "rows": {"a": 1}}')


def test_from_json_missing_organization_id_raises_valueerror():
    with pytest.raises(ValueError, match=r"organization_id"):
        CanonicalTakeoff.from_json('{"rows": []}')
