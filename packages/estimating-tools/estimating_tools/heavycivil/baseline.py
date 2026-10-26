"""The payload a HeavyCivil book was built from, carried in the book.

Read-back compares the edited book against this baseline, not a re-fetch: a
re-fetch cannot tell an estimator's edit from a BidSheet.ai change since
export. ``encode(doc)`` gives the cells for ``_wb`` column B (B1 downward)
and the meta the layout JSON carries; ``decode(chunks, meta)`` reverses it
and refuses a baseline that does not match its meta.

The JSON is canonical (sorted keys, no spaces), zlib-compressed and
base64-encoded, cut into chunks of at most ``CHUNK`` characters (Excel caps
a cell at 32,767). The checksum is of the JSON bytes, not the compressed
ones: zlib builds (zlib, zlib-ng) may compress the same bytes differently,
so only the decoded payload is pinned.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib

ENCODING = "zlib+base64"
CHUNK = 32000
MAX_BYTES = 256 * 1024 * 1024  # decompressed ceiling; a bomb is refused


class BaselineError(ValueError):
    """The book's baseline is missing or does not match its meta."""


def _json_bytes(doc):
    try:
        return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BaselineError(f"the payload is not plain JSON: {exc}") from None


def encode(doc):
    """(chunks, meta) for ``doc``: the text for ``_wb!B1``, ``B2``, ... and
    ``{"encoding", "chunks", "sha256"}`` for the layout JSON. A value JSON
    cannot carry (NaN, a set, a Decimal) fails here, at build time."""
    raw = _json_bytes(doc)
    text = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
    chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    meta = {"encoding": ENCODING, "chunks": len(chunks),
            "sha256": hashlib.sha256(raw).hexdigest()}
    return chunks, meta


def decode(chunks, meta):
    """The payload from its chunks (``_wb`` B1 downward, in order). Every
    failure is a BaselineError."""
    if not isinstance(meta, dict) or meta.get("encoding") != ENCODING:
        raise BaselineError("no baseline in this book")
    chunks = list(chunks)
    want = meta.get("chunks")
    if isinstance(want, bool) or not isinstance(want, int) or len(chunks) != want:
        raise BaselineError(
            f"chunk count: found {len(chunks)}, the layout says {want!r}")
    for n, c in enumerate(chunks, 1):
        if not isinstance(c, str):
            raise BaselineError(f"chunk {n} (_wb!B{n}) is not text")
    try:
        packed = base64.b64decode("".join(chunks), validate=True)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(packed, MAX_BYTES)
    except (ValueError, zlib.error):
        raise BaselineError("the baseline does not decode") from None
    if inflater.unconsumed_tail:
        raise BaselineError("the baseline is too large")
    if not inflater.eof:
        raise BaselineError("the baseline does not decode")
    if hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
        raise BaselineError("the baseline does not match its checksum")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise BaselineError("the baseline does not decode") from None
    if not isinstance(doc, dict):
        raise BaselineError("the baseline is not a payload object")
    return doc
