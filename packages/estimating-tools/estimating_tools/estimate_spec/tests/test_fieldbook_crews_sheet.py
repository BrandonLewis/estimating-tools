"""The Crews sheet: BidSheet.ai's crew copies, read-only (fieldbook spec,
Decision 7). Nothing on it is bound, so nothing on it is ever sent."""
from openpyxl import load_workbook

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.estimate_spec.tests._fieldbook import EXAMPLE, fieldbook_pack


def _rows(ws):
    return [[c.value for c in row[:4]] for row in ws.iter_rows()]


def test_the_crews_sheet_lists_each_crew_and_its_members(tmp_path):
    ws = load_workbook(X.book(tmp_path))["Crews"]
    rows = _rows(ws)
    assert ["Pipe crew", "PIPE", None, 257.4] in rows
    assert ["Superintendent", None, 1, 95] in rows
    assert ["Pipelayer", None, 2, 81.2] in rows


def test_the_crews_sheet_binds_nothing(tmp_path):
    ws = load_workbook(X.book(tmp_path))["Crews"]
    assert [c.coordinate for row in ws.iter_rows(min_col=5, max_col=26)
            for c in row if c.value is not None] == []


def test_a_book_without_crews_has_no_crews_sheet():
    import yaml
    cfg = yaml.safe_load(EXAMPLE.read_text())
    cfg.pop("crews", None)
    wb = B.generate(cfg, fieldbook_pack())
    assert "Crews" not in wb.sheetnames


def test_a_spec_that_keeps_its_crews_has_no_crews_sheet():
    """The Crews sheet is the read model's crew copies (R5: gated on
    ``crew_copies``); a spec's own ``crews:`` (the seed's) is not shown."""
    import yaml
    cfg = yaml.safe_load(EXAMPLE.read_text())
    seed = yaml.safe_load((EXAMPLE.parent.parent / "seed.yaml").read_text())
    cfg["crews"] = seed["crews"]
    assert cfg["crews"] and "crew_copies" not in cfg
    wb = B.generate(cfg, fieldbook_pack())
    assert "Crews" not in wb.sheetnames


def test_a_read_model_crew_member_without_a_rate_row_still_builds():
    from estimating_tools.estimate_spec import identity
    from estimating_tools.estimate_spec.from_model import from_model
    doc = X.payload()
    doc["crews"][0]["members"][0]["classification"] = "Flagger"
    base = identity.Baseline(payload=doc, host=X.HOST, exported_at=X.EXPORTED_AT)
    wb = B.generate(from_model(doc), fieldbook_pack(), exchange=base)
    assert "Flagger" in [row[0] for row in _rows(wb["Crews"])]
