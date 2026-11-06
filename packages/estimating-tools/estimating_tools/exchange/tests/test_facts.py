from __future__ import annotations

from openpyxl import Workbook
from openpyxl.packaging.custom import StringProperty
from openpyxl.workbook.defined_name import DefinedName

from estimating_tools.exchange.facts import read_facts


def test_read_facts_reads_properties_names_and_sheets(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Bid Form"
    hidden = wb.create_sheet("_wb")
    hidden["A1"] = '{"format": "heavybook"}'
    wb.defined_names["hc.layout"] = DefinedName("hc.layout", attr_text="_wb!$A$1")
    wb.custom_doc_props.append(StringProperty(name="estimate_format", value="heavybook 1"))
    path = tmp_path / "b.xlsx"
    wb.save(path)
    facts = read_facts(path, names=("hc.layout", "exchange.stamp"))
    assert facts.properties["estimate_format"] == "heavybook 1"
    assert facts.names == {"hc.layout": '{"format": "heavybook"}'}
    assert facts.sheets == ["Bid Form", "_wb"]
    assert facts.path == str(path)


def test_read_facts_on_a_non_workbook(tmp_path):
    path = tmp_path / "x.xlsx"
    path.write_text("not a zip")
    facts = read_facts(path)
    assert facts.properties == {} and facts.sheets == [] and facts.error


def test_read_facts_on_a_missing_path(tmp_path):
    facts = read_facts(tmp_path / "missing.xlsx")
    assert facts.error.startswith("no such file")
    assert facts.properties == {} and facts.names == {} and facts.sheets == []


def test_a_whole_column_defined_name_is_skipped_without_error(tmp_path):
    wb = Workbook()
    wb.create_sheet("_wb")
    wb.defined_names["exchange.stamp"] = DefinedName("exchange.stamp", attr_text="_wb!$A:$A")
    path = tmp_path / "c.xlsx"
    wb.save(path)
    facts = read_facts(path)
    assert "exchange.stamp" not in facts.names
    assert facts.error == "" and facts.sheets == ["Sheet", "_wb"]
