import pytest

from estimating_tools.takeoff.push import (
    OwnershipError, assert_estimate_owned, is_estimate_owned,
)

OWNED = {"id": 10, "context": "estimate", "context_id": 42}
TEMPLATE = {"id": 11, "context": "template", "context_id": 7}
FOREIGN = {"id": 12, "context": "estimate", "context_id": 99}


def test_owned_assembly_passes():
    assert is_estimate_owned(OWNED, 42) is True
    assert_estimate_owned(OWNED, 42)  # does not raise


def test_template_assembly_refused():
    assert is_estimate_owned(TEMPLATE, 42) is False
    with pytest.raises(OwnershipError, match=r"template"):
        assert_estimate_owned(TEMPLATE, 42)


def test_foreign_estimate_assembly_refused():
    assert is_estimate_owned(FOREIGN, 42) is False
    with pytest.raises(OwnershipError, match=r"99|refusing"):
        assert_estimate_owned(FOREIGN, 42)
