from __future__ import annotations

from estimating_tools.exchange import contract


def test_every_writable_field_has_a_reader_and_every_reader_is_known():
    for kind, fields in contract.FIELDS.items():
        assert kind in contract.TAGS, kind
        for name, spec in fields.items():
            assert spec.reader in contract.READERS, (kind, name)
            if spec.reader in contract.CHOICES:
                assert contract.CHOICES[spec.reader]


def test_identity_tags_follow_the_contract_table():
    assert contract.TAGS["ELEMENT_QTY"] == ("id", "key", "v")
    assert contract.TAGS["MEMBER"] == ("id", "parent")
    assert contract.TAGS["ESTIMATE"] == ("id", "v", "name")
    assert contract.TAGS["BID_TOTAL"] == ("id",)
    assert contract.tags_for("START", marker=True) == ("parent",)
    assert contract.tags_for("BID_FIGURE", named=True) == ("name",)
    assert contract.tags_for("GROUP") == ()


def test_collections_name_attributes_of_the_read_model():
    """A child block's row kind maps to the collection the reader fills:
    an activity's ``steps``, the workbook's ``resources`` (flat, each with
    its ``activity_id``) and a crew's ``members``."""
    import dataclasses

    from estimating_tools.exchange import model

    def fields_of(cls):
        return {f.name for f in dataclasses.fields(cls)}

    assert contract.COLLECTIONS == {"STEP": "steps", "RESOURCE": "resources", "MEMBER": "members"}
    assert contract.COLLECTIONS["STEP"] in fields_of(model.Activity)
    assert contract.COLLECTIONS["MEMBER"] in fields_of(model.Crew)
    assert contract.COLLECTIONS["RESOURCE"] in fields_of(model.Workbook)
    assert "activity_id" in fields_of(model.Resource)


#: Writable fields HeavyBook's Cost Report has no cell for: a copy carries
#: them from its source (fieldbook binds both).
UNBOUND = {"ACTIVITY": ("description",), "RESOURCE": ("description",)}


def test_heavybook_binds_every_contract_field_and_nothing_else():
    """HeavyBook's declaration binds each writable field of every kind it
    carries to one column; the reader's inputs are those fields with the
    contract's reader, clear and attribute, in the contract's order."""
    from estimating_tools.exchange.reader import fields as F
    from estimating_tools.heavybook import pack as hb_pack
    decl = hb_pack.pack().declaration()
    bound = {}
    for sheet in decl.sheets.values():
        for kind, by_field in sheet.fields.items():
            assert kind not in bound, kind
            bound[kind] = set(by_field)
            inputs = F.inputs_for_decl(decl, sheet.key, kind)
            assert [i.field for i in inputs] == [f for f in contract.FIELDS[kind]
                                                 if f not in UNBOUND.get(kind, ())]
            for inp in inputs:
                spec = contract.FIELDS[kind][inp.field]
                assert (inp.reader, inp.clear, inp.base_attr) == (
                    spec.reader, spec.clear, spec.attr or inp.field)
                assert inp.letter == by_field[inp.field]
    want = {kind: set(fields) - set(UNBOUND.get(kind, ()))
            for kind, fields in contract.FIELDS.items() if kind != "ESTIMATE"}
    assert bound == want
    named = decl.sheets["bid_form"].named_rows
    assert [n for n, r in named.rows.items() if r.input] == list(contract.FIELDS["ESTIMATE"])
