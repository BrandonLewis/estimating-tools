from __future__ import annotations

import json

import pytest

from estimating_tools.estimate_spec import cli

FIXTURE = __import__("pathlib").Path(__file__).parent / "fixtures" / "workbook.json"


def test_build_writes_the_workbook(tmp_path, capsys):
    out = tmp_path / "hc.xlsx"
    rc = cli.main(["heavybook", "build", str(FIXTURE), "-o", str(out),
                   "--exported-at", "2026-10-20T09:00:00Z"])
    assert rc == 0 and out.exists()
    assert "WROTE:" in capsys.readouterr().out


def test_default_output_sits_next_to_the_json(tmp_path):
    src = tmp_path / "e76.workbook.json"
    src.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["heavybook", "build", str(src), "--exported-at", "x"]) == 0
    assert (tmp_path / "e76.workbook.xlsx").exists()


def test_bad_payload_exits_nonzero_without_a_file(tmp_path, capsys):
    src = tmp_path / "bad.json"
    src.write_text(json.dumps({"estimate": {}}), encoding="utf-8")
    out = tmp_path / "bad.xlsx"
    assert cli.main(["heavybook", "build", str(src), "-o", str(out)]) == 1
    assert not out.exists()
    assert "payload" in capsys.readouterr().err


WARNING = "the book's look is its template now"


def test_a_style_pack_is_ignored_with_a_warning(tmp_path, capsys):
    style_dir = tmp_path / "style"
    style_dir.mkdir()
    (style_dir / "sheets.yaml").write_text("columns:\n  cost_report:\n    v: {width: 3}\n")
    out = tmp_path / "x.xlsx"
    assert cli.main(["heavybook", "build", str(FIXTURE), "-o", str(out),
                     "--style", str(style_dir), "--exported-at", "x"]) == 0
    assert out.exists()
    assert WARNING in capsys.readouterr().err


def test_invalid_json_exits_nonzero(tmp_path, capsys):
    src = tmp_path / "x.json"
    src.write_text("{nope", encoding="utf-8")
    assert cli.main(["heavybook", "build", str(src)]) == 1
    assert "invalid JSON" in capsys.readouterr().err


def _profile(tmp_path, text):
    prof = tmp_path / "profile"
    prof.mkdir()
    (prof / "profile.yaml").write_text(text, encoding="utf-8")
    return prof


def test_a_profile_style_is_ignored_with_a_warning(tmp_path, monkeypatch, capsys):
    prof = _profile(tmp_path, "estimating:\n  heavycivil_style: org-style\n")
    monkeypatch.setenv("ESTIMATING_PROFILES", str(prof))
    out = tmp_path / "x.xlsx"
    assert cli.main(["heavybook", "build", str(FIXTURE), "-o", str(out),
                     "--exported-at", "x"]) == 0
    assert out.exists()
    assert WARNING in capsys.readouterr().err


@pytest.mark.parametrize("text", ["estimating:\n  heavycivil_style: 5\n",
                                  "estimating: [unclosed\n"])
def test_a_profile_that_does_not_load_no_longer_stops_the_build(tmp_path, monkeypatch, text):
    """The profile is read only to warn about ``heavycivil_style``: one
    dropped by validation, or one that does not load, shapes nothing."""
    prof = _profile(tmp_path, text)
    monkeypatch.setenv("ESTIMATING_PROFILES", str(prof))
    out = tmp_path / "x.xlsx"
    assert cli.main(["heavybook", "build", str(FIXTURE), "-o", str(out),
                     "--exported-at", "x"]) == 0
    assert out.exists()


def test_build_reads_the_profile_through_the_strict_loader(tmp_path, monkeypatch):
    from estimating_tools.estimate_spec import format_pack
    seen = []

    def refuse(field="format"):
        seen.append(field)
        raise format_pack.FormatPackError("profile broken")

    # The alias runs the pack's build, which loads the profile itself.
    monkeypatch.setattr(format_pack, "profile_for_pack", refuse)
    out = tmp_path / "x.xlsx"
    assert cli.main(["heavybook", "build", str(FIXTURE), "-o", str(out),
                     "--exported-at", "x"]) == 0
    assert seen == ["heavycivil_style"] and out.exists()


