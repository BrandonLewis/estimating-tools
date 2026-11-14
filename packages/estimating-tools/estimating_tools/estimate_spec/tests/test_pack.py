from __future__ import annotations

import pytest

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import pack as fb_pack
from estimating_tools.estimate_spec.tests._fieldbook import EXAMPLE, fieldbook_pack
from estimating_tools.exchange.facts import read_facts
from estimating_tools.exchange.types import BookFacts, NotYet


def test_identity():
    p = fb_pack.pack()
    assert (p.name, p.contract) == ("fieldbook", "1") and p.version == "2"


def test_version_matches_the_fieldbook_format_pack():
    assert fb_pack.FORMAT_VERSION == fieldbook_pack().version


def test_detect_by_the_estimate_format_property():
    p = fb_pack.pack()
    assert p.detect(BookFacts(path="x", properties={"estimate_format": "fieldbook 2"})) == "ok"
    assert p.detect(BookFacts(path="x", properties={"estimate_format": "heavybook 1"})) == "none"
    assert p.detect(BookFacts(path="x", properties={"estimate_format": "fieldbook 3"})) == "newer"
    assert p.detect(BookFacts(path="x", properties={"estimate_format": "fieldbook x"})) == "bad"
    assert p.detect(BookFacts(path="x")) == "none"
    for stamp in ("fieldbook -1", "fieldbook 0"):
        assert p.detect(BookFacts(path="x", properties={"estimate_format": stamp})) == "bad"


@pytest.mark.parametrize("stamp, verdict", [
    ("derived_fieldbook 1 / fieldbook 2", "ok"),
    ("derived_fieldbook 1 / fieldbook 3", "newer"),
    ("arr 1 / fieldbook 2", "ok"),
    ("heavybook 1", "none"),
])
def test_detect_walks_a_derived_packs_chain(stamp, verdict):
    facts = BookFacts(path="x", properties={"estimate_format": stamp})
    assert fb_pack.pack().detect(facts) == verdict


def test_a_real_fieldbook_book_detects_as_ok(tmp_path):
    out = tmp_path / "book.xlsx"
    B.build(EXAMPLE, out, fieldbook_pack(), lint=False)
    assert fb_pack.pack().detect(read_facts(out)) == "ok"


def test_read_and_patch_refuse_until_1_11(tmp_path):
    p = fb_pack.pack()
    with pytest.raises(NotYet, match="read-back"):
        p.read(tmp_path / "b.xlsx")
    with pytest.raises(NotYet, match="patches through the engine in delivery 3"):
        p.patch(tmp_path / "b.xlsx", None, None, {})
    with pytest.raises(NotYet, match="refreshes through the engine in delivery 3"):
        p.refresh(tmp_path / "b.xlsx", {})


def test_the_declaration_is_the_bundled_layout_map_lifted():
    """``Pack.declaration()`` for fieldbook: ``pack.yaml`` with the bundled
    pack's ``layout_map`` lifted into its navigator section and prototypes."""
    pack = fb_pack.pack()
    decl = pack.declaration()
    assert (decl.pack.name, decl.pack.version, decl.kind) == ("fieldbook", "2", "recipe")
    assert list(decl.sheets) == ["items", "rates"]
    assert decl.prototypes == {"task": "est.tpl.task", "crew": "est.tpl.crew",
                               "line": "est.tpl.line"}
    assert set(decl.prototypes.values()) == {k.name for k in pack.templates()}
    assert decl.navigator["tags"] == fieldbook_pack().layout_map["tags"]


def test_templates_name_the_fieldbook_prototypes():
    assert {k.name for k in fb_pack.pack().templates()} == {
        "est.tpl.task", "est.tpl.crew", "est.tpl.line"}
