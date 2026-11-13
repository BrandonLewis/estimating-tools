"""A tagged rates sheet (fieldbook spec, "Rates are the library plus local
rows"): library rows carry kind RATE and their link in the ref tag, local
rows carry neither. Its key columns are the name, the kind's text (a
section's title) and the rate; ``local_suffix`` is what a local row whose
name a library row has carries after it."""
from __future__ import annotations

import pytest

from estimating_tools.exchange import contract
from estimating_tools.exchange import declaration as D
from estimating_tools.exchange.tests import _forms


def test_a_tagged_rates_sheet_loads():
    sheet = D.load(_forms.with_rates()).sheets["rates"]
    assert (sheet.tag("kind"), sheet.tag("ref"), sheet.local_suffix) == ("I", "J", " (local)")
    assert contract.RATE_ROW == "RATE"


def _untag(s):
    s["tags"].pop("ref")
    s.pop("local_suffix")


@pytest.mark.parametrize("change, says", [
    (lambda s: s["columns_by_key"].pop("kind"),
     r"sheets\.rates\.columns_by_key: a tagged rates sheet needs name, kind and rate"),
    (lambda s: s["tags"].pop("kind"),
     r"sheets\.rates\.tags: a tagged rates sheet needs a kind tag \(its library rows are "
     r"tagged RATE\)"),
    (lambda s: (s["tags"].pop("ref"), s["columns_by_key"].update(id="A", unit="B")),
     r"sheets\.rates\.local_suffix: only a tagged rates sheet \(one with a ref tag\) has "
     r"local rows"),
    (_untag, r"sheets\.rates\.columns_by_key: a rates sheet needs id, name, unit and rate"),
])
def test_the_loader_refuses_and_names_the_defect(change, says):
    doc = _forms.with_rates()
    change(doc["sheets"]["rates"])
    with pytest.raises(D.DeclarationError, match=says):
        D.load(doc)


def test_heavybooks_rates_sheet_is_untagged():
    from estimating_tools.heavybook.pack import pack

    sheet = next(s for s in pack().declaration().sheets.values() if s.role == "rates")
    assert sheet.tag("ref") is None and sheet.local_suffix is None


def test_a_tagged_rates_sheet_with_regions_is_refused_by_name():
    """The fill lays out an untagged rates sheet's regions only; a tagged one
    is refused with a message, not a ``KeyError`` from the label rules."""
    doc = _forms.full()
    rates = doc["sheets"]["rates"]
    rates.update(regions=[{"at": 1, "rows": ["RATE_SECTION"]}],
                 prototypes={"RATE_SECTION": "t.rates"},
                 labels={"RATE_TITLE": {"A": "title"},
                         "RATE": {"A": "name", "B": "kind", "G": "rate"}})
    with pytest.raises(D.DeclarationError,
                       match=r"sheets\.rates\.regions: a tagged rates sheet is not laid out by "
                             r"the fill"):
        D.load(doc)