def test_style_flag_skips_the_profile(tmp_path, monkeypatch):
    from estimating_tools.estimate_spec import format_pack

    def refuse(field="format"):
        raise AssertionError("profile read despite --style")

    monkeypatch.setattr(format_pack, "profile_for_pack", refuse)
    style_dir = tmp_path / "style"
    style_dir.mkdir()
    (style_dir / "tokens.yaml").write_text("fills: {input: 'E8F0FE'}\n")
    out = tmp_path / "x.xlsx"
    assert cli.main(["heavybook", "build", str(FIXTURE), "-o", str(out), "--style",
                     str(style_dir), "--exported-at", "x"]) == 0


def test_build_merges_pages(tmp_path):
    import copy
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    a, b = copy.deepcopy(doc), copy.deepcopy(doc)
    ids = [i["id"] for i in doc["items"]]
    a["items"] = [i for i in doc["items"] if i["id"] in ids[:2]]
    b["items"] = [i for i in doc["items"] if i["id"] in ids[2:]]
    pa, pb = tmp_path / "e.p1.json", tmp_path / "e.p2.json"
    pa.write_text(json.dumps(a), encoding="utf-8")
    pb.write_text(json.dumps(b), encoding="utf-8")
    out = tmp_path / "e.xlsx"
    assert cli.main(["heavybook", "build", str(pa), str(pb), "-o", str(out),
                     "--exported-at", "x"]) == 0
    assert out.exists()
    # The book carries the merged payload, not either page.
    from openpyxl import load_workbook

    from estimating_tools.exchange import baseline
    from estimating_tools.exchange.model import merge_pages
    ws = load_workbook(out)["_wb"]
    meta = json.loads(ws["A1"].value)["baseline"]
    chunks = [ws[f"B{n}"].value for n in range(1, meta["chunks"] + 1)]
    assert baseline.decode(chunks, meta) == merge_pages([a, b])


def test_a_non_json_value_the_model_ignores_is_refused_cleanly(tmp_path, capsys):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["unread_field"] = float("nan")              # json.dumps writes NaN; json.loads reads it
    src, out = tmp_path / "e.json", tmp_path / "e.xlsx"
    src.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main(["heavybook", "build", str(src), "-o", str(out), "--exported-at", "x"]) == 1
    assert "payload refused" in capsys.readouterr().err
    assert not out.exists()


def test_default_output_drops_the_page_suffix(tmp_path):
    src = tmp_path / "e76.workbook.p1.json"
    src.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["heavybook", "build", str(src), "--exported-at", "x"]) == 0
    assert (tmp_path / "e76.workbook.xlsx").exists()


def test_unreadable_file_exits_nonzero(tmp_path, capsys):
    out = tmp_path / "x.xlsx"
    # A directory cannot be read as a file (OSError, not FileNotFoundError).
    assert cli.main(["heavybook", "build", str(tmp_path), "-o", str(out)]) == 1
    assert "could not read" in capsys.readouterr().err
    assert not out.exists()


def test_non_utf8_file_exits_nonzero(tmp_path, capsys):
    src = tmp_path / "x.json"
    src.write_bytes(b'{"estimate": "\xff\xfe"}')
    out = tmp_path / "x.xlsx"
    assert cli.main(["heavybook", "build", str(src), "-o", str(out)]) == 1
    assert f"could not read {src}" in capsys.readouterr().err
    assert not out.exists()


def test_out_of_range_date_is_a_payload_refusal(tmp_path, capsys):
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc["activities"][0]["start_date"] = "0001-01-01"
    src = tmp_path / "x.json"
    src.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "x.xlsx"
    assert cli.main(["heavybook", "build", str(src), "-o", str(out)]) == 1
    assert "payload refused" in capsys.readouterr().err
    assert not out.exists()


def test_the_heavycivil_alias_is_retired_with_a_pointer(tmp_path, capsys):
    """``heavycivil`` was renamed in 0.1.96 and kept as an alias for a
    release; it is gone, and says what to run instead."""
    out = tmp_path / "a.xlsx"
    assert cli.main(["heavycivil", "build", str(FIXTURE), "-o", str(out)]) == 2
    assert "est-estimate heavybook build|read" in capsys.readouterr().err
    assert not out.exists()
