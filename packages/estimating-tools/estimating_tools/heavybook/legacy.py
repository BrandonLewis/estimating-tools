"""Books stamped before the exchange stamp (layout 2: 0.1.95, 0.1.96), and
books whose exchange stamp predates step 2b (``upgrade_step2a``).

``upgrade(raw, wb)`` turns the old ``_wb!A1`` layout document into the
stamp document ``exchange.stamp.make`` would have written, in memory. The
sheets of layout 2 and 3 hold the same cells, so nothing else changes; the
patch after an apply writes the new stamp to the cell. The declaration it
carries is ``declaration.generate(derived=False)``: a layout-2 book's owner
tags are stored constants (no chain formulas) and its Crews sheet has no
crew-row helper column, and the declaration says so, so the reader reads
those tags and checks only the formulas the book has.

Page-ness: layout 2 recorded none, and the read model carries no count of
the estimate's items to compare the baseline against, so the book's items
are its baseline's and ``page`` is true (``item_ids`` the baseline's item
ids). A whole-estimate book thus says page too: an apply then fetches those
items, which is the whole estimate. The other guess -- "whole" for a book
that is a page -- would make an apply read the absent items as deletions
(#426), so it is never made. A baseline with no items at all upgrades as
the whole estimate (a page cannot cover no items)."""
from __future__ import annotations

from estimating_tools.exchange import baseline as exchange_baseline
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.stamp import StampError
from estimating_tools.heavybook import ACCEPTED_FORMATS, FORMAT_NAME, FORMAT_VERSION, layout
from estimating_tools.heavybook.columns import CR, CW

#: The layout versions ``upgrade`` turns into a stamp.
UPGRADABLE = (2,)
#: The custom document properties the 0.1.95 and 0.1.96 builds wrote.
HOST_PROPERTY = "bidsheet_host"
EXPORTED_AT_PROPERTY = "exported_at"
#: The old document's keys that the stamp carries itself, not under ``extra.layout``.
_LIFTED = ("baseline", "estimate_id", "estimate_v", "format")


def _property(wb, name):
    return next((p.value for p in wb.custom_doc_props.props if p.name == name), None)


def upgrade(raw: dict, wb) -> dict:
    """The stamp document for a layout-2 book; ``StampError`` for any other.

    The host and the export time come from the book's custom properties
    ``bidsheet_host`` and ``exported_at`` (where the 0.1.96 build put them);
    a book that names no host is refused. The items are the baseline's and
    the book is a page (the module docstring says why)."""
    # Inside the function: ``pack`` imports this module and this module
    # needs ``pack.bare_host``; each imports the other lazily so the two load
    # in either order.
    from estimating_tools.heavybook.declaration import generate
    from estimating_tools.heavybook.pack import bare_host

    if not isinstance(raw, dict) or not exchange_stamp.is_legacy(raw):
        raise StampError("this book is not stamped with a layout document")
    version = raw.get("layout_version")
    if isinstance(version, bool) or version not in UPGRADABLE:
        raise StampError(f"this book was stamped before the exchange stamp (layout "
                         f"{version!r}) and cannot be upgraded")
    if raw.get("format") not in ACCEPTED_FORMATS:
        raise StampError("not a HeavyBook workbook")
    host = str(_property(wb, HOST_PROPERTY) or "").strip()
    if not host:
        raise StampError("the book names no BidSheet.ai host")
    try:
        host = bare_host(host)
    except ValueError as exc:
        raise StampError(f"the book's BidSheet.ai host is not usable ({exc})") from None
    exported_at = str(_property(wb, EXPORTED_AT_PROPERTY) or "")
    meta = raw.get("baseline")
    if not isinstance(meta, dict):
        raise StampError("the book carries no baseline")
    try:
        payload = exchange_baseline.decode(exchange_stamp.chunks_of(wb[exchange_stamp.SHEET]),
                                           meta)
    except exchange_baseline.BaselineError as exc:
        raise StampError(str(exc)) from None
    try:
        item_ids = sorted({int(item["id"]) for item in payload.get("items") or ()})
    except (TypeError, ValueError, KeyError):
        raise StampError("the embedded baseline's items have no ids") from None
    page = bool(item_ids)
    tabs = raw.get("tabs")
    if not isinstance(tabs, dict):
        raise StampError(f"the layout in {exchange_stamp.SHEET}!{exchange_stamp.CELL} "
                         "names no tabs")
    layout_doc = {k: v for k, v in raw.items() if k not in _LIFTED}
    layout_doc["layout_version"] = layout.LAYOUT_VERSION
    # A layout-2 book's owner tags are stored constants, and its Crews sheet
    # has no crew-row helper column: its declaration says so (no derived
    # tag, no helper formula), so the reader reads and checks what is there.
    return exchange_stamp.make(
        pack=FORMAT_NAME, version=FORMAT_VERSION,
        declaration=generate(tabs=tabs, derived=False),
        host=host, estimate_id=raw.get("estimate_id"), estimate_v=raw.get("estimate_v"),
        exported_at=exported_at, baseline=meta, page=page,
        item_ids=item_ids if page else None,
        extra={"layout": layout_doc, "upgraded_from": version})


