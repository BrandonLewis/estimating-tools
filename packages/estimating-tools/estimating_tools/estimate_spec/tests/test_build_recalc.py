"""The calculating pass of `est-estimate build` is opt-in (#370): ``--recalc
{auto,excel,libreoffice,off}``, default ``off`` (the build already stored
cached values with the built-in evaluator, #445; no line). Asked for, it runs
and prints one line. The helper is replaced by a spy, so no test starts an
engine."""
from __future__ import annotations

from pathlib import Path

import pytest

from estimating_tools import xlsx_recalc
from estimating_tools.estimate_spec import cli
from estimating_tools.estimate_spec.tests._fieldbook import EXAMPLE, FIELDBOOK_DIR

HEAVYBOOK_JSON = (Path(__file__).resolve().parents[2] / "heavybook" / "tests" / "fixtures"
                  / "workbook.json")


@pytest.fixture
def spy(monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    calls = []

    def fake(path, *, engine="auto", auto_order=xlsx_recalc.AUTO_ORDER, **kw):
        calls.append({"path": Path(path), "engine": engine, "auto_order": tuple(auto_order)})
        assert Path(path).exists(), "the pass runs on the written book"
        return xlsx_recalc.RecalcResult("excel-com", "Excel (pywin32)")

    monkeypatch.setattr(xlsx_recalc, "recalculate", fake)
    return calls


def _fieldbook(tmp_path, *extra):
    out = tmp_path / "fb.xlsx"
    rc = cli.main(["build", str(EXAMPLE), "-o", str(out), "--format", str(FIELDBOOK_DIR),
                   *extra])
    return rc, out


def test_fieldbook_build_runs_no_engine_by_default(tmp_path, spy, capsys):
    rc, _ = _fieldbook(tmp_path)
    assert rc == 0 and spy == []
    printed = capsys.readouterr().out
    assert "WROTE:" in printed and "RECALC" not in printed


def test_fieldbook_build_recalcs_with_excel_only_in_auto(tmp_path, spy, capsys):
    rc, out = _fieldbook(tmp_path, "--recalc", "auto")
    assert rc == 0
    assert spy == [{"path": out, "engine": "auto", "auto_order": ("excel",)}]
    printed = capsys.readouterr().out
    assert "WROTE:" in printed
    assert printed.count("RECALC:") == 1 and "excel-com" in printed


@pytest.mark.parametrize("choice", ["excel", "libreoffice"])
def test_fieldbook_build_passes_the_choice(tmp_path, spy, choice):
    rc, _ = _fieldbook(tmp_path, "--recalc", choice)
    assert rc == 0 and spy[0]["engine"] == choice


def test_fieldbook_build_recalc_off_runs_nothing(tmp_path, spy, capsys):
    rc, _ = _fieldbook(tmp_path, "--recalc", "off")
    assert rc == 0 and spy == [] and "RECALC" not in capsys.readouterr().out


def test_an_unknown_choice_is_a_usage_error(tmp_path, spy):
    with pytest.raises(SystemExit) as exc:
        _fieldbook(tmp_path, "--recalc", "numbers")
    assert exc.value.code == 2 and spy == []


def test_a_failed_build_does_not_recalc(tmp_path, spy):
    rc = cli.main(["build", str(tmp_path / "missing.estimate.yaml"), "-o",
                   str(tmp_path / "x.xlsx"), "--format", str(FIELDBOOK_DIR),
                   "--recalc", "excel"])
    assert rc == 1 and spy == []


def test_heavybook_build_runs_no_engine_by_default(tmp_path, spy, capsys):
    out = tmp_path / "hb.xlsx"
    rc = cli.main(["heavybook", "build", str(HEAVYBOOK_JSON), "-o", str(out),
                   "--exported-at", "2026-10-20T09:00:00Z"])
    assert rc == 0 and spy == []
    assert "RECALC" not in capsys.readouterr().out


def test_heavybook_build_recalcs_with_excel_only_in_auto(tmp_path, spy, capsys):
    out = tmp_path / "hb.xlsx"
    rc = cli.main(["heavybook", "build", str(HEAVYBOOK_JSON), "-o", str(out),
                   "--exported-at", "2026-10-20T09:00:00Z", "--recalc", "auto"])
    assert rc == 0
    assert spy == [{"path": out, "engine": "auto", "auto_order": ("excel",)}]
    assert "RECALC:" in capsys.readouterr().out


def test_build_pack_heavybook_takes_the_flag(tmp_path, spy):
    out = tmp_path / "hb.xlsx"
    rc = cli.main(["build", "--pack", "heavybook", str(HEAVYBOOK_JSON), "-o", str(out),
                   "--exported-at", "2026-10-20T09:00:00Z", "--recalc", "libreoffice"])
    assert rc == 0
    assert spy[0]["engine"] == "libreoffice" and spy[0]["auto_order"] == ("excel",)


def test_the_suite_switch_leaves_the_book_as_written(tmp_path, capsys):
    """No spy: asked for Excel, the conftest's ESTIMATING_RECALC=off reaches
    the real helper, which runs nothing and says so."""
    out = tmp_path / "hb.xlsx"
    assert cli.main(["heavybook", "build", str(HEAVYBOOK_JSON), "-o", str(out),
                     "--exported-at", "2026-10-20T09:00:00Z", "--recalc", "excel"]) == 0
    assert "RECALC: off (ESTIMATING_RECALC=off)" in capsys.readouterr().out
