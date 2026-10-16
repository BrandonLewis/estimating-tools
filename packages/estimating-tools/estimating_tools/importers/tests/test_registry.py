from pathlib import Path

import pytest

from estimating_tools.importers.model import CanonicalEstimate, Schedule, LineItem
from estimating_tools.importers import registry


class _StubImporter:
    name = "stub"

    def __init__(self, matches: bool):
        self._matches = matches

    def detect(self, path: Path) -> bool:
        return self._matches

    def parse(self, path: Path) -> CanonicalEstimate:
        return CanonicalEstimate(project={"name": "stub"},
                                 schedules=[Schedule(name="Base Bid", items=[LineItem(item_number="1")])])


def test_register_and_dispatch_to_matching_importer(monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", [])
    registry.register(_StubImporter(matches=False))
    registry.register(_StubImporter(matches=True))
    est = registry.import_file(Path("anything.xlsx"))
    assert est.project["name"] == "stub"


def test_no_match_raises(monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", [])
    registry.register(_StubImporter(matches=False))
    with pytest.raises(ValueError):
        registry.import_file(Path("anything.xlsx"))
