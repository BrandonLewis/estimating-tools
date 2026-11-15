"""A fieldbook built from the read model takes BidSheet.ai's data as the
server sends it (delivery 2, final review): null numbers are 0 (R11),
duplicate item numbers build (R12), crews sharing a code build (R13), text
that starts with "=" stays text (R14), and a stamp past one cell is a
refusal (R9). Each builds through the registered pack's ``build``."""
from __future__ import annotations

import pytest
from openpyxl import load_workbook

from estimating_tools import xlcalc
from estimating_tools.estimate_spec import pack as fieldbook_pack_mod
from estimating_tools.estimate_spec.from_model import from_model
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.types import BuildRefused

OPTIONS = {"exported_at": X.EXPORTED_AT, "host": X.HOST}


def _resource(doc, rid):
    return next(r for r in doc["resources"] if r["id"] == rid)


def _build(tmp_path, doc):
    out = tmp_path / "b.xlsx"
    fieldbook_pack_mod.pack().build(doc, out, options=OPTIONS)
    xlcalc.cache_or_warn(out)
    return out


def _row(ws, text, col="A"):
    return next(c.row for c in ws[col] if c.value == text)


def _texts(path):
    """Every string a cell holds, as written and as cached."""
    for data_only in (False, True):
        for ws in load_workbook(path, data_only=data_only):
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str):
                        yield ws.title, c.coordinate, c.value


# ---- R11: a null number from the server is 0 ------------------------------

def _null_item_qty(doc):
    doc["items"][0]["quantity"] = None


def _null_crew_qty(doc):
    _resource(doc, 31)["quantity"] = None


def _null_library_rate(doc):
    doc["rates"]["labor"][0]["rate"] = None


def _null_local_cost(doc):
    _resource(doc, 35)["unit_cost"] = None


def _null_line_qty(doc):
    _resource(doc, 34)["quantity"] = None


def _null_line_cost(doc):
    _resource(doc, 34)["unit_cost"] = None


@pytest.mark.parametrize("edit, sheet, label, col", [
    (_null_item_qty, X.ITEM1, None, "G"),                     # G1, the bid qty
    (_null_crew_qty, X.ITEM1, "Superintendent", "D"),         # the crew row's count
    (_null_library_rate, "Rates", "Superintendent", "G"),
    (_null_local_cost, "Rates", "Laborer (local)", "G"),
    (_null_line_qty, X.ITEM2, "8-inch ductile iron pipe", "B"),
    (_null_line_cost, X.ITEM2, "8-inch ductile iron pipe", "G"),
], ids=["item quantity", "crew quantity", "library rate", "local unit cost",
        "line quantity", "line unit cost"])
def test_a_null_server_number_is_written_as_zero(tmp_path, edit, sheet, label, col):
    doc = X.payload()
    edit(doc)
    path = _build(tmp_path, doc)
    assert [t for t in _texts(path) if "None" in t[2]] == []
    ws = load_workbook(path)[sheet]
    row = 1 if label is None else _row(ws, label)
    assert ws[f"{col}{row}"].value == 0


# ---- R12: duplicate item numbers build ------------------------------------

def test_two_items_numbered_alike_build(tmp_path):
    doc = X.payload()
    doc["items"][1]["item_number"] = "1"
    wb = load_workbook(_build(tmp_path, doc), data_only=True)
    sheets = [i["sheet"] for i in from_model(doc)["items"]]
    assert sheets == [X.ITEM1, "1 - 8-INCH WATER MAIN"]
    assert all(s in wb.sheetnames for s in sheets)
    bid_form = wb["Bid Form"]
    assert [bid_form[f"A{r}"].value for r in (5, 6)] == [1, 1]
    r11 = [[c.value for c in row[:6]] for row in wb["Checks"].iter_rows() if row[0].value == 11]
    assert [r[5] for r in r11] == ["✓", "✓"]


def test_an_item_sheet_named_with_a_bang_builds(tmp_path):
    """The per-item keys carry the sheet name, which may hold a "!" (Excel
    allows it); the cross-sheet refs that name those keys still resolve."""
    doc = X.payload()
    doc["items"][0]["description"] = "Mobilize!"
    wb = load_workbook(_build(tmp_path, doc), data_only=True)
    assert "1 - MOBILIZE!" in wb.sheetnames
    r6 = [[c.value for c in row[:6]] for row in wb["Checks"].iter_rows() if row[0].value == 6]
    assert [r[5] for r in r6] == ["✓", "✓"]


# ---- R13: crews sharing a code build --------------------------------------

def _second_pipe_crew(doc):
    crew = {**doc["crews"][0], "id": 42, "name": "Pipe crew, night", "v": "e000000000000042",
            "members": [{**m, "id": m["id"] + 10} for m in doc["crews"][0]["members"]]}
    doc["crews"].append(crew)


def test_crews_sharing_a_code_get_unique_ids_in_payload_order():
    doc = X.payload()
    _second_pipe_crew(doc)
    crews = from_model(doc)["crews"]
    assert [c["id"] for c in crews] == ["PIPE", "PIPE (2)"]
    assert [c["code"] for c in crews] == ["PIPE", "PIPE"]


def test_crews_sharing_a_code_build_and_each_shows_its_own_code(tmp_path):
    doc = X.payload()
    _second_pipe_crew(doc)
    ws = load_workbook(_build(tmp_path, doc))["Crews"]
    rows = [[c.value for c in row[:2]] for row in ws.iter_rows()]
    assert ["Pipe crew", "PIPE"] in rows and ["Pipe crew, night", "PIPE"] in rows


