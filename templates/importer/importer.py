"""EXAMPLE importer adapter — copy this file, rename the class, and implement
detect()/parse() for your own legacy format. Register it with
estimating_tools.importers.register(YourImporter()).
"""
from __future__ import annotations

from pathlib import Path

from estimating_tools.importers.model import CanonicalEstimate, LineItem, Schedule


class ExampleImporter:
    name = "example"

    def detect(self, path: Path) -> bool:
        # Return True only for files your adapter handles (sniff extension/headers).
        return path.suffix.lower() == ".example"

    def parse(self, path: Path) -> CanonicalEstimate:
        # Read `path` and build the open model. This stub returns one empty schedule.
        return CanonicalEstimate(
            project={"name": path.stem, "source": "example"},
            schedules=[Schedule(name="Base Bid", items=[LineItem(item_number="1", description="replace me")])],
        )
