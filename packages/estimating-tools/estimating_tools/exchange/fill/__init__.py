"""Template fill (engine spec, "Fill (build) for template packs"): a template
pack's ``template.xlsx`` plus its declaration plus a read-model payload
become a stamped book.

``fill(pack, template, payload, out, *, exported_at, host, allow_dropped)``:

1. **Lint** the template against the declaration (``fill.lint``).
2. **Expand.** ``fill.plan`` lays every declared sheet out; each fill
   region's rows go in as one ``rowops.FillRows`` op above its template row
   (a blocks sheet's ``first_row``; a flat, rates or display sheet's
   regions bottom-up, so each op names its region's row as the template
   has it), so every reference into the sheet -- defined names,
   conditional formats, validations, charts, other sheets' formulas --
   moves as Excel moves it for the same insert, and each placed row's
   formulas are its prototype's, placed (``refs.place``). A flat sheet's
   named rows are the template's own; the fill writes their values.
3. **Owner row.** The engine writes the owner-row helper on every row of a
   blocks sheet, and on every row of its prototypes in the filled book, so
   a later patch or refresh insert copies it (``fill.values``).
4. **Stamp.** ``estimate_format`` and the stamp's custom properties, the
   stamp JSON (contract, pack, declaration and schema, host, estimate,
   export time, page, baseline meta) in ``_wb!A1`` under the defined name
   ``exchange.stamp``, the baseline chunks in column B.
5. **Cached values** (``xlcalc.cache_or_warn``), on the filled copy.

All of it is one ``writer.edit`` of a copy of the template beside ``out``
-- the template is never loaded and re-saved through openpyxl, so charts,
images, VBA, extension validations and every other part survive -- and the
copy is read back through the reader before it becomes ``out``: a fill that
would not read back clean (no problems, no ops) is refused, nothing
written. The fill writes the same bytes for the same payload, template and
export time (the writer keeps the template's entry times)."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from estimating_tools.exchange import baseline, model, rowops, writer
from estimating_tools.exchange import stamp as exchange_stamp
from estimating_tools.exchange.fill import lint as L
from estimating_tools.exchange.fill.plan import FillRefused, regions
from estimating_tools.exchange.fill.values import (header_cells, named_cells,
                                                   prototype_cells, row_cells)
from estimating_tools.exchange.types import BuildRefused
from estimating_tools.xlcalc import cache_or_warn

__all__ = ["FillReport", "fill", "prepare"]


@dataclass(frozen=True)
class FillReport:
    """What a fill wrote: the book, its export time, the rows placed per
    sheet tab, and what the template holds on a prototype row that the fill
    did not copy (``allow_dropped``)."""
    path: Path
    exported_at: str
    rows: dict = field(default_factory=dict)
    dropped: list = field(default_factory=list)


def _refused(problems) -> BuildRefused:
    shown = "; ".join(problems[:5]) + (f"; and {len(problems) - 5} more"
                                       if len(problems) > 5 else "")
    return BuildRefused("template", shown)


def prepare(pack, template, payload, *, exported_at: str, host: str,
            allow_dropped=False):
    """``(ops, cells, properties, names, rows, dropped)`` for ``writer.edit``;
    ``BuildRefused`` (nothing written) for a template, a declaration or a
    payload the fill cannot use."""
    decl = pack.declaration()
    try:
        wb = model.parse(payload)
        chunks, meta = baseline.encode(payload)
    except (model.PayloadError, baseline.BaselineError) as exc:
        raise BuildRefused("payload", str(exc)) from exc
    try:
        found = L.check(template, decl)
    except L.LintError as exc:
        raise _refused(exc.problems) from exc
    if found.dropped and not allow_dropped:
        raise _refused([f"{d} -- the fill does not copy it onto the rows it places; pass "
                        "--allow-dropped to fill anyway" for d in found.dropped])
    ops, cells, rows, names = [], {}, {}, {}
    try:
        for key, sheet in decl.sheets.items():
            laid = regions(decl, key, wb, found.protos)
            names.update(fitted_names(found.ranges, sheet.tab,
                                      [(at, len(placed)) for at, placed in laid]))
            mine = cells.setdefault(sheet.tab, {})
            mine.update(header_cells(decl, key, wb, exported_at=exported_at, host=host))
            mine.update(named_cells(decl, key, wb, found.named.get(key, {})))
            rows[sheet.tab] = sum(len(placed) for _at, placed in laid)
            skip = (sheet.tag("owner_row"),) if sheet.tag("owner_row") else ()
            # Values at the rows as they stand after every insert: a region's
            # rows move down by the rows placed in the regions above it.
            above = 0
            for at, placed in laid:
                for n, p in enumerate(placed):
                    mine.update(row_cells(decl, key, p, at + above + n, wb))
                above += len(placed)
            # The ops bottom-up, so each names its region's template row
            # (and a block map's indices are among its own region's rows).
            for at, placed in reversed(laid):
                if placed:
                    ops.append(rowops.FillRows(
                        sheet.tab, at, found.sheet,
                        [rowops.FillRow(p.proto_row, p.block, p.level) for p in placed],
                        skip=skip))
    except FillRefused as exc:
        raise BuildRefused("payload", str(exc)) from exc
    # The prototypes keep what the template held, plus the owner-row helper:
    # patch and refresh insert from them, and the helper is the one cell the
    # placing copy skipped.
    cells.setdefault(found.sheet, {}).update(prototype_cells(decl, found.protos))
    page, item_ids = exchange_stamp.page_of(payload)
    doc = exchange_stamp.make(pack=decl.pack.name, version=decl.pack.version,
                              declaration=decl.raw, host=host, estimate_id=wb.estimate.id,
                              estimate_v=wb.estimate.v, exported_at=exported_at, baseline=meta,
                              page=page, item_ids=item_ids)
    text = exchange_stamp.dumps(doc)
    if len(text) > exchange_stamp.CELL_LIMIT:
        raise BuildRefused("payload", f"the book's stamp is {len(text)} characters; Excel holds "
                           f"{exchange_stamp.CELL_LIMIT} per cell -- build fewer items per page")
    stamp_cells = {exchange_stamp.CELL: text}
    for n, chunk in enumerate(chunks, start=1):
        stamp_cells[f"B{n}"] = chunk
    cells[exchange_stamp.SHEET] = stamp_cells
    properties = {exchange_stamp.PROPERTY: f"{decl.pack.name} {decl.pack.version}",
                  "estimate_id": str(wb.estimate.id), "bidsheet_host": host,
                  "exported_at": exported_at}
    names[exchange_stamp.NAME] = f"'{exchange_stamp.SHEET}'!$A$1"
    return ops, cells, properties, names, rows, list(found.dropped)


def fitted_names(ranges, tab, laid) -> dict:
    """The template's workbook-scoped names on sheet ``tab`` that end on a
    fill region's template row (its sentinel, so each insert there grows them), set to
    end on the region's last placed row instead -- the names cover the rows
    the fill placed, never the sentinel. A name that is only the sentinel
    row covers exactly the placed rows. ``ranges``: ``Lint.ranges``;
    ``laid``: ``[(template row, rows placed)]`` top to bottom. With no rows
    placed, a name over rows above keeps them (it ends above the sentinel)
    and a sentinel-only name is left as the inserts move it, on the sentinel.
    Only workbook-scoped names are fitted (``Lint.ranges`` lists no other):
    a sheet-scoped name, or one over several ranges, is left as the inserts
    move it."""
    def moved(row):                       # where a template row above no sentinel lands
        return row + sum(n for at, n in laid if at <= row)

    out = {}
    for name, (sheet, c1, r1, c2, r2) in ranges.items():
        if sheet != tab:
            continue
        for i, (at, n) in enumerate(laid):
            if r2 != at:
                continue
            first = at + sum(m for a, m in laid[:i])          # the region's first placed row
            if r1 == at:
                if not n:
                    break
                start, end = first, first + n - 1
            else:
                start, end = moved(r1), first + n - 1
            quoted = sheet.replace("'", "''")
            out[name] = f"'{quoted}'!${c1}${start}:${c2}${max(end, start)}"
            break
    return out


def _match_new_file_mode(tmp):
    """``mkstemp`` creates the file 0600; give it the mode a normally created
    file gets (0666 less the umask), as HeavyBook's build does."""
    old = os.umask(0)
    os.umask(old)
    os.chmod(tmp, 0o666 & ~old)