# ---- R14: server text that starts with "=" is text ------------------------

FORMULA = '=HYPERLINK("http://x","click")'


def test_server_text_starting_with_equals_lands_as_text(tmp_path):
    doc = X.payload()
    doc["items"][0]["description"] = FORMULA
    _resource(doc, 34)["name"] = "=1+1"            # the pipe line, on item 2
    path = _build(tmp_path, doc)
    wb = load_workbook(path)
    sheet = from_model(doc)["items"][0]["sheet"]
    assert sheet in wb.sheetnames and len(sheet) <= 31
    assert not any(ch in sheet for ch in "[]:*?/\\")
    ws = wb[sheet]
    assert ws["B1"].value == FORMULA and ws["B1"].data_type != "f"
    line = wb[X.ITEM2][f"A{_row(wb[X.ITEM2], '=1+1')}"]
    assert line.data_type != "f"
    bid_form = wb["Bid Form"]
    (desc,) = [c for c in bid_form["B"] if c.value == FORMULA]
    assert desc.data_type != "f"
    landed = [(ws.title, c.data_type) for ws in wb for row in ws.iter_rows() for c in row
              if c.value in (FORMULA, "=1+1")]       # formulas naming the sheet are not it
    assert {t for t, _ in landed} >= {sheet, X.ITEM2, "Bid Form", "Cost Summary"}
    assert [d for _, d in landed if d == "f"] == []


# ---- rule 11 against timed equipment (BidManager #1701) -------------------

def test_rule_11_fails_an_item_whose_server_prices_equipment_as_qty_times_cost(tmp_path):
    """Until BidManager #1701, BidSheet.ai prices timed equipment as quantity
    x unit cost; fieldbook prices it as count x days x shift hours x rate. So
    an item with timed equipment shows a rule-11 cross on a real estimate."""
    doc = X.payload()
    pipelayer = 2 * 16 * 81.20                       # count x hours x rate
    excavator = 1 * 145.00                           # quantity x unit cost (pre-#1701)
    pipe = 640 * 42.00
    next(a for a in doc["activities"] if a["id"] == 22)["cost"] = f"{pipelayer + excavator + pipe:.2f}"
    wb = load_workbook(_build(tmp_path, doc), data_only=True)
    r11 = [[c.value for c in row[:6]] for row in wb["Checks"].iter_rows() if row[0].value == 11]
    assert [(str(r[2]), r[5]) for r in r11] == [("1", "✓"), ("2", "✗")]


# ---- R9: a stamp past one cell is a refusal -------------------------------

def test_a_stamp_past_one_cell_is_a_payload_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(exchange_stamp, "CELL_LIMIT", 100)
    out = tmp_path / "b.xlsx"
    with pytest.raises(BuildRefused) as exc:
        fieldbook_pack_mod.pack().build(X.payload(), out, options=OPTIONS)
    assert exc.value.kind == "payload"
    assert "100 per cell" in str(exc.value)
    assert not out.exists()


# ---- an untimed labor or equipment resource is a priced line --------------

def _untimed(doc, ctype):
    """Activity 21's one resource priced as a lump: quantity 1 at 95, no time."""
    res = _resource(doc, 31)
    res.update(component_type=ctype, time_value=None, time_unit="", quantity="1",
               unit_cost="95.00", labor_rate_id=None, equipment_rate_id=None,
               name="Supervision, lump" if ctype == "labor" else "Light plant, lump")
    next(a for a in doc["activities"] if a["id"] == 21)["cost"] = "95.00"
    return res["name"]


@pytest.mark.parametrize("ctype, shown, lane", [("labor", "Labor", "L"),
                                                ("equipment", "Equipment", "M")])
def test_an_untimed_resource_builds_as_a_priced_line(tmp_path, ctype, shown, lane):
    doc = X.payload()
    name = _untimed(doc, ctype)
    wb = load_workbook(_build(tmp_path, doc), data_only=True)
    ws = wb[X.ITEM1]
    r = _row(ws, name)
    assert ws[f"Q{r}"].value == "LINE" and ws[f"H{r}"].value == shown
    assert (ws[f"B{r}"].value, ws[f"G{r}"].value) == (1, 95)
    assert ws[f"{lane}{r}"].value == 95 and ws[f"P{r}"].value == 95
    rows = [[c.value for c in row[:6]] for row in wb["Checks"].iter_rows()]
    by_rule = {n: [x[5] for x in rows if x[0] == n and str(x[2]) == "1"] for n in (3, 5, 11)}
    assert by_rule == {3: ["✓"], 5: ["✓"], 11: ["✓"]}


# ---- library rates sharing a name -----------------------------------------

def test_a_crew_row_prices_from_its_own_rate_when_library_names_repeat(tmp_path):
    """Two library Pipelayers: the crew row on labor:4 prices at $99, not the
    first Pipelayer's $81.20, and a rebuild from a reordered payload keeps
    every rate name where it was."""
    from estimating_tools.estimate_spec.tests.test_fieldbook_from_model import _second_pipelayer

    books = []
    for n, first in enumerate((False, True)):
        out = tmp_path / str(n)
        out.mkdir()
        books.append(load_workbook(_build(out, _second_pipelayer(X.payload(), first=first)),
                                   data_only=True))
    for wb in books:
        ws = wb["2 - 8-INCH WATER MAIN"]
        r = _row(ws, "Pipelayer (2)")
        assert ws[f"G{r}"].value == 99
    names = [[c.value for c in wb["Rates"]["A"]] for wb in books]
    assert names[0] == names[1] and "Pipelayer (2)" in names[0]
