"""The payload a book was built from rides in ``_wb`` column B."""
from __future__ import annotations

import base64
import hashlib
import json
import zlib

import pytest

from estimating_tools.heavycivil import baseline, build, style


def test_round_trip(doc):
    chunks, meta = baseline.encode(doc)
    assert meta["encoding"] == "zlib+base64"
    assert meta["chunks"] == len(chunks) == 1
    assert baseline.decode(chunks, meta) == doc


def test_checksum_is_of_the_canonical_json(doc):
    _, meta = baseline.encode(doc)
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert meta["sha256"] == hashlib.sha256(raw).hexdigest()
    reordered = dict(reversed(list(doc.items())))
    assert baseline.encode(reordered)[1]["sha256"] == meta["sha256"]


def test_long_baseline_is_cut_into_chunks(doc, monkeypatch):
    monkeypatch.setattr(baseline, "CHUNK", 1000)
    chunks, meta = baseline.encode(doc)
    assert meta["chunks"] == len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert baseline.decode(chunks, meta) == doc


def test_wrong_chunk_count_is_refused(doc, monkeypatch):
    monkeypatch.setattr(baseline, "CHUNK", 1000)
    chunks, meta = baseline.encode(doc)
    with pytest.raises(baseline.BaselineError, match="chunk"):
        baseline.decode(chunks[:-1], meta)


def test_tampered_baseline_is_refused(doc):
    chunks, meta = baseline.encode(doc)
    edited = dict(doc, estimate=dict(doc["estimate"], name="Edited"))
    forged = base64.b64encode(zlib.compress(json.dumps(edited).encode("utf-8"))).decode("ascii")
    with pytest.raises(baseline.BaselineError, match="checksum"):
        baseline.decode([forged], meta)
    with pytest.raises(baseline.BaselineError, match="decode"):
        baseline.decode(["not base64!"], meta)


@pytest.mark.parametrize("meta", [None, {}, {"encoding": "gzip", "chunks": 1, "sha256": ""}])
def test_missing_baseline_is_refused(meta):
    with pytest.raises(baseline.BaselineError, match="no baseline"):
        baseline.decode([], meta)


def _forge(payload_bytes, meta):
    text = base64.b64encode(zlib.compress(payload_bytes)).decode("ascii")
    return [text], dict(meta, sha256=hashlib.sha256(payload_bytes).hexdigest())


@pytest.mark.parametrize("bad", [None, 5])
def test_non_text_chunk_is_named(doc, bad):
    chunks, meta = baseline.encode(doc)
    with pytest.raises(baseline.BaselineError, match=r"chunk 1 \(_wb!B1\) is not text"):
        baseline.decode([bad], meta)


@pytest.mark.parametrize("count", [True, "1", 1.0, None])
def test_chunk_count_must_be_a_real_int(doc, count):
    chunks, meta = baseline.encode(doc)
    with pytest.raises(baseline.BaselineError, match="chunk"):
        baseline.decode(chunks, dict(meta, chunks=count))


def test_chunk_count_message_grammar(doc):
    chunks, meta = baseline.encode(doc)
    with pytest.raises(baseline.BaselineError) as e:
        baseline.decode([], meta)
    assert "1 chunks" not in str(e.value)


@pytest.mark.parametrize("payload", [b"\xff\xfe not utf-8", b"{not json", b"[1, 2]", b"null"])
def test_forged_payloads_are_baseline_errors(doc, payload):
    _, meta = baseline.encode(doc)
    chunks, forged_meta = _forge(payload, meta)
    with pytest.raises(baseline.BaselineError):
        baseline.decode(chunks, forged_meta)


def test_decompression_bomb_is_refused(doc, monkeypatch):
    _, meta = baseline.encode(doc)
    chunks, forged_meta = _forge(b"[" + b"0," * 100000 + b"0]", meta)
    monkeypatch.setattr(baseline, "MAX_BYTES", 1000)
    with pytest.raises(baseline.BaselineError, match="too large"):
        baseline.decode(chunks, forged_meta)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1, 2}, object()])
def test_non_json_values_fail_at_build(doc, value):
    with pytest.raises(baseline.BaselineError):
        baseline.encode(dict(doc, extra=value))


def test_chunk_fits_an_excel_cell():
    assert baseline.CHUNK <= 32767


def test_decoded_baseline_parses_like_the_original(doc):
    from estimating_tools.heavycivil import model
    assert model.parse(baseline.decode(*baseline.encode(doc))) == model.parse(doc)


def test_truncated_stream_is_refused(doc):
    raw = b"{" + b'"a":1,' * 5000 + b'"b":2}'
    full = zlib.compress(raw)
    text = base64.b64encode(full[:len(full) // 2]).decode("ascii")
    meta = {"encoding": "zlib+base64", "chunks": 1, "sha256": hashlib.sha256(raw).hexdigest()}
    with pytest.raises(baseline.BaselineError, match="decode"):
        baseline.decode([text], meta)


def test_book_carries_the_payload_it_was_built_from(doc, book):
    meta = json.loads(book["_wb"]["A1"].value)["baseline"]
    ws = book["_wb"]
    chunks = [ws[f"B{n}"].value for n in range(1, meta["chunks"] + 1)]
    assert ws[f"B{meta['chunks'] + 1}"].value is None
    assert baseline.decode(chunks, meta) == doc


def test_large_payload_spreads_over_cells_under_excels_limit(doc):
    base = list(doc["resources"])
    next_id = max(r["id"] for r in base) + 1
    for _ in range(200):
        for r in base:
            # A version hash per row, as BidSheet.ai sends: it does not compress.
            v = hashlib.sha256(str(next_id).encode("ascii")).hexdigest()
            doc["resources"].append(dict(r, id=next_id, v=v))
            next_id += 1
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    meta = json.loads(book["_wb"]["A1"].value)["baseline"]
    chunks = [book["_wb"][f"B{n}"].value for n in range(1, meta["chunks"] + 1)]
    assert meta["chunks"] > 1
    assert all(len(c) <= baseline.CHUNK for c in chunks)
    assert baseline.decode(chunks, meta) == doc


def test_a_chunk_starting_with_equals_is_stored_as_text(doc, monkeypatch):
    """Base64 padding can make the last chunk "==" -- text, never a formula."""
    real = baseline.encode

    def padded(d):
        chunks, meta = real(d)
        return chunks + ["=="], dict(meta, chunks=meta["chunks"] + 1)

    monkeypatch.setattr(baseline, "encode", padded)
    book = build.build(doc, style=style.load_style(), exported_at="x", host="h")
    cell = book["_wb"]["B2"]
    assert cell.value == "==" and cell.data_type == "s"
