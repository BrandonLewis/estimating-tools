"""Importer registration and format dispatch."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from estimating_tools.importers.model import CanonicalEstimate

_REGISTRY: list["Importer"] = []


@runtime_checkable
class Importer(Protocol):
    name: str

    def detect(self, path: Path) -> bool: ...

    def parse(self, path: Path) -> CanonicalEstimate: ...


def register(importer: "Importer") -> None:
    _REGISTRY.append(importer)


def importers() -> list["Importer"]:
    return list(_REGISTRY)


def import_file(path) -> CanonicalEstimate:
    """Dispatch to the first registered importer whose detect() matches `path`."""
    p = Path(path)
    for imp in _REGISTRY:
        if imp.detect(p):
            return imp.parse(p)
    raise ValueError(f"no importer matched {p} (registered: {[i.name for i in _REGISTRY]})")
