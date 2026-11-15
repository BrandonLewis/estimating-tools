"""Fieldbook on the contract, delivery 2: ``FieldbookPack.build`` and
``est-estimate build --pack fieldbook payload.json OUT.xlsx``."""
from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook

from estimating_tools.estimate_spec import cli
from estimating_tools.estimate_spec.pack import FieldbookPack
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.estimate_spec.tests.test_fieldbook_round_trip import _dump
from estimating_tools.exchange import registry
from estimating_tools.exchange.types import BuildRefused

OPTIONS = {"exported_at": X.EXPORTED_AT, "host": X.HOST}


def _two_shift_lengths() -> dict:
    doc = X.payload()
    doc["activities"][2]["hours_per_shift"] = "10.0"
    return doc


def test_build_writes_a_stamped_book(tmp_path):
    report = FieldbookPack().build(X.payload(), tmp_path / "b.xlsx", options=OPTIONS)
    assert report.path == tmp_path / "b.xlsx" and report.exported_at == X.EXPORTED_AT
    props = {p.name: p.value for p in load_workbook(report.path).custom_doc_props.props}
    assert props["estimate_id"] == str(X.payload()["estimate"]["id"])
    assert props["bidsheet_host"] == X.HOST
    assert props["exported_at"] == X.EXPORTED_AT


def test_two_pack_builds_differ_only_in_the_export_time(tmp_path):
    a = FieldbookPack().build(X.payload(), tmp_path / "a.xlsx", options=OPTIONS).path
    b = FieldbookPack().build(X.payload(), tmp_path / "b.xlsx", options=OPTIONS).path
    later = FieldbookPack().build(X.payload(), tmp_path / "c.xlsx", options={
        **OPTIONS, "exported_at": "2026-11-09T10:30:00Z"}).path
    assert _dump(a) == _dump(b)
    da, dl = _dump(a), _dump(later)
    assert {k for k in da.keys() | dl.keys() if da.get(k) != dl.get(k)} == {
        ("_wb", "A1"), ("property", "exported_at")}


def test_a_refused_payload_is_a_build_refusal(tmp_path):
    with pytest.raises(BuildRefused) as exc:
        FieldbookPack().build(_two_shift_lengths(), tmp_path / "b.xlsx", options=OPTIONS)
    assert exc.value.kind == "payload"
    assert "8.0" in str(exc.value) and "10.0" in str(exc.value)
    assert not (tmp_path / "b.xlsx").exists()


@pytest.fixture(autouse=True)
def _packs(monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "discover",
                        lambda: registry.Discovery([FieldbookPack()], []))
    monkeypatch.setenv("ESTIMATING_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)


def test_the_cli_builds_a_payload_with_pack_fieldbook(tmp_path, capsys):
    src, out = tmp_path / "p.json", tmp_path / "o.xlsx"
    src.write_text(json.dumps(X.payload()), encoding="utf-8")
    assert cli.main(["build", "--pack", "fieldbook", str(src), str(out)]) == 0
    assert "WROTE:" in capsys.readouterr().out
    assert X.ITEM1 in load_workbook(out).sheetnames


def test_the_cli_refusal_exits_one(tmp_path, capsys):
    src, out = tmp_path / "p.json", tmp_path / "o.xlsx"
    src.write_text(json.dumps(_two_shift_lengths()), encoding="utf-8")
    assert cli.main(["build", "--pack", "fieldbook", str(src), str(out)]) == 1
    assert capsys.readouterr().err.startswith("payload refused:")
