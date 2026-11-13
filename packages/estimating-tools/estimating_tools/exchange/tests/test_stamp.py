from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from estimating_tools.exchange import baseline, stamp
from estimating_tools.heavybook.tests import _readback as H


def _make(**over):
    chunks, meta = baseline.encode({"estimate": {"id": 1, "v": "e"}, "items": []})
    args = dict(pack="heavybook", version="1", declaration={}, host="www.bidsheet.ai",
                estimate_id=1, estimate_v="e", exported_at="2026-11-04T00:00:00Z",
                baseline=meta, page=False, item_ids=None, extra={"layout": {"tabs": {}}})
    args.update(over)
    return stamp.make(**args)


def test_make_and_parse_round_trip():
    doc = _make(page=True, item_ids=[3, 4])
    st = stamp.parse(doc)
    assert st.contract == "1" and st.schema == stamp.SCHEMA_VERSION
    assert st.pack == {"name": "heavybook", "version": "1"}
    assert st.page is True and st.item_ids == [3, 4]
    assert st.extra == {"layout": {"tabs": {}}} and st.raw == doc
    assert json.loads(stamp.dumps(doc)) == doc


@pytest.mark.parametrize("damage", [
    lambda d: d.pop("baseline"), lambda d: d.pop("pack"), lambda d: d.__setitem__("schema", "1"),
    lambda d: d.__setitem__("item_ids", "3,4"), lambda d: d.__setitem__("page", 1),
    lambda d: d.__setitem__("contract", 1),
    lambda d: d.update(page=True, item_ids=[]),
    lambda d: d.pop("estimate_v"), lambda d: d.__setitem__("estimate_v", ""),
    lambda d: d.__setitem__("estimate_v", 3),
])
def test_parse_refuses_a_damaged_stamp(damage):
    doc = _make()
    damage(doc)
    with pytest.raises(stamp.StampError):
        stamp.parse(doc)


def test_parse_names_the_missing_estimate_version():
    doc = _make()
    doc.pop("estimate_v")
    with pytest.raises(stamp.StampError, match="does not name the estimate's version"):
        stamp.parse(doc)


def test_a_step1_layout_json_is_legacy():
    legacy = {"format": "heavybook", "layout_version": 2, "tabs": {}, "row_kinds": [],
              "baseline": {"encoding": "zlib+base64", "chunks": 1, "sha256": "x"}}
    assert stamp.is_legacy(legacy) and not stamp.is_legacy(_make())
    with pytest.raises(stamp.StampError, match="before"):
        stamp.parse(legacy)


def test_with_baseline_replaces_only_the_baseline_fields():
    doc = _make()
    new = stamp.with_baseline(doc, {"encoding": "zlib+base64", "chunks": 2, "sha256": "y"},
                              estimate_v="e2", exported_at="2026-11-05T00:00:00Z")
    assert new["baseline"]["chunks"] == 2 and new["estimate_v"] == "e2"
    assert new["exported_at"] == "2026-11-05T00:00:00Z"
    assert {k: v for k, v in new.items() if k not in ("baseline", "estimate_v", "exported_at")} \
        == {k: v for k, v in doc.items() if k not in ("baseline", "estimate_v", "exported_at")}
    assert doc["estimate_v"] == "e"                          # the input is not mutated


def test_a_stale_list_is_kept_and_only_grows():
    doc = _make()
    assert "stale" not in doc and stamp.parse(doc).stale == ()      # as built, and older stamps
    _chunks, meta = baseline.encode({"estimate": {"id": 1, "v": "f"}, "items": []})
    once = stamp.with_baseline(doc, meta, estimate_v="f", exported_at="x", stale=("shares",))
    assert stamp.parse(once).stale == ("shares",)
    twice = stamp.with_baseline(once, meta, estimate_v="g", exported_at="y", stale=("rates",))
    assert twice["stale"] == ["shares", "rates"]
    assert "stale" not in stamp.with_baseline(doc, meta, estimate_v="f", exported_at="x")
    with pytest.raises(stamp.StampError, match="stale list"):
        stamp.parse(dict(doc, stale="shares"))
    # stale_of agrees with parse: a malformed list is refused, never read
    # as none.
    for bad in ("shares", ["shares", 1]):
        with pytest.raises(stamp.StampError, match="stale list"):
            stamp.stale_of(dict(doc, stale=bad))
        with pytest.raises(stamp.StampError, match="stale list"):
            stamp.parse(dict(doc, stale=bad))


def test_page_of_reads_the_fetch_record():
    assert stamp.page_of({"items": []}) == (False, None)
    assert stamp.page_of({"_fetch": None}) == (False, None)
    assert stamp.page_of({"_fetch": {"item_ids": [4, 3]}}) == (True, [3, 4])


