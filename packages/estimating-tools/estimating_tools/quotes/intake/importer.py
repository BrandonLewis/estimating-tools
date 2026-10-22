"""Results in, quote files out: the extraction agent's results become vendor quote
files behind the build gate.

`assemble_quote` turns one result into a `CanonicalQuote` and the reasons a human
should look at it (pure, no I/O). `import_results` walks a validated results file,
records each document's outcome in the inventory, and writes a quote file only when
`build_package_frames` accepts the real spec with the would-be quote set -- so a
file this module writes never breaks `est-estimate build`.
"""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from estimating_tools.estimate_spec.cli import _backup_path
from estimating_tools.estimate_spec.package_frames import PackageError, build_package_frames
from estimating_tools.quotes.files import (
    QuoteFileError, load_quote_file, load_quotes, quote_file_slug, write_quote_file)
from estimating_tools.quotes.intake.batch import package_digest, validate_results
from estimating_tools.quotes.intake.checks import contradicts, normalize_date_verbose
from estimating_tools.quotes.intake.inventory import Inventory
from estimating_tools.quotes.model import CanonicalQuote, QuoteLine

_LISTS = ("written", "revised", "unchanged", "held", "not_quote", "review", "refused")


@dataclass
class ImportReport:
    written: list[str] = field(default_factory=list)
    revised: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    not_quote: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [f"{name} {entry}" for name in _LISTS for entry in getattr(self, name)]

    def summary(self) -> str:
        return (f"{len(self.written)} written, {len(self.revised)} revised, "
                f"{len(self.unchanged)} unchanged, "
                f"{len(self.held)} held, {len(self.not_quote)} not quotes, "
                f"{len(self.refused)} refused")


def _fold(text) -> str:
    return str(text).strip().casefold()


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _target(pkg: dict, item_number: str, line_name) -> tuple[dict | None, int]:
    """The package line a result line prices (None when it names none), and how
    many package lines its item has."""
    cands = [ln for ln in pkg["lines"] if ln["item_number"] == item_number]
    if line_name is not None:
        match = [ln for ln in cands if ln["line_name"] == line_name]
        return (match[0] if match else None), len(cands)
    return (cands[0] if len(cands) == 1 else None), len(cands)


