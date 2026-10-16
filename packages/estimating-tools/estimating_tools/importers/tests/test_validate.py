import jsonschema
import pytest

from estimating_tools.importers.model import CanonicalEstimate, LineItem, Schedule
from estimating_tools.importers.validate import validate_canonical


def test_valid_estimate_passes():
    est = CanonicalEstimate(project={"name": "P"},
                            schedules=[Schedule(name="Base Bid", items=[LineItem(item_number="1")])])
    validate_canonical(est.to_dict())  # no raise


def test_missing_project_name_rejected():
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical({"project": {}, "schedules": [{"name": "Base Bid", "items": []}]})


def test_item_without_item_number_rejected():
    bad = {"project": {"name": "P"},
           "schedules": [{"name": "Base Bid", "items": [{"description": "no number"}]}]}
    with pytest.raises(jsonschema.ValidationError):
        validate_canonical(bad)
