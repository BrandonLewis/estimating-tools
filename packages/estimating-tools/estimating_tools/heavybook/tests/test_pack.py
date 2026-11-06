from __future__ import annotations

import json

import pytest

from estimating_tools.exchange.facts import read_facts
from estimating_tools.exchange.types import BookFacts, InsertKind
from estimating_tools.heavybook import pack as hb_pack
from estimating_tools.heavybook.columns import CR
from estimating_tools.heavybook.tests import _readback as H


def test_identity():
    p = hb_pack.pack()
    assert (p.name, p.version, p.contract) == ("heavybook", "1", "1")


def test_detect_from_the_property_and_the_layout_cell(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    assert hb_pack.pack().detect(read_facts(path)) == "ok"


def test_detect_accepts_a_heavycivil_stamp():
    facts = BookFacts(path="x", properties={"estimate_format": "heavycivil 1"},
                      names={"hc.layout": json.dumps({"format": "heavycivil",
                                                      "layout_version": 2})})
    assert hb_pack.pack().detect(facts) == "ok"


def _stamp(**over):
    from estimating_tools.exchange import stamp
    args = dict(pack="heavybook", version="1", declaration={}, host="www.bidsheet.ai",
                estimate_id=1, estimate_v="e", exported_at="x",
                baseline={"encoding": "zlib+base64", "chunks": 1, "sha256": "x"},
                extra={"layout": {"layout_version": 3}})
    args.update(over)
    return json.dumps(stamp.make(**args))


def _facts(cell, name="exchange.stamp"):
    return BookFacts(path="x", properties={"estimate_format": "heavybook 1"}, names={name: cell})


def test_detect_says_none_for_a_fieldbook_and_newer_for_a_later_layout():
    p = hb_pack.pack()
    assert p.detect(BookFacts(path="x", properties={"estimate_format": "fieldbook 2"})) == "none"
    newer = json.dumps({"format": "heavybook", "layout_version": 99})
    assert p.detect(_facts(newer, "hc.layout")) == "newer"
    assert p.detect(_facts("{not json", "hc.layout")) == "bad"
    assert p.detect(_facts(_stamp())) == "ok"
    assert p.detect(_facts(_stamp(schema=2))) == "newer"
    assert p.detect(_facts(_stamp(contract="2"))) == "newer"
    assert p.detect(_facts(_stamp(extra={"layout": {"layout_version": 4}}))) == "newer"
    assert p.detect(_facts(_stamp(pack="other"))) == "bad"
    assert p.detect(_facts("{not json")) == "bad"


def test_build_writes_a_book(tmp_path, monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    out = tmp_path / "b.xlsx"
    report = hb_pack.pack().build(H.fixture_doc(), out,
                                  options={"exported_at": "2026-10-20T09:00:00Z",
                                           "host": "https://www.bidsheet.ai"})
    assert out.exists() and report.exported_at == "2026-10-20T09:00:00Z"


def test_read_an_edit_and_a_refusal(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    wb = H.open_book(path)
    ws = wb[H.CR_TAB]
    row = H.cr_row(ws, "RESOURCE", 1)
    ws[f"{CR.QTY}{row}"] = 31
    H.save_book(wb, path)
    result = hb_pack.pack().read(path)
    assert not result.refused and [o["op"] for o in result.change_set.ops] == ["resource.update"]
    wb = H.open_book(path)
    wb[H.CR_TAB][f"{CR.TOTAL}{row}"] = 5          # overwrite a formula
    H.save_book(wb, path)
    result = hb_pack.pack().read(path)
    assert result.refused and any("formula" in p for p in result.problems)


def test_templates_are_the_prototype_names():
    kinds = hb_pack.pack().templates()
    assert InsertKind(kind="resource", name="hc.tpl.resource") in kinds
    assert {k.kind for k in kinds} == {"activity", "stepped", "resource", "step", "member"}


def _entries(path):
    import zipfile
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in sorted(z.namelist())}


def _props(path):
    from openpyxl import load_workbook
    wb = load_workbook(path)
    return {p.name: p.value for p in wb.custom_doc_props.props}


def test_build_normalises_a_url_host_to_the_bare_stamp(tmp_path, monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    opts = {"exported_at": "2026-10-20T09:00:00Z"}
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    hb_pack.pack().build(H.fixture_doc(), a, options={**opts, "host": "https://www.bidsheet.ai/x"})
    hb_pack.pack().build(H.fixture_doc(), b, options={**opts, "host": "www.bidsheet.ai"})
    assert _props(a)["bidsheet_host"] == "www.bidsheet.ai"
    assert _entries(a) == _entries(b)


def test_build_matches_the_cli_byte_for_byte(tmp_path, monkeypatch):
    from estimating_tools.estimate_spec import cli
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    x = "2026-10-20T09:00:00Z"
    assert cli.main(["heavybook", "build", str(H.FIXTURE), "-o", str(a),
                     "--exported-at", x]) == 0
    hb_pack.pack().build(H.fixture_doc(), b, options={"exported_at": x})
    assert _entries(a) == _entries(b)


def test_build_with_an_unknown_style_path_fails(tmp_path):
    from estimating_tools.exchange.types import BuildRefused
    with pytest.raises(BuildRefused) as exc:
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "c.xlsx",
                             options={"style": str(tmp_path / "nope")})
    assert exc.value.kind == "style"
    assert not (tmp_path / "c.xlsx").exists()


def test_an_older_layout_detects_ok_and_read_refuses_it_by_layout(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "old.xlsx")
    wb = H.open_book(path)
    cell = wb["_wb"]["A1"]
    doc = json.loads(cell.value)
    legacy = dict(doc["extra"]["layout"], format="heavybook", layout_version=1,
                  estimate_id=1, estimate_v="e", baseline=doc["baseline"])
    cell.value = json.dumps(legacy)
    H.save_book(wb, path)
    assert hb_pack.pack().detect(read_facts(path)) == "ok"
    result = hb_pack.pack().read(path)
    assert result.refused and any("layout" in p for p in result.problems)


@pytest.mark.parametrize("given, bare", [
    ("  ", "www.bidsheet.ai"), ("HTTPS://WWW.X.ai/a", "www.x.ai"),
    ("host?x=1", "host"), ("https://Host:8443/p#f", "host:8443")])
def test_the_host_is_reduced_to_a_bare_lowercase_host(given, bare):
    assert hb_pack.bare_host(given) == bare


def test_an_http_host_is_refused(tmp_path):
    with pytest.raises(ValueError, match="https"):
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "h.xlsx",
                             options={"host": "http://host"})
    assert not (tmp_path / "h.xlsx").exists()


def test_build_honours_the_profile_option(tmp_path, monkeypatch):
    from estimating_tools.heavybook import style as hb_style
    seen = []
    real = hb_style.resolve_style
    monkeypatch.setattr(hb_style, "resolve_style",
                        lambda path, profile: (seen.append((path, profile)), real())[1])
    marker = object()
    hb_pack.pack().build(H.fixture_doc(), tmp_path / "p.xlsx", options={"profile": marker})
    assert seen == [(None, marker)]


def test_a_strict_profile_refusal_propagates_and_writes_nothing(tmp_path, monkeypatch):
    from estimating_tools.estimate_spec import format_pack
    from estimating_tools.exchange.types import BuildRefused

    def refuse(field="format"):
        raise format_pack.FormatPackError("org profile refused")
    monkeypatch.setattr(format_pack, "profile_for_pack", refuse)
    with pytest.raises(BuildRefused) as exc:
        hb_pack.pack().build(H.fixture_doc(), tmp_path / "f.xlsx", options={})
    assert exc.value.kind == "profile"
    assert not (tmp_path / "f.xlsx").exists()


def test_build_refusals_are_pack_neutral(tmp_path, doc):
    from estimating_tools.exchange.types import BuildRefused
    p = hb_pack.pack()
    with pytest.raises(BuildRefused) as exc:
        p.build({"estimate": {}}, tmp_path / "x.xlsx", options={})
    assert exc.value.kind == "payload"
    with pytest.raises(BuildRefused) as exc:
        p.build(doc, tmp_path / "x.xlsx", options={"style": str(tmp_path / "nope")})
    assert exc.value.kind == "style"
    with pytest.raises(BuildRefused) as exc:
        p.build(doc, tmp_path / "x.xlsx", options={"host": "http://x"})
    assert exc.value.kind == "host"
    assert not (tmp_path / "x.xlsx").exists()