def assemble_quote(result: dict, pkg: dict, *, source: str) -> tuple[CanonicalQuote, list[str]]:
    """One quote result as a `CanonicalQuote` on package `pkg` (a `package_digest`
    entry), and its review reasons. Prices are kept as printed; a line the package
    does not have is kept as given for the build gate to refuse."""
    reasons: list[str] = list(result.get("needs_review") or [])
    notes: list[str] = []
    conditions: dict[str, str] = {}

    printed = result.get("quote_date")
    iso, ambiguous = normalize_date_verbose(printed)
    if iso and ambiguous:
        reasons.append(f"quote date '{printed}' read as {iso} (US month-first)")
    elif iso is None and printed and str(printed).strip():
        reasons.append(f"quote date '{printed}' could not be read")

    default_schedule = pkg["lines"][0]["schedule_name"] if pkg["lines"] else "Base"
    result_lines = result.get("lines") or []
    total = result.get("total_amount")
    # A lump sum that covers the unpriced lines: an unpriced line is left out
    # so the lump sum's remainder is prorated over it.
    covering = total is not None and (not result_lines or bool(result.get("total_covers_unpriced")))
    lines: list[QuoteLine] = []
    for rl in result_lines:
        item = rl["item_number"]
        target, count = _target(pkg, item, rl.get("line_name"))
        single = count == 1 and target is not None
        name = target["line_name"] if target else (rl.get("line_name") or rl["description"])
        label = f"item {item} '{name}'"
        uom = target["uom"] if target else None
        unpriced = (rl.get("unit_price") is None and rl.get("is_included") is not False
                    and not rl.get("folded_into"))
        if unpriced and rl.get("is_alternate"):
            conditions[f"Alternate: {name}"] = "no price"
            reasons.append(f"{label}: alternate without a price")
            continue
        if unpriced and covering:
            notes.append(f"{label}: unpriced, covered by the lump sum")
            continue
        lines.append(QuoteLine(
            schedule_name=target["schedule_name"] if target else default_schedule,
            item_number=item,
            line_name=None if single else rl.get("line_name"),
            unit_price=rl.get("unit_price"), quantity=rl.get("quantity"),
            is_included=rl.get("is_included") is not False,
            is_alternate=bool(rl.get("is_alternate")),
            exclusion_notes=rl.get("exclusion_note"), folded_into=rl.get("folded_into")))
        unit = (rl.get("unit") or "").strip()
        if unit and uom is not None and _fold(unit) != _fold(uom):
            reasons.append(f"{label}: priced per {unit}, package line is {uom}")
        elif not unit and rl.get("unit_price") is not None and uom:
            reasons.append(f"{label}: unit not stated; package line is {uom}")
        ext, qty, price = rl.get("extension"), rl.get("quantity"), rl.get("unit_price")
        freight = rl.get("freight_unit_price")
        if ext is not None and qty is not None and contradicts(qty, price, ext, freight):
            reasons.append(f"{label}: printed extension {ext} does not reproduce {qty} × {price}")
        if freight is not None:
            reasons.append(f"{label}: freight rate {freight} printed beside the unit price; "
                           "not combined")
            conditions[f"Freight rate: {name}"] = f"{freight} / {unit or uom}"
        if rl.get("review"):
            reasons.append(rl["review"])
        if rl.get("quantity_basis"):
            notes.append(f"{label}: quantity basis {rl['quantity_basis']}")

    for extra in result.get("extras") or []:
        price = extra.get("printed_price")
        if price is None:
            text = "no price"
        else:
            text = str(price)
            if extra.get("printed_unit"):
                text += f" / {extra['printed_unit']}"
            if extra.get("printed_quantity") is not None:
                text += f" × {extra['printed_quantity']}"
        conditions[f"Also quoted: {extra['description']}"] = text
        reasons.append(f"extra line: {extra['description']}")

    keys = {_fold(k): k for k in pkg.get("conditions") or []}
    for key, value in (result.get("conditions") or {}).items():
        conditions[keys.get(_fold(key), key)] = value

    amount = None
    if total is not None:
        if covering:
            amount = total
        else:
            conditions["Printed total"] = f"{total:,.2f}"

    if reasons:
        conditions["Review"] = "; ".join(reasons)
        notes.extend(f"review: {r}" for r in reasons)

    quote = CanonicalQuote(
        vendor_name=result["vendor_name"].strip(), work_package_name=pkg["name"],
        amount=amount, is_dbe=bool(result.get("is_dbe")),
        contact_info=result.get("contact_info"), notes="\n".join(notes) or None,
        lines=lines, quote_date=iso, quote_ref=result.get("quote_ref"),
        surcharge=result.get("surcharge"), conditions=conditions)
    return quote, reasons


def is_carried(pkg_spec: dict, vendor: str) -> bool:
    """Does the spec package carry `vendor`, as `selected` or in any pick?"""
    names = [pkg_spec.get("selected")] + list((pkg_spec.get("picks") or {}).values())
    return any(n is not None and _fold(n) == _fold(vendor) for n in names)


def vendor_total(frame, vendor: str) -> float:
    """The vendor column's total on `frame`: its lump amount, else the sum of its
    numeric cells times the lines' numeric quantities. 0.0 when it has no column."""
    for col in frame.vendors:
        if col.is_spare or _fold(col.name) != _fold(vendor):
            continue
        if col.lump_sum and col.lump_amount is not None:
            return float(col.lump_amount)
        return float(sum(col.cells[ln.key] * ln.qty for ln in frame.lines
                         if _is_number(col.cells.get(ln.key)) and _is_number(ln.qty)))
    return 0.0


def _quote_file_check(quote: CanonicalQuote) -> None:
    """Raise `QuoteFileError` when the file `quote` would be written as does not load."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "check.json"
        write_quote_file(path, quote)
        load_quote_file(path)


def _write_atomic(path: Path, quote: CanonicalQuote) -> None:
    """A failed write leaves the last usable quote intact."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".quote-",
                                     suffix=".tmp", delete=False) as fh:
        staged = Path(fh.name)
    try:
        write_quote_file(staged, quote)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


_SAME = ("unit_price", "amount", "is_included", "folded_into", "is_alternate")
EMPTY_REASON = "no priced lines and no total (a failed read; see prompt rule 3)"


def _join_conditions(existing: dict | None, part: dict | None) -> dict:
    """`existing`'s conditions with `part`'s added; a key both carry with
    different text keeps both, joined with "; " (existing first). A text already
    in the existing value is not repeated."""
    out = dict(existing or {})
    for key, value in (part or {}).items():
        have = out.get(key)
        if have is None:
            out[key] = value
        elif have != value:
            held = str(have).split("; ")
            if not all(seg in held for seg in str(value).split("; ")):
                out[key] = f"{have}; {value}"
    return out


