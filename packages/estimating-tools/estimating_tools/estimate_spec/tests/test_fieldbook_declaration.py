"""Fieldbook's declaration (fieldbook spec, "The mapping is the
declaration"): ``pack.yaml`` beside ``format.yaml``, with the layout map
lifted into its navigator section and prototypes."""
from __future__ import annotations

import pytest

from estimating_tools.estimate_spec.format_pack import bundled_pack
from estimating_tools.estimate_spec.pack import FORMAT_VERSION, FieldbookPack
from estimating_tools.exchange import declaration as D
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.types import NotYet


@pytest.fixture(scope="module")
def decl():
    return FieldbookPack().declaration()


def test_the_declaration_names_fieldbook(decl):
    assert (decl.pack.name, decl.pack.version, decl.kind) == ("fieldbook", FORMAT_VERSION,
                                                              "recipe")
    assert decl.aliases == {"TASK": "ACTIVITY", "CREW": "RESOURCE", "LINE": "RESOURCE"}
    assert list(decl.sheets) == ["items", "rates"]


def test_the_navigator_section_is_the_layout_maps(decl):
    lifted = D.lift_layout_map(bundled_pack().layout_map, pack="fieldbook",
                               version=FORMAT_VERSION)
    assert decl.navigator == lifted["navigator"]
    assert decl.prototypes == {"task": "est.tpl.task", "crew": "est.tpl.crew",
                               "line": "est.tpl.line"}


def test_the_item_sheet_maps_the_spec(decl):
    items = decl.sheets["items"]
    assert (items.each, items.tag("id"), items.tag("v"), items.tag("ref")) == ("ITEM", "W",
                                                                               "X", "Y")
    assert items.binding("TASK", "description") == D.Binding(column="A", rows="NOTE",
                                                             sep="\n")
    assert items.binding("TASK", "hours_per_shift") == D.Binding(by_name="est.shift_hours")
    assert items.binding("CREW", "time_unit") == D.Binding(column="Z")
    assert items.binding("CREW", "component_type") == D.Binding(from_rate="kind")
    assert items.binding("LINE", "description") == D.Binding(cells=("I", "J"), sep=" · ")
    assert items.not_shown == ("STEP", "ELEMENT_QTY")
    assert items.labels["TASK"]["A"].path == "code"


def test_the_rates_sheet_is_tagged(decl):
    rates = decl.sheets["rates"]
    assert (rates.tag("kind"), rates.tag("ref"), rates.local_suffix) == ("I", "J", " (local)")


def test_the_declaration_fits_the_stamp_cell(decl):
    assert decl.size() < exchange_stamp.CELL_LIMIT // 4


def test_lifting_into_a_declaration_that_has_a_navigator_is_refused():
    with pytest.raises(D.DeclarationError, match="navigator: lifted from the layout map"):
        D.lift_layout_map({}, pack="fieldbook", version="2", into={"navigator": {}})


@pytest.mark.parametrize("call", [
    lambda p, tmp: p.read(tmp / "x.xlsx"),
    lambda p, tmp: p.patch(tmp / "x.xlsx", None, None, {}),
    lambda p, tmp: p.refresh(tmp / "x.xlsx", {}),
])
def test_the_pack_still_refuses_to_read_patch_and_refresh(call, tmp_path):
    with pytest.raises(NotYet):
        call(FieldbookPack(), tmp_path)
