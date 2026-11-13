"""The exchange stamp a fieldbook book carries when it is built from
BidSheet.ai's read model (contract part 5; engine spec, Fill step 4): the
stamp JSON at ``_wb!A1`` under the defined name ``exchange.stamp``, the
baseline payload chunked in ``_wb`` column B below it, and the
``estimate_id``, ``bidsheet_host`` and ``exported_at`` properties -- the
cells and properties HeavyBook's fill writes, written here through
openpyxl, which is fieldbook's renderer. ``estimate_format`` is the
renderer's own property. A book built from a spec carries none of this: it
has no BidSheet.ai identity to read back against."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from estimating_tools.exchange import baseline as exchange_baseline
from estimating_tools.exchange import model
from estimating_tools.exchange import stamp as exchange_stamp


@dataclass(frozen=True)
class Baseline:
    """What a build from the read model stamps: the payload (the book's
    baseline), the BidSheet.ai host it came from and the export time (now,
    unless the caller says)."""
    payload: dict
    host: str = exchange_stamp.DEFAULT_HOST
    exported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"))           # TemplatePack.build's default


def write(wb, base: Baseline, declaration) -> None:
    """Stamp ``wb`` (an openpyxl workbook) with ``base`` and ``declaration``
    (a loaded ``exchange.declaration.Declaration``). ValueError for a
    payload the read model refuses, or a stamp past one cell."""
    from openpyxl.packaging.custom import StringProperty
    from openpyxl.workbook.defined_name import DefinedName

    try:
        data = model.parse(base.payload)
        chunks, meta = exchange_baseline.encode(base.payload)
    except (model.PayloadError, exchange_baseline.BaselineError) as exc:
        raise ValueError(f"the read model cannot be laid out: {exc}") from exc
    host = exchange_stamp.bare_host(base.host)
    page, item_ids = exchange_stamp.page_of(base.payload)
    doc = exchange_stamp.make(pack=declaration.pack.name, version=declaration.pack.version,
                              declaration=declaration.raw, host=host,
                              estimate_id=data.estimate.id, estimate_v=data.estimate.v,
                              exported_at=base.exported_at, baseline=meta, page=page,
                              item_ids=item_ids)
    text = exchange_stamp.dumps(doc)
    if len(text) > exchange_stamp.CELL_LIMIT:
        raise ValueError(f"the book's stamp is {len(text)} characters; Excel holds "
                         f"{exchange_stamp.CELL_LIMIT} per cell -- build fewer items per page")
    ws = wb.create_sheet(exchange_stamp.SHEET)
    ws.sheet_state = "hidden"
    ws[exchange_stamp.CELL] = text
    for n, chunk in enumerate(chunks, start=1):
        ws[f"B{n}"] = chunk
    wb.defined_names[exchange_stamp.NAME] = DefinedName(
        exchange_stamp.NAME, attr_text=f"'{exchange_stamp.SHEET}'!$A$1")
    for name, value in (("estimate_id", str(data.estimate.id)), ("bidsheet_host", host),
                        ("exported_at", base.exported_at)):
        wb.custom_doc_props.append(StringProperty(name=name, value=value))