def _lump_sum(q: CanonicalQuote) -> bool:
    return not q.lines and q.amount is not None


def merge_part(existing: CanonicalQuote, part: CanonicalQuote,
               part_sha: str) -> tuple[CanonicalQuote, str | None]:
    """`part` (a second document of the same date) unioned into `existing`, or
    `(existing, reason)` when the two price a line differently. Pure; see `_merge`."""
    merged, conflict, _ = _merge(existing, part, part_sha)
    return merged, conflict


def _merge(existing: CanonicalQuote, part: CanonicalQuote,
           part_sha: str) -> tuple[CanonicalQuote, str | None, list[str]]:
    """`merge_part`, and the review reasons the merge adds. Lines are keyed
    `(item_number, line_name)`; an alternate may share a priced line's key, so
    alternates are unioned beside the priced lines rather than against them.
    The existing header wins; a condition both carry keeps both texts. A lump
    sum beside an itemised quote is not merged as `amount`: it is kept as the
    `Printed total` condition and flagged. Prices are never changed. Pure."""
    lines = [copy.deepcopy(ln) for ln in existing.lines]
    priced = {(ln.item_number, ln.line_name): ln for ln in lines if not ln.is_alternate}
    for ln in part.lines:
        key = (ln.item_number, ln.line_name)
        if ln.is_alternate:
            if ln not in lines:
                lines.append(copy.deepcopy(ln))
            continue
        have = priced.get(key)
        if have is None:
            priced[key] = copy.deepcopy(ln)
            lines.append(priced[key])
        elif any(getattr(have, f) != getattr(ln, f) for f in _SAME):
            return existing, (f"conflicts with the quote on file on item {ln.item_number} "
                              f"line '{ln.line_name}'"), []
    if existing.amount is not None and part.amount is not None and existing.amount != part.amount:
        return existing, (f"conflicts with the quote on file on the lump sum "
                          f"({existing.amount:,.2f} on file, {part.amount:,.2f} in this part)"), []
    refs = [r for r in (existing.quote_ref, part.quote_ref) if r]
    notes = [existing.notes] if existing.notes else []
    if (part.notes and part.notes != existing.notes
            and f"part {part_sha[:8]}:" not in (existing.notes or "")):
        notes.append(f"part {part_sha[:8]}:\n{part.notes}")
    conditions = _join_conditions(existing.conditions, part.conditions)
    amount = existing.amount if existing.amount is not None else part.amount
    reviews: list[str] = []
    # Exactly one side a lump sum, the other itemised: the lump sum is not prorated
    # over (or dropped from) the itemised lines; it is shown and flagged.
    lump = (existing if _lump_sum(existing) and part.lines and part.amount is None
            else part if _lump_sum(part) and existing.lines and existing.amount is None
            else None)
    if lump is not None:
        amount = None
        printed = f"{lump.amount:,.2f}"
        reason = f"lump sum {printed} from a second document; not merged as amount"
        reviews.append(reason)
        conditions = _join_conditions(conditions, {"Printed total": printed, "Review": reason})
        if f"review: {reason}" not in "\n".join(notes):
            notes.append(f"review: {reason}")
    merged = replace(
        existing, lines=lines,
        conditions=conditions,
        quote_ref="; ".join(dict.fromkeys(refs)) or None,
        notes="\n".join(notes) or None,
        amount=amount,
        is_dbe=existing.is_dbe or part.is_dbe,
        contact_info=existing.contact_info or part.contact_info,
        surcharge=existing.surcharge if existing.surcharge is not None else part.surcharge,
        vendor_id=existing.vendor_id if existing.vendor_id is not None else part.vendor_id)
    return merged, None, reviews


def _single_names(pkg: dict) -> dict[str, str]:
    """Item number -> its line's name, for the package's single-line items."""
    by_item: dict[str, list[str]] = {}
    for ln in pkg["lines"]:
        by_item.setdefault(ln["item_number"], []).append(ln["line_name"])
    return {item: names[0] for item, names in by_item.items() if len(names) == 1}