@pytest.mark.parametrize("rec", [
    {"item_ids": ["x"]}, {"item_ids": []}, {"item_ids": "3"}, {"item_ids": [True]},
    {"item_ids": None}, {}, "3", [3],
])
def test_page_of_refuses_a_malformed_fetch_record(rec):
    """A ``_fetch`` record that is there but wrong is a payload refusal, not
    a traceback (``HeavyBookPack.build`` maps it to ``BuildRefused``)."""
    from estimating_tools.exchange.model import PayloadError
    with pytest.raises(PayloadError, match="_fetch.item_ids"):
        stamp.page_of({"_fetch": rec})


def test_a_built_book_carries_the_stamp_under_both_names(tmp_path):
    path = H.build_book(H.fixture_doc(), tmp_path / "e1.xlsx")
    wb = load_workbook(path, read_only=True)
    assert list(wb.defined_names[stamp.NAME].destinations) == [("_wb", "$A$1")]
    assert "hc.layout" not in wb.defined_names      # only the code-built books had it
    st = stamp.read(path)
    assert st.pack["name"] == "heavybook" and st.page is False and st.item_ids is None
    assert st.host == "www.bidsheet.ai" and st.estimate_id == 1
    assert len(wb["_wb"]["A1"].value) < 32767


def _page_doc():
    """The fixture cut down to its first item, with the ``_fetch`` record
    ``fetch --items`` writes: ``(doc, item id)``."""
    doc = H.fixture_doc()
    item = doc["items"][0]["id"]
    doc["items"] = [doc["items"][0]]
    acts = {a["id"] for a in doc["activities"] if a["estimate_item_id"] == item}
    doc["activities"] = [a for a in doc["activities"] if a["id"] in acts]
    doc["resources"] = [r for r in doc["resources"] if r["activity_id"] in acts]
    doc["shares"] = [s for s in doc["shares"] if s["item_id"] == item]
    doc["elements"] = [e for e in doc["elements"]
                       if all(q.get("pay_item_id") in (item, None) for q in e["quantities"])]
    doc["_fetch"] = {"item_ids": [item]}
    return doc, item


def test_covered_says_page_or_whole(tmp_path):
    whole = H.build_book(H.fixture_doc(), tmp_path / "whole.xlsx")
    assert stamp.covered(whole) == (False, None)
    doc, item = _page_doc()
    page = H.build_book(doc, tmp_path / "page.xlsx")
    assert stamp.covered(page) == (True, [item])
    assert stamp.covered(tmp_path / "missing.xlsx") == (None, None)


def test_make_drops_the_item_ids_that_do_not_fit_the_cell():
    """Ten thousand ids are ~49 KB of JSON, past what Excel holds in one
    cell: the stamp keeps ``page`` and lets the baseline list the items."""
    doc = _make(page=True, item_ids=list(range(1, 10001)))
    assert doc["item_ids"] is None and doc["page"] is True
    assert len(stamp.dumps(doc)) <= stamp.CELL_LIMIT
    st = stamp.parse(doc)
    assert st.page is True and st.item_ids is None
    small = _make(page=True, item_ids=list(range(1, 101)))
    assert small["item_ids"] == list(range(1, 101))        # kept while they fit


def test_covered_reads_a_page_without_stamped_ids_from_the_baseline(tmp_path):
    doc, item = _page_doc()
    path = H.build_book(doc, tmp_path / "page.xlsx")
    wb = load_workbook(path)
    ws = wb["_wb"]
    stamped = json.loads(ws["A1"].value)
    assert stamped["page"] is True and stamped["item_ids"] == [item]
    stamped["item_ids"] = None
    ws["A1"] = stamp.dumps(stamped)
    wb.save(path)
    assert stamp.covered(path) == (True, [item])


def test_build_refuses_a_stamp_that_cannot_fit_the_cell(monkeypatch, tmp_path):
    """When the stamp is too long even without the ids, nothing is written:
    Excel would truncate the cell and the book would be refused on read."""
    from estimating_tools.exchange.types import BuildRefused
    from estimating_tools.heavybook import pack as hb_pack

    monkeypatch.setattr(stamp, "dumps", lambda doc: "x" * (stamp.CELL_LIMIT + 1))
    doc, _ = _page_doc()
    out = tmp_path / "big.xlsx"
    with pytest.raises(BuildRefused, match="Excel holds 32767 per cell"):
        hb_pack.pack().build(doc, out, options={"exported_at": "2026-10-20T09:00:00Z"})
    assert not out.exists()


def test_covered_falls_back_to_the_baseline_for_a_step1_book(tmp_path):
    """A book stamped before this task has no page flag: its baseline's items
    are its items, as ``covered_item_ids`` read them."""
    import shutil

    path = tmp_path / "old.xlsx"                  # a code-built book carries its layout
    shutil.copy(Path(H.__file__).parent / "fixtures" / "v1-book.xlsx", path)
    wb = load_workbook(path)
    ws = wb["_wb"]
    doc = json.loads(ws["A1"].value)
    legacy = dict(doc["extra"]["layout"], format="heavybook", estimate_id=1, estimate_v="e",
                  baseline=doc["baseline"])
    ws["A1"] = json.dumps(legacy, sort_keys=True)
    wb.save(path)
    assert stamp.covered(path) == (True, [1, 2, 3, 4, 5])
