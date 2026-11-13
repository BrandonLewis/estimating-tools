"""`est-estimate build` tells a spec from a payload (engine spec,
"Surfaces"): ``build --pack NAME payload.json OUT.xlsx``, ``build SPEC.yaml
OUT.xlsx``, a payload without ``--pack`` and a spec with it refused with
the command that builds each, and the ``heavybook build`` alias taking the
same forms."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from estimating_tools.estimate_spec import cli
from estimating_tools.exchange import registry
from estimating_tools.exchange.cli import is_payload
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.tests import _readback as H

SPEC = (Path(__file__).parents[2] / "estimate_spec" / "packs" / "fieldbook" / "examples"
        / "demo-pipeline.estimate.yaml")


@pytest.fixture(autouse=True)
def packs(monkeypatch, tmp_path):
    from estimating_tools.estimate_spec import pack as fb_pack
    monkeypatch.setattr(registry, "discover",
                        lambda: registry.Discovery([fb_pack.pack(), hb_pack.pack()], []))
    monkeypatch.setenv("ESTIMATING_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)


@pytest.fixture
def payload(tmp_path):
    src = tmp_path / "e1.workbook.json"
    src.write_text(json.dumps(H.fixture_doc()), encoding="utf-8")
    return src


def test_a_last_workbook_name_is_the_output(tmp_path, payload):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(payload), str(a),
                     "--exported-at", "x"]) == 0
    assert cli.main(["build", "--pack", "heavybook", str(payload), "-o", str(b),
                     "--exported-at", "x"]) == 0
    assert a.read_bytes() == b.read_bytes()


def test_the_heavybook_alias_takes_the_output_last_too(tmp_path, payload):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    assert cli.main(["heavybook", "build", str(payload), str(a), "--exported-at", "x"]) == 0
    assert cli.main(["build", "--pack", "heavybook", str(payload), str(b),
                     "--exported-at", "x"]) == 0
    assert a.read_bytes() == b.read_bytes()


def test_pages_and_a_last_output(tmp_path, payload):
    out = tmp_path / "e1.xlsx"
    page = tmp_path / "e1.workbook.p2.json"
    page.write_text(payload.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["build", "--pack", "heavybook", str(payload), str(page), str(out),
                     "--exported-at", "x"]) == 0
    assert out.exists()


def test_the_output_given_twice_is_refused(tmp_path, payload, capsys):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(payload), str(a), "-o", str(b)]) == 1
    assert "the output is given twice" in capsys.readouterr().err
    assert not a.exists() and not b.exists()


def test_a_workbook_alone_is_not_an_input(tmp_path, capsys):
    assert cli.main(["build", str(tmp_path / "book.xlsx")]) == 1
    assert "is a workbook -- build from an estimate spec" in capsys.readouterr().err


def test_a_payload_without_pack_names_the_pack_to_build_it(tmp_path, payload, capsys):
    out = tmp_path / "a.xlsx"
    for argv in (["build", str(payload), str(out)], [str(payload), "-o", str(out)]):
        assert cli.main(argv) == 2
        err = capsys.readouterr().err
        assert (f"{payload} is a BidSheet.ai workbook payload -- name the pack that lays it "
                f"out: est-estimate build --pack NAME {payload} OUT.xlsx (installed: "
                "fieldbook, heavybook)") in err
    assert not out.exists()


def test_a_spec_given_to_pack_is_refused(tmp_path, capsys):
    out = tmp_path / "a.xlsx"
    assert cli.main(["build", "--pack", "heavybook", str(SPEC), str(out)]) == 1
    assert (f"{SPEC} is an estimate spec, and --pack builds from a BidSheet.ai payload"
            in capsys.readouterr().err)
    assert not out.exists()


def test_a_spec_builds_with_its_output_last(tmp_path):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    assert cli.main(["build", str(SPEC), str(a)]) == 0
    assert cli.main(["build", str(SPEC), "-o", str(b)]) == 0
    assert a.exists() and b.exists()


def test_what_is_a_payload(tmp_path, payload):
    assert is_payload(payload)
    spec_json = tmp_path / "x.estimate.json"        # a spec written as JSON is a spec
    spec_json.write_text(json.dumps({"project": "x", "items": []}), encoding="utf-8")
    spec_yaml = tmp_path / "x.estimate.yaml"
    spec_yaml.write_text("project: x\nitems: []\n", encoding="utf-8")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    broken_yaml = tmp_path / "broken.yaml"
    broken_yaml.write_text("a: [", encoding="utf-8")
    assert not any(is_payload(p) for p in (spec_json, spec_yaml, SPEC, broken, broken_yaml,
                                           tmp_path / "missing.json"))


@pytest.fixture
def yaml_payload(tmp_path):
    """The payload saved as YAML: still a payload (an ``estimate`` mapping)."""
    import yaml
    src = tmp_path / "e1.workbook.yaml"
    src.write_text(yaml.safe_dump(H.fixture_doc()), encoding="utf-8")
    return src


def test_a_payload_saved_as_yaml_is_a_payload(tmp_path, yaml_payload, capsys):
    assert is_payload(yaml_payload)
    out = tmp_path / "a.xlsx"
    assert cli.main(["build", str(yaml_payload), str(out)]) == 2
    assert (f"{yaml_payload} is a BidSheet.ai workbook payload -- name the pack"
            in capsys.readouterr().err)
    assert not out.exists()
    assert cli.main(["build", "--pack", "heavybook", str(yaml_payload), str(out),
                     "--exported-at", "x"]) == 0
    assert out.exists()


def test_a_spec_written_as_json_builds(tmp_path):
    import yaml
    spec_json = tmp_path / "x.estimate.json"
    spec_json.write_text(json.dumps(yaml.safe_load(SPEC.read_text(encoding="utf-8"))),
                         encoding="utf-8")
    out = tmp_path / "OUT.xlsx"
    assert cli.main(["build", str(spec_json), str(out)]) == 0
    assert out.exists()