def _merge_on_package(existing: CanonicalQuote, part: CanonicalQuote, part_sha: str,
                      pkg: dict) -> tuple[CanonicalQuote, str | None, list[str]]:
    """`_merge` with a single-line item's line keyed (and named in a conflict)
    by its package line whether or not the file spells the name out; the merged
    file leaves it out, as `assemble_quote` does."""
    single = _single_names(pkg)

    def named(q):
        return replace(q, lines=[replace(ln, line_name=ln.line_name or single.get(ln.item_number))
                                 for ln in q.lines])
    merged, reason, reviews = _merge(named(existing), named(part), part_sha)
    if reason:
        return existing, reason, []
    return replace(merged, lines=[
        replace(ln, line_name=None) if single.get(ln.item_number) == ln.line_name else ln
        for ln in merged.lines]), None, reviews


def _column(frame, vendor: str):
    return next((c for c in frame.vendors
                 if not c.is_spare and _fold(c.name) == _fold(vendor)), None)


def _revised_line(file_name: str, vendor: str, pkg_spec: dict, old_frame, new_frame) -> str:
    """The report's line for a revision: the vendor's total before and after, and
    the package lines the old quote priced that the new one does not."""
    carried = "carried" if is_carried(pkg_spec, vendor) else "not carried"
    old = vendor_total(old_frame, vendor) if old_frame is not None else None
    new = vendor_total(new_frame, vendor)
    before = f"{old:,.2f}" if old is not None else "(previous set does not build)"
    text = f"{file_name}: {vendor} revised {pkg_spec['name']} ({carried}): {before} → {new:,.2f}"
    old_col = _column(old_frame, vendor) if old_frame is not None else None
    new_col = _column(new_frame, vendor)
    if old_col is not None:
        dropped = [ln.name for ln in old_frame.lines if _is_number(old_col.cells.get(ln.key))
                   and not (new_col is not None and _is_number(new_col.cells.get(ln.key)))]
        if dropped:
            text += f"; dropped {', '.join(dropped)}"
    return text


def _next_seq(inv: Inventory) -> int:
    """One more than the highest entry `seq` on file: entries are ordered by it."""
    return 1 + max((e.get("seq") or 0 for d in inv.all()
                    for e in list(d.results) + list(d.requeued_from)), default=0)


def _holders(inv: Inventory, file_name: str) -> list[str]:
    """The records whose quotes are in `file_name` now, the base record first.
    Every entry that put a quote into the file counts, a requeued one too (the
    file still holds what it wrote): a part adds its record, anything else
    rewrote the file and starts over from its own."""
    entries = sorted(((e.get("seq") or 0, d.sha256, e) for d in inv.all()
                      for e in list(d.results) + list(d.requeued_from)
                      if e.get("quote_file") == file_name), key=lambda t: t[0])
    holders: list[str] = []
    for _, sha, e in entries:
        if e.get("part_of"):
            if sha not in holders:
                holders.append(sha)
        else:
            holders = [sha]
    return holders


def _current_record(inv: Inventory, file_name: str) -> str | None:
    """The sha of the record whose quote is the base of `file_name` now."""
    holders = _holders(inv, file_name)
    return holders[0] if holders else None


def _replaces(inv: Inventory, sha: str, holders: list[str]) -> str | None:
    """The holder `sha` is (a requeued document) or supersedes (a re-saved one,
    following `superseded_by`), or None."""
    for holder in holders:
        doc, seen = inv.get(holder), set()
        if holder == sha:
            return holder
        while doc is not None and doc.superseded_by and doc.sha256 not in seen:
            seen.add(doc.sha256)
            if doc.superseded_by == sha:
                return holder
            doc = inv.get(doc.superseded_by)
    return None


def _still_on_file(inv: Inventory, sha: str, file_name: str) -> bool:
    """Is `sha` a live record whose (not requeued) results name `file_name`?"""
    doc = inv.get(sha)
    return (doc is not None and doc.superseded_by is None
            and any(e.get("quote_file") == file_name for e in doc.results))


def _frame(frames, name: str):
    return next(f for f in frames if _fold(f.name) == _fold(name))


def _part_or_revision(on_file: CanonicalQuote, new: CanonicalQuote, sha: str,
                      pkg: dict) -> tuple[str, CanonicalQuote, str | None, list[str]]:
    """What `new` is beside the quote on file, by date: `("part", merged, None,
    reviews)` on the same date, `("revision", new, None, [])` when newer, else a
    hold reason."""
    old_date, new_date = on_file.quote_date or "", new.quote_date or ""
    if new_date == old_date:
        merged, why, reviews = _merge_on_package(on_file, new, sha, pkg)
        return "part", merged, why, reviews
    if new_date > old_date:
        return "revision", new, None, []
    return "held", on_file, f"older than the quote on file ({on_file.quote_date})", []


