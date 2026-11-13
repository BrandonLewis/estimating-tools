"""An exact MATCH answers from a per-range index: the same positions as a
linear search, text case-blind, the first of duplicates, wildcards searched."""
from __future__ import annotations

from openpyxl import Workbook

from estimating_tools.xlcalc import functions as Fn
from estimating_tools.xlcalc.book import Book
from estimating_tools.xlcalc.evaluate import evaluate


def _results(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    for n, v in enumerate(["ITEM:1", "item:2", 3, "ITEM:1", True, None, "A*B"], start=1):
        if v is not None:
            ws[f"A{n}"] = v
    lookups = ['"ITEM:1"', '"Item:2"', "3", "TRUE", '"nope"', '"A~*B"', '"IT*:2"', '"A*B"']
    for n, key in enumerate(lookups, start=1):
        ws[f"C{n}"] = f"=MATCH({key},$A:$A,0)"
    path = tmp_path / "m.xlsx"
    wb.save(path)
    out = evaluate(Book.load(path))
    return [out[("S", n, 3)] for n in range(1, len(lookups) + 1)]


def test_the_index_answers_as_the_linear_search_does(tmp_path, monkeypatch):
    indexed = _results(tmp_path)
    monkeypatch.setattr(Fn, "_exact_index", lambda rng: None)      # force the linear path
    assert [str(v) for v in _results(tmp_path)] == [str(v) for v in indexed]
    assert indexed[:4] == [1.0, 2.0, 3.0, 5.0]
    assert str(indexed[4]) == "#N/A" and indexed[5:] == [7.0, 2.0, 7.0]


def test_one_index_per_range(tmp_path, monkeypatch):
    built = []
    real = Fn._exact_index

    def counting(rng):
        index = real(rng)
        built.append((rng.sheet, rng.top, rng.left, rng.bottom, rng.right))
        return index
    monkeypatch.setattr(Fn, "_exact_index", counting)
    _results(tmp_path)
    assert len(set(built)) == 1


#: (a range value, a lookup) where str.lower() and the linear search's
#: case-blind regex can disagree: dotted capital I, sharp s, the Kelvin sign,
#: Greek final sigma. Each pair is also tried the other way round.
UNICODE = [("\u0130STANBUL", "istanbul"), ("\u00df", "SS"), ("\u212a", "k"),
           ("\u03a3\u039f\u03a3", "\u03c3\u03bf\u03c2"), ("\u03c3\u03bf\u03c2", "\u03c3\u03bf\u03c3")]
CASES = UNICODE + [(b, a) for a, b in UNICODE]


def _unicode_results(tmp_path):
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    for n, (value, lookup) in enumerate(CASES):
        col = get_column_letter(2 * n + 1)
        ws[f"{col}1"], ws[f"{col}2"] = "plain", value
        ws[f"{get_column_letter(2 * n + 2)}1"] = f'=MATCH("{lookup}",${col}$1:${col}$2,0)'
    path = tmp_path / "u.xlsx"
    wb.save(path)
    out = evaluate(Book.load(path))
    return [str(out[("S", 1, 2 * n + 2)]) for n in range(len(CASES))]


def test_unicode_text_matches_as_the_linear_search_does(tmp_path, monkeypatch):
    indexed = _unicode_results(tmp_path)
    monkeypatch.setattr(Fn, "_exact_index", lambda rng: None)      # force the linear path
    linear = _unicode_results(tmp_path)
    assert indexed == linear
    assert linear[0] == "2.0"               # the case reported: İSTANBUL found by istanbul


def test_ascii_ranges_keep_the_index(tmp_path, monkeypatch):
    got = []
    real = Fn._exact_index
    monkeypatch.setattr(Fn, "_exact_index", lambda rng: got.append(real(rng)) or got[-1])
    _results(tmp_path)
    assert got and all(isinstance(i, dict) for i in got)
    got.clear()
    _unicode_results(tmp_path)
    # an ASCII lookup into a non-ASCII range asks for the index and gets none
    assert got and all(i is None for i in got)
