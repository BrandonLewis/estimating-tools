"""Round-trip YAML: what `read-back --write` keeps of the spec the estimator wrote."""
from __future__ import annotations

import yaml

from estimating_tools.estimate_spec.readback.spec_io import SpecYaml
from estimating_tools.estimate_spec.tests._fieldbook import EXAMPLE, example_spec


def commented_spec() -> str:
    """The example as a block-style spec (what `scaffold` writes), with notes added."""
    text = yaml.safe_dump(example_spec(), sort_keys=False, allow_unicode=True)
    text = "# Bid 2026-10 -- hand notes that must survive read-back\n" + text
    return text.replace("  bond_pct: 0.012\n", "  bond_pct: 0.012   # surety quote, 10/01\n")


def _comments(text: str) -> list:
    return [line for line in text.splitlines() if "#" in line]


def test_an_unchanged_block_style_spec_dumps_byte_for_byte():
    text = commented_spec()
    assert SpecYaml(text).dumps() == text


def test_an_edit_in_place_changes_only_its_own_line():
    text = commented_spec()
    doc = SpecYaml(text)
    doc.spec["markup"]["profit"]["labor"] = 0.10
    before, after = text.splitlines(), doc.dumps().splitlines()
    assert len(after) == len(before)
    assert [(a, b) for a, b in zip(before, after) if a != b] == [("    labor: 0.12", "    labor: 0.1")]


def test_the_example_keeps_comments_keys_and_quoting_but_not_inner_flow_spacing():
    text = EXAMPLE.read_text(encoding="utf-8")
    out = SpecYaml(text).dumps()
    assert _comments(out) == _comments(text)
    assert yaml.safe_load(out) == yaml.safe_load(text)
    assert list(yaml.safe_load(out)) == list(yaml.safe_load(text))     # key order
    assert '    item_no: "2"\n' in out                                    # quoting kept
    assert "  - {trade: Superintendent, rate: 95.00}\n" in out            # 95.00 kept, inner spacing not


def test_a_new_row_in_a_flow_style_list_is_written_in_block_style():
    doc = SpecYaml(EXAMPLE.read_text(encoding="utf-8"))
    doc.spec["items"][0]["labor"][0]["crew"].append({"trade": "Truck Driver", "count": 1, "days": 2})
    assert ("          - {trade: Laborer, count: 2, days: 2}\n"
            "          - trade: Truck Driver\n"
            "            count: 1\n"
            "            days: 2\n") in doc.dumps()


# ---- YAML 1.1 (PyYAML, what `build` reads) vs YAML 1.2 (ruamel.yaml) ----
#: Text PyYAML (YAML 1.1) reads as a bool or a base-60 int when written plain.
YAML11_TEXT = ["Yes", "No", "On", "Off", "yes", "no", "on", "off", "1:30", "y", "~", "null"]


def test_a_string_yaml_1_1_would_misread_is_written_quoted():
    doc = SpecYaml("names: []\n")
    doc.spec["names"].extend(YAML11_TEXT)
    out = doc.dumps()
    assert yaml.safe_load(out) == {"names": YAML11_TEXT}


def test_a_plain_yaml_1_1_scalar_is_read_the_way_build_reads_it():
    text = "a: no\nb: yes\nc: 1:30\nd: Off\ne: plain\n"
    doc = SpecYaml(text)
    assert doc.spec == yaml.safe_load(text) == {"a": False, "b": True, "c": 90, "d": False,
                                                 "e": "plain"}
    assert yaml.safe_load(doc.dumps()) == yaml.safe_load(text)


def test_a_spec_whose_two_readings_cannot_be_reconciled_is_refused():
    import pytest

    from estimating_tools.estimate_spec.readback.spec_io import SpecYamlError
    with pytest.raises(SpecYamlError, match="YAML 1.1"):
        SpecYaml("yes: 1\n'True': 2\n")     # PyYAML reads the key `yes` as True


def test_dumps_refuses_text_that_would_read_back_differently(monkeypatch):
    import pytest

    from estimating_tools.estimate_spec.readback import spec_io
    from estimating_tools.estimate_spec.readback.spec_io import SpecYamlError
    doc = SpecYaml("a: 1\n")
    real = spec_io.SpecYaml._dump_text
    monkeypatch.setattr(spec_io.SpecYaml, "_dump_text",
                        lambda self, spec: real(self, spec).replace("a: 1", "a: 2"))
    with pytest.raises(SpecYamlError, match="would read back differently"):
        doc.dumps()