def _old_frame(spec: dict, quote_set: dict, name: str):
    """The package's frame on the quote set before this write, or None when that
    set no longer builds."""
    try:
        return _frame(build_package_frames(spec, list(quote_set.values()), spare_columns=0,
                                           taken=set()), name)
    except PackageError:
        return None


def import_results(inv: Inventory, spec: dict, quotes_dir: Path, payload: dict, *,
                   write: bool, batch_name: str | None = None) -> ImportReport:
    """Turn a results payload into quote files and inventory records.

    Without `write` nothing on disk changes and `inv` is left as it was: the
    records are updated on a copy, and the report says what a write would do.
    """
    validate_results(payload)
    quotes_dir = Path(quotes_dir)
    if not write:
        inv = Inventory(inv.path, {d.sha256: copy.deepcopy(d) for d in inv.all()})
    report = ImportReport()
    packages = {_fold(p["name"]): p for p in package_digest(spec)}
    # The quote set the gate builds on: the files on disk, then this run's files.
    quote_set = {q.source_file: q for q in load_quotes(quotes_dir)}
    held_now: set[str] = set()       # documents a result of this run left held or in error
    targets: dict[str, set[tuple[str, str]]] = {}
    for res in payload["results"]:
        if res["doc_type"] == "quote":
            targets.setdefault(res["sha256"], set()).add(
                (_fold(res["vendor_name"]), _fold(res["work_package_name"])))
    # A correction that changes identity must not leave the old, potentially
    # carried quote behind. Hold the whole document before any of its writes.
    moved: dict[str, list[str]] = {}
    for sha in {r["sha256"] for r in payload["results"]}:
        for name, quote in quote_set.items():
            if (_replaces(inv, sha, _holders(inv, name)) is not None
                    and (_fold(quote.vendor_name), _fold(quote.work_package_name))
                    not in targets.get(sha, set())):
                moved.setdefault(sha, []).append(name)

    def hold(doc, reason: str, status: str = "held") -> None:
        doc.status, doc.reason = status, reason
        inv.touch()
        held_now.add(doc.sha256)
        report.held.append(f"{doc.file_name} ({doc.short}): {reason}")

    try:
        for res in payload["results"]:
            sha = res["sha256"]
            # 1. The document must be one the inventory knows.
            doc = inv.get(sha)
            if doc is None:
                report.refused.append(f"{sha[:8]}: not in the inventory")
                continue
            if doc.superseded_by is not None:
                report.refused.append(f"{doc.short}: superseded by {doc.superseded_by[:8]}")
                continue
            if sha in moved:
                if sha not in held_now:
                    hold(doc, "previous quote would remain on file: " + ", ".join(moved[sha])
                         + "; reconcile its vendor/package before re-importing")
                continue
            # 2. Not a quote, or not readable.
            if res["doc_type"] == "not_quote":
                inv.touch()
                doc.status, doc.reason = "not_quote", res.get("reason") or "not a quote"
                report.not_quote.append(f"{doc.file_name} ({doc.short}): {doc.reason}")
                continue
            if res["doc_type"] == "unreadable":
                inv.touch()
                doc.status = "error"
                doc.reason = f"unreadable by the agent: {res.get('reason') or 'no reason given'}"
                report.held.append(f"{doc.file_name} ({doc.short}): {doc.reason}")
                continue
            # 3. The package must be one the spec has.
            printed = res["work_package_name"].strip()
            pkg = packages.get(_fold(printed))
            if pkg is None:
                hold(doc, f"package '{printed}' is not in the spec")
                continue
            # 4. Assemble; a quote already on file makes this a part or a revision.
            quote, reasons = assemble_quote(res, pkg, source=doc.file_name)
            entry = {"batch": batch_name, "seq": _next_seq(inv),
                     "vendor_name": quote.vendor_name,
                     "work_package_name": pkg["name"], "quote_file": None,
                     "needs_review": reasons}
            # The vendor's quote on this package, by content, whatever its file is named.
            existing = next((n for n, q in quote_set.items()
                             if _fold(q.vendor_name) == _fold(quote.vendor_name)
                             and _fold(q.work_package_name) == _fold(pkg["name"])), None)
            file_name = existing or quote_file_slug(quote.vendor_name, pkg["name"])
            kind = "new"
            # A document already imported into this file (a re-run) changes nothing.
            if any(e.get("quote_file") == file_name
                   and _fold(e.get("work_package_name") or "") == _fold(pkg["name"])
                   for e in doc.results):
                report.unchanged.append(f"{file_name} ({quote.vendor_name} / {pkg['name']}): "
                                        "already on file")
                continue
            # Nothing priced and no total: a failed read, never an empty vendor column.
            if not quote.lines and quote.amount is None:
                doc.results.append(entry)
                inv.touch()
                hold(doc, EMPTY_REASON)
                continue
            if existing is None and (file_name in quote_set or (quotes_dir / file_name).exists()):
                doc.results.append(entry)
                inv.touch()
                hold(doc, f"{file_name} holds another vendor's or package's quote")
                continue
            supersedes = None
            holders = _holders(inv, existing) if existing is not None else []
            replaced = _replaces(inv, sha, holders)
            if replaced is not None:
                # The document (requeued, or re-saved) that produced the file: its new
                # extraction replaces its own contribution, whatever its date.
                others = [h for h in holders if h != replaced and _still_on_file(inv, h, existing)]
                if others:
                    doc.results.append(entry)
                    inv.touch()
                    hold(doc, "the file holds parts from other documents; requeue them too: "
                              + ", ".join(h[:8] for h in others))
                    continue
                kind, supersedes = "revision", replaced
            elif existing is not None:
                kind, quote, why, merge_reviews = _part_or_revision(
                    quote_set[existing], quote, sha, pkg)
                reasons.extend(merge_reviews)
                if why:
                    doc.results.append(entry)
                    inv.touch()
                    hold(doc, why)
                    continue
                # A part that adds nothing leaves the file as it is.
                if quote == quote_set[existing]:
                    entry.update(quote_file=file_name, part_of=file_name)
                    doc.results.append(entry)
                    inv.touch()
                    if sha not in held_now:
                        doc.status, doc.reason = "extracted", None
                    report.unchanged.append(f"{file_name} ({quote.vendor_name} / "
                                            f"{pkg['name']}): already on file")
                    continue
            # The file must load as written: nothing the loader refuses reaches the folder.
            try:
                _quote_file_check(quote)
            except QuoteFileError as exc:
                doc.results.append(entry)
                inv.touch()
                hold(doc, f"quote file check: {exc}")
                continue
            # 5. The build gate: the real spec with the would-be quote set.
            try:
                frames = build_package_frames(
                    spec, [q for n, q in quote_set.items() if n != file_name] + [quote],
                    spare_columns=0, taken=set())
            except PackageError as exc:
                doc.results.append(entry)
                inv.touch()
                hold(doc, str(exc))
                continue
            # 6. Written (or, in a dry run, would be); a file replaced is backed up first.
            path = quotes_dir / file_name
            if write:
                try:
                    quotes_dir.mkdir(parents=True, exist_ok=True)
                    if path.exists():
                        shutil.copy2(path, _backup_path(path))
                    _write_atomic(path, quote)
                except OSError as exc:
                    hold(doc, f"could not write {file_name}: {exc}", status="error")
                    continue
            if kind == "revision":
                pkg_spec = next(p for p in spec["work_packages"]
                                if _fold(p["name"]) == _fold(pkg["name"]))
                report.revised.append(_revised_line(
                    file_name, quote.vendor_name, pkg_spec,
                    _old_frame(spec, quote_set, pkg["name"]), _frame(frames, pkg["name"])))
                entry["supersedes"] = supersedes or _current_record(inv, file_name)
            elif kind == "part":
                report.written.append(f"{file_name} ({quote.vendor_name} / {pkg['name']}, part)")
                entry["part_of"] = file_name
            else:
                report.written.append(f"{file_name} ({quote.vendor_name} / {pkg['name']})")
            quote.source_file = file_name
            quote_set[file_name] = quote
            entry["quote_file"] = file_name
            doc.results.append(entry)
            inv.touch()
            if sha not in held_now:     # a held package on the same document keeps it held
                doc.status, doc.reason = "extracted", None
            # 7. Review reasons are listed beside the file they belong to.
            if reasons:
                report.review.append(f"{file_name}: {'; '.join(reasons)}")
    finally:
        if write and inv.dirty:
            inv.save()   # once, and even when a write fails part-way
    return report
