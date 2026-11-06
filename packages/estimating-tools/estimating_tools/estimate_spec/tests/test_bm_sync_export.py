import pytest

from estimating_tools.estimate_spec import scaffold
from estimating_tools.estimate_spec.bm_sync.export import BmExport, ExportError
from estimating_tools.estimate_spec.tests._bm_fixture import (
    acme_rebar, bolt_rebar, export_builder, spec_two_packages)
from estimating_tools.estimate_spec import format_pack as fp
from estimating_tools.estimate_spec.tests._fieldbook import derived_pack_dir


def test_refuses_export_without_carry_mode():
    data = export_builder().package("Reinforcing steel", 273, {"61": 7001}).build()
    del data["packages"][0]["carry_mode"]
    with pytest.raises(ExportError, match="carry_mode on package 'Reinforcing steel'"):
        BmExport.from_dict(data)


def test_refuses_export_without_packages():
    with pytest.raises(ExportError, match="export has no packages"):
        BmExport.from_dict(export_builder().build())


def test_export_error_is_a_value_error():
    assert issubclass(ExportError, ValueError)


def test_package_lookup_is_casefold_and_quotes_are_current_only():
    b = export_builder().package("Reinforcing steel", 273, {"61": 7001})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722, revision=1,
            lines=[{"item_number": "61", "line_id": 900, "unit_price": 1.7, "quantity": 1000}],
            allocations=[{"allocation_id": 5, "quote_line_item_id": 900, "allocation_type": "full"}],
            is_current=False)
    b.quote("Reinforcing steel", 56, "Acme Rebar", 4722, revision=2,
            lines=[{"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}])
    ex = BmExport.from_dict(b.build())
    pkg = ex.package("reinforcing STEEL")
    assert [q.quote_id for q in pkg.quotes] == [56] and pkg.quotes[0].lines["61"]["line_id"] == 901
    assert [a["allocation_id"] for a in pkg.allocations] == [5]   # allocations cover every revision
    assert ex.package("nope") is None
    assert (ex.project_id, ex.estimate_id) == (1234, 100)
    assert pkg.items["61"].work_package_item_id == 7001


def test_quote_without_line_items_has_no_lines():
    b = export_builder().package("P", 1, {})
    data = b.quote("P", 9, "V", None).build()
    del data["packages"][0]["quotes"][0]["line_items"]
    assert BmExport.from_dict(data).package("P").quotes[0].lines == {}


def test_components_keyed_by_item_number():
    b = export_builder().package("P", 1, {"61": 7001})
    b.components(7001, 88, [{"component_id": 1, "name": "Labor", "component_type": "labor",
                             "quantity": 2, "unit_cost": 90.0, "description": ""}])
    pkg = BmExport.from_dict(b.build()).package("P")
    assert pkg.components["61"][0]["assembly_id"] == 88


def test_organizations_by_name_folds_case_and_space():
    ex = BmExport.from_dict(export_builder().package("P", 1, {}).organization(4722, " Acme Rebar ")
                            .organization(4723, "ACME REBAR").build())
    assert ex.organizations_by_name()["acme rebar"] == [4722, 4723]


def test_fixture_spec_validates(tmp_path):
    # The bundled trade vocabulary lacks the pickup and fuel-and-lube lines, so validate against
    # a fork of the pack that lists every trade the fixture's rate_table names.
    root = derived_pack_dir(tmp_path)
    vocab = root / "vocabulary.yaml"
    extra = "".join(f'  - "{r["trade"]}"\n' for r in spec_two_packages()["rate_table"]
                    if r.get("kind") == "equipment")
    vocab.write_text(vocab.read_text(encoding="utf-8").replace("trades:\n", "trades:\n" + extra, 1),
                     encoding="utf-8")
    scaffold.validate_spec(spec_two_packages(), pack=fp.load_pack(root))


def test_fixture_quotes():
    assert acme_rebar().lines[0].unit_price == 1.65 and bolt_rebar().amount == 1720.0


def test_id_is_the_fallback_for_quote_line_and_allocation_ids():
    """Ruling 43a: MCP rows that carry `id` instead of the documented id key."""
    b = export_builder().package("Reinforcing steel", 273, {"61": 7001})
    b.quote("Reinforcing steel", 55, "Acme Rebar", 4722,
            lines=[{"item_number": "61", "line_id": 901, "unit_price": 1.65, "quantity": 1000}],
            allocations=[{"allocation_id": 5, "quote_line_item_id": 901, "allocation_type": "full"}])
    data = b.build()
    qd = data["packages"][0]["quotes"][0]
    qd["id"] = qd.pop("quote_id")
    qd["line_items"][0]["id"] = qd["line_items"][0].pop("line_id")
    qd["allocations"][0]["id"] = qd["allocations"][0].pop("allocation_id")
    pkg = BmExport.from_dict(data).package("Reinforcing steel")
    assert pkg.quotes[0].quote_id == 55
    assert pkg.quotes[0].lines["61"]["line_id"] == 901
    assert pkg.allocations == [{"quote_id": 55, "allocation_id": 5, "quote_line_item_id": 901,
                                "allocation_type": "full", "accept_alternate": False}]


def test_an_organization_without_a_name_is_skipped():
    data = export_builder().package("Reinforcing steel", 273, {"61": 7001}).organization(1, None) \
        .organization(2, "Acme Rebar").build()
    assert BmExport.from_dict(data).organizations_by_name() == {"acme rebar": [2]}