def is_step2a(raw) -> bool:
    """Whether ``raw`` is a HeavyBook exchange stamp written by the step 2a
    code (#437): schema 1, and its Cost Report activity block has no
    ``within`` (that key arrived with step 2b, so every later stamp has it).
    Anything else -- a current stamp, a layout document, a malformed one --
    is not."""
    if not isinstance(raw, dict) or exchange_stamp.is_legacy(raw) or raw.get("schema") != 1:
        return False
    pack = raw.get("pack")
    if not isinstance(pack, dict) or pack.get("name") not in ACCEPTED_FORMATS:
        return False
    decl = raw.get("declaration")
    sheets = decl.get("sheets") if isinstance(decl, dict) else None
    cost_report = sheets.get("cost_report") if isinstance(sheets, dict) else None
    blocks = cost_report.get("blocks") if isinstance(cost_report, dict) else None
    activity = blocks.get("activity") if isinstance(blocks, dict) else None
    return isinstance(activity, dict) and "within" not in activity


def upgrade_step2a(raw: dict) -> dict:
    """The current stamp document for a step-2a stamp (``is_step2a``), in
    memory; any other document unchanged.

    Such a book was built (or, from layout 2, patched) by the step 2a code:
    its owner tags are stored constants (no chain formulas) and its Crews
    sheet has no crew-row helper column, so its declaration is
    ``declaration.generate(tabs=<extra.layout.tabs>, derived=False)`` -- the
    step 2a declaration plus the activity block's ``within``. Everything
    else in the stamp is kept; ``extra.upgraded_from`` says ``"2a"`` unless
    the book came from layout 2 (``2``, kept). ``StampError`` when the
    stamp names no tabs."""
    from estimating_tools.heavybook.declaration import generate

    if not is_step2a(raw):
        return raw
    extra = raw.get("extra")
    extra = dict(extra) if isinstance(extra, dict) else {}
    layout_doc = extra.get("layout")
    tabs = layout_doc.get("tabs") if isinstance(layout_doc, dict) else None
    if not isinstance(tabs, dict):
        raise StampError(f"the stamp in {exchange_stamp.SHEET}!{exchange_stamp.CELL} names no tabs")
    if extra.get("upgraded_from") != 2:
        extra["upgraded_from"] = "2a"
    return {**raw, "declaration": generate(tabs=tabs, derived=False), "extra": extra}


#: Export values step 3 added to HeavyBook's declaration, by (sheet key,
#: kind): cells every build has written (an item's bid quantity on its Cost
#: Report row, a member's rate as of export) but a stamp written before
#: step 3 does not list, so a refresh would leave them as built.
STEP3_EXPORT_VALUES = {("cost_report", "ITEM"): {CR.H1: "schedule_quantity"},
                       ("crews", "MEMBER"): {CW.EXPORT: "effective_hourly_rate"}}


def upgrade_export_values(raw: dict) -> dict:
    """A HeavyBook stamp whose declaration predates step 3's export values
    (``STEP3_EXPORT_VALUES``), with them added, in memory; any other
    document unchanged."""
    decl = raw.get("declaration") if isinstance(raw, dict) else None
    sheets = decl.get("sheets") if isinstance(decl, dict) else None
    pack = raw.get("pack") if isinstance(raw, dict) else None
    name = pack.get("name") if isinstance(pack, dict) else pack
    if name != "heavybook" or not isinstance(sheets, dict):
        return raw
    new_sheets = dict(sheets)
    for (key, kind), cells in STEP3_EXPORT_VALUES.items():
        sheet = sheets.get(key)
        if not isinstance(sheet, dict):
            continue
        values = sheet.get("export_values") if isinstance(sheet.get("export_values"), dict) else {}
        if values.get(kind) == cells:
            continue
        new_sheets[key] = {**sheet, "export_values": {**values, kind: dict(cells)}}
    if new_sheets == sheets:
        return raw
    return {**raw, "declaration": {**decl, "sheets": new_sheets}}
