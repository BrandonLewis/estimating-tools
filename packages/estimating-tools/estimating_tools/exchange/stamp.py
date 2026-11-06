"""The stamp every pack's book carries (contract part 5): one short document
property for detection (``estimate_format: <pack> <major>``) and one JSON
cell under the workbook-scoped defined name ``exchange.stamp`` holding the
contract major, the pack, the declaration and its schema version, the host,
the estimate, the export time, whether the book is a page and which items
it covers, and how the baseline is stored (``exchange.baseline``'s meta; the
chunks sit in column B under the stamp cell). Packs put what only they read
under ``extra``.

Readers accept HeavyBook's ``hc.layout`` and fieldbook's ``est.layout`` as
names for books stamped before this document. A HeavyBook book built before
step 2 holds its layout JSON in the same cell (``is_legacy``): it has no
``schema`` key; ``parse`` refuses it, and HeavyBook's reader upgrades a
layout-2 one in memory (``heavybook.legacy``) or refuses it by layout
version. The upgrade is the pack's, so this module stays pack-neutral."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from estimating_tools.exchange import baseline

NAME = "exchange.stamp"
SHEET = "_wb"
CELL = "A1"
PROPERTY = "estimate_format"
CONTRACT = "1"
#: The declaration schema this package reads and writes (``exchange.declaration``).
SCHEMA_VERSION = 1
#: What Excel holds in one cell. A stamp longer than this would be truncated
#: on write and refused on read, so ``make`` drops a page's item ids (the
#: baseline lists them) to stay under it, and a build refuses a stamp that
#: still does not fit.
CELL_LIMIT = 32767


class StampError(ValueError):
    """The stamp cell does not hold a stamp this package reads."""


@dataclass(frozen=True)
class Stamp:
    contract: str
    pack: dict
    schema: int
    declaration: dict
    host: str
    estimate_id: object
    estimate_v: str
    exported_at: str
    page: bool
    item_ids: list | None
    baseline: dict
    extra: dict
    raw: dict


def dumps(doc: dict) -> str:
    """The cell text: canonical JSON (sorted keys, no spaces)."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str)


def make(*, pack: str, version: str, declaration: dict, host: str, estimate_id, estimate_v,
         exported_at: str, baseline: dict, page: bool = False, item_ids=None,
         extra: dict | None = None, contract: str = CONTRACT,
         schema: int = SCHEMA_VERSION) -> dict:
    """The stamp document a build writes. A page's ``item_ids`` are kept
    only while the whole stamp fits one cell (``CELL_LIMIT``); past that
    they are ``None`` and ``page`` stays true, and ``covered`` reads the
    page's items from the baseline."""
    doc = {"contract": contract, "pack": {"name": pack, "version": version},
           "schema": schema, "declaration": dict(declaration), "host": host,
           "estimate_id": estimate_id, "estimate_v": estimate_v, "exported_at": exported_at,
           "page": bool(page),
           "item_ids": None if item_ids is None else [int(i) for i in item_ids],
           "baseline": dict(baseline), "extra": dict(extra or {})}
    if doc["item_ids"] is not None and len(dumps(doc)) > CELL_LIMIT:
        doc["item_ids"] = None
    return doc


def is_legacy(doc) -> bool:
    """A step 1 HeavyBook layout JSON: a layout version and no schema."""
    return isinstance(doc, dict) and "schema" not in doc and "layout_version" in doc


def parse(doc) -> Stamp:
    """``Stamp`` from the cell's JSON object; ``StampError`` names what is wrong."""
    if not isinstance(doc, dict):
        raise StampError("the stamp is not a JSON object")
    if is_legacy(doc):
        raise StampError("this book was stamped before the exchange stamp (layout "
                         f"{doc.get('layout_version')!r})")
    pack = doc.get("pack")
    if not isinstance(pack, dict) or not isinstance(pack.get("name"), str) or not pack["name"]:
        raise StampError("the stamp names no pack")
    schema = doc.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int):
        raise StampError("the stamp has no schema version")
    if not isinstance(doc.get("contract"), str):
        raise StampError("the stamp has no contract major")
    if not isinstance(doc.get("baseline"), dict):
        raise StampError("the stamp has no baseline")
    page = doc.get("page", False)
    if not isinstance(page, bool):
        raise StampError("the stamp's page flag is not true or false")
    ids = doc.get("item_ids")
    if ids is not None and not (isinstance(ids, list)
                                and all(isinstance(i, int) and not isinstance(i, bool)
                                        for i in ids)):
        raise StampError("the stamp's item ids are not a list of integers")
    if page and ids is not None and not ids:
        # ``None`` on a page is allowed: the ids did not fit the cell and
        # the baseline lists them (``make``, ``covered``).
        raise StampError("the stamp says page but lists no item ids")
    estimate_v = doc.get("estimate_v")
    if not isinstance(estimate_v, str) or not estimate_v:
        raise StampError("the stamp does not name the estimate's version")
    declaration = doc.get("declaration")
    if not isinstance(declaration, dict):
        raise StampError("the stamp's declaration is not an object")
    extra = doc.get("extra")
    return Stamp(contract=doc["contract"], pack=dict(pack), schema=schema,
                 declaration=declaration, host=str(doc.get("host") or ""),
                 estimate_id=doc.get("estimate_id"), estimate_v=estimate_v,
                 exported_at=str(doc.get("exported_at") or ""), page=page,
                 item_ids=None if ids is None else list(ids), baseline=dict(doc["baseline"]),
                 extra=dict(extra) if isinstance(extra, dict) else {}, raw=doc)


