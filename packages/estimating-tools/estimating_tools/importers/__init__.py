"""Importer framework: parse legacy estimate formats into the open canonical model."""
from estimating_tools.importers.model import CanonicalEstimate, LineItem, Schedule

__all__ = ["CanonicalEstimate", "LineItem", "Schedule", "import_file", "register"]


def __getattr__(name):  # lazy so importing the model doesn't pull openpyxl/jsonschema
    if name in ("import_file", "register"):
        from estimating_tools.importers import registry
        return getattr(registry, name)
    raise AttributeError(name)