def fill(pack, template, payload, out, *, exported_at: str, host: str,
         allow_dropped: bool = False) -> FillReport:
    """Fill ``template`` from ``payload`` into ``out`` for ``pack`` (a template
    pack: its ``declaration()`` and its ``read``-side are the engine's).
    ``BuildRefused`` with nothing written when the template, the payload or
    the read-back of the filled copy refuses; ``OSError`` propagates."""
    from estimating_tools.exchange.patch.verify import unclean

    out = Path(out)
    if out.resolve() == Path(template).resolve():
        raise BuildRefused("template", f"the output {out} is the template itself -- write the "
                           "book somewhere else")
    ops, cells, properties, names, rows, dropped = prepare(
        pack, template, payload, exported_at=exported_at, host=host,
        allow_dropped=allow_dropped)
    fd, name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.stem}.", suffix=".filling.xlsx")
    os.close(fd)
    tmp = Path(name)
    try:
        tmp.write_bytes(Path(template).read_bytes())
        try:
            writer.edit(tmp, rows=ops, cells=cells, properties=properties, names=names,
                        full_calc_on_load=True)
        except (rowops.RowOpError, ValueError) as exc:
            raise BuildRefused("template", f"the template cannot be filled: {exc}") from exc
        cache_or_warn(tmp, label=out.name)
        why = unclean(tmp, pack)
        if why:
            raise _refused([f"the filled book does not read back clean: {w}" for w in why])
        _match_new_file_mode(tmp)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return FillReport(path=out, exported_at=exported_at, rows=rows, dropped=dropped)