def with_baseline(doc: dict, meta: dict, *, estimate_v, exported_at: str) -> dict:
    """A copy of ``doc`` whose baseline, estimate ``v`` and export time are the
    ones a patch or refresh just established. Nothing else changes."""
    out = dict(doc)
    out["baseline"] = dict(meta)
    out["estimate_v"] = estimate_v
    out["exported_at"] = exported_at
    return out


def page_of(payload: dict) -> tuple:
    """``(page, item_ids)`` from a payload's ``_fetch`` record (the client
    writes it for ``fetch --items``): the whole estimate when the record is
    absent or null. A record that is there but malformed is a payload
    refusal (``exchange.model.PayloadError``), never a traceback."""
    from estimating_tools.exchange.model import fetch_record

    ids = fetch_record(payload)
    if ids is None:
        return False, None
    return True, sorted(set(ids))


def chunks_of(ws) -> list:
    """The baseline chunks: column B from B1 down to the first empty cell,
    on a normal or a read-only worksheet. Not only text -- a chunk Excel
    turned into a number is handed on so ``baseline.decode`` names it."""
    out = []
    for (value,) in ws.iter_rows(min_col=2, max_col=2, values_only=True):
        if value in (None, ""):
            break
        out.append(value)
    return out


def read_cell(ws):
    """The stamp cell's JSON object, or ``StampError``."""
    try:
        doc = json.loads(ws[CELL].value or "")
    except (TypeError, ValueError):
        raise StampError(f"the stamp in {SHEET}!{CELL} is unreadable") from None
    if not isinstance(doc, dict):
        raise StampError(f"the stamp in {SHEET}!{CELL} is unreadable")
    return doc


def read(path) -> Stamp:
    """The stamp of the book at ``path`` (openpyxl, read-only). ``StampError``
    for a book without one; ``OSError`` for a file that cannot be opened."""
    from openpyxl import load_workbook

    wb = load_workbook(Path(path), read_only=True, data_only=False)
    try:
        if SHEET not in wb.sheetnames:
            raise StampError(f"no {SHEET} sheet: not an exchange book")
        ws = wb[SHEET]
        row = next(ws.iter_rows(min_row=1, max_row=1, max_col=1, values_only=True), (None,))
        try:
            doc = json.loads(row[0] or "")
        except (TypeError, ValueError):
            raise StampError(f"the stamp in {SHEET}!{CELL} is unreadable") from None
        return parse(doc)
    finally:
        wb.close()


def covered(path) -> tuple:
    """``(page, item_ids)`` for the CLI's post-commit fetch and rebuild
    advice: ``(True, ids)`` for a page, ``(False, None)`` for the whole
    estimate, ``(None, None)`` when the book cannot say (unreadable). A
    page whose stamp carries no ids (they did not fit the cell, ``make``)
    lists its baseline's items; so does a book stamped before this module
    (``is_legacy``), which has no page flag: its baseline's items are taken
    as a page, as step 1 did and as HeavyBook's in-memory upgrade of a
    layout-2 book does (``heavybook.legacy``). A layout-2 whole book thus
    says page too; the apply then fetches those items, which is the whole
    estimate -- never the other guess, which would read absent items as
    deletions."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(Path(path), read_only=True, data_only=False)
    except Exception:  # noqa: BLE001 -- unreadable: the caller fetches the whole estimate
        return None, None
    try:
        if SHEET not in wb.sheetnames:
            return None, None
        ws = wb[SHEET]
        row = next(ws.iter_rows(min_row=1, max_row=1, max_col=1, values_only=True), (None,))
        doc = json.loads(row[0] or "")
        if not is_legacy(doc):
            st = parse(doc)
            if not st.page:
                return False, None
            if st.item_ids is not None:
                return True, list(st.item_ids)
            meta = st.baseline
        else:
            meta = doc.get("baseline")
        payload = baseline.decode(chunks_of(ws), meta)
        ids = sorted({int(item["id"]) for item in payload.get("items") or ()})
        return (True, ids) if ids else (None, None)
    except (StopIteration, TypeError, ValueError, KeyError, AttributeError,
            baseline.BaselineError):
        return None, None
    finally:
        wb.close()
