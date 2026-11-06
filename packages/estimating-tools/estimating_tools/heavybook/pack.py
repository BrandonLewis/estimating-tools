"""HeavyBook as a code pack (engine spec, delivery step 1): the existing
build, read-back and templates behind the ``Pack`` protocol, plus ``patch``.
No read-back rule changes here."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from estimating_tools.exchange.types import (ApplyResult, BookFacts, BuildReport, InsertKind,
                                             PatchReport, ReadResult, Verdict)
from estimating_tools.heavybook import ACCEPTED_FORMATS, FORMAT_VERSION, layout

LAYOUT_NAME = "hc.layout"
DEFAULT_HOST = "www.bidsheet.ai"


def bare_host(host: str) -> str:
    """``HTTPS://WWW.X.ai/a?q#f`` or ``www.x.ai`` -> ``www.x.ai`` (port kept).

    Blank gives the default; any scheme other than https is refused."""
    host = str(host).strip()
    if not host:
        return DEFAULT_HOST
    if "://" in host:
        scheme, host = host.split("://", 1)
        if scheme.lower() != "https":
            raise ValueError("the BidSheet.ai host must be https")
    for sep in "/?#":
        host = host.split(sep, 1)[0]
    return host.lower() or DEFAULT_HOST


class HeavyBookPack:
    """The HeavyBook estimate workbook behind the exchange ``Pack`` protocol."""

    name = "heavybook"
    version = FORMAT_VERSION
    contract = "1"

    def detect(self, facts: BookFacts) -> Verdict:
        """Whether a book is HeavyBook: none, ok, bad (damaged stamp) or newer.
        A book stamped before the exchange stamp (its layout JSON under
        ``hc.layout``) is ``ok``: a layout in ``legacy.UPGRADABLE`` reads
        (upgraded in memory), any other layout read refuses with its layout
        message, not the registry's generic "damaged" one."""
        from estimating_tools.exchange import stamp as exchange_stamp
        from estimating_tools.heavybook import legacy

        fmt = str(facts.properties.get("estimate_format", "")).split(" ")[0]
        if fmt not in ACCEPTED_FORMATS:
            return "none"
        raw = facts.names.get(exchange_stamp.NAME)
        if raw is None:
            raw = facts.names.get(LAYOUT_NAME)
        if raw is None:
            return "bad"
        try:
            doc = json.loads(raw)
        except (TypeError, ValueError):
            return "bad"
        if not isinstance(doc, dict):
            return "bad"
        if exchange_stamp.is_legacy(doc):
            if doc.get("format") not in ACCEPTED_FORMATS:
                return "bad"
            version = doc.get("layout_version")
            if isinstance(version, bool) or not isinstance(version, int):
                return "bad"
            if version in legacy.UPGRADABLE:
                return "ok"
            # An older layout is "ok" on purpose: read refuses it with its
            # specific layout message, not the registry's generic "damaged" one.
            return "newer" if version > layout.LAYOUT_VERSION else "ok"
        try:
            st = exchange_stamp.parse(doc)
        except exchange_stamp.StampError:
            return "bad"
        if st.pack.get("name") not in ACCEPTED_FORMATS:
            return "bad"
        if st.schema > exchange_stamp.SCHEMA_VERSION:
            return "newer"
        if st.contract != exchange_stamp.CONTRACT:
            return "newer"
        version = (st.extra.get("layout") or {}).get("layout_version")
        if isinstance(version, int) and not isinstance(version, bool) \
                and version > layout.LAYOUT_VERSION:
            return "newer"
        return "ok"

    def build(self, payload: dict, out: Path, *, options: dict) -> BuildReport:
        """Build the book exactly as ``est-estimate heavybook build`` does.

        ``pack().build(payload, out, options={})`` equals the CLI with no flags.
        ``payload`` is the already-merged ``get_estimate_workbook`` document.
        Recognised ``options`` keys, all optional:

        - ``exported_at``: ISO string; default now in UTC (``%Y-%m-%dT%H:%M:%SZ``).
        - ``host``: BidSheet.ai host to stamp; a bare host or an https URL, which
          is reduced to the bare lowercase host (scheme, path, query and fragment
          dropped, port kept). Blank gives the default ``www.bidsheet.ai``; a
          scheme other than https raises ``ValueError``.
        - ``style``: a style-pack path (the CLI's ``--style``).
        - ``profile``: a loaded ``Profile``, used when no ``style`` is given.
          With neither, the org profile is loaded as the CLI does.

        A refused build raises ``BuildRefused`` (kind ``payload``, ``style``,
        ``profile`` or ``host``) and writes nothing; ``OSError`` propagates.
        """
        from estimating_tools.estimate_spec.format_pack import FormatPackError, profile_for_pack
        from estimating_tools.exchange.model import PayloadError
        from estimating_tools.exchange.types import BuildRefused
        from estimating_tools.heavybook import build as hb_build
        from estimating_tools.exchange.baseline import BaselineError
        from estimating_tools.heavybook.style import StyleError, resolve_style

        exported_at = options.get("exported_at") or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        try:
            host = bare_host(options.get("host") or DEFAULT_HOST)
        except ValueError as exc:
            raise BuildRefused("host", str(exc)) from exc
        style_path = options.get("style")
        profile = options.get("profile")
        try:
            if profile is None and not style_path:
                profile = profile_for_pack("heavycivil_style")
        except FormatPackError as exc:
            raise BuildRefused("profile", str(exc)) from exc
        try:
            style = resolve_style(style_path, profile)
        except StyleError as exc:
            raise BuildRefused("style", str(exc)) from exc
        try:
            book = hb_build.build(payload, style=style, exported_at=exported_at, host=host)
        except (PayloadError, BaselineError) as exc:
            raise BuildRefused("payload", str(exc)) from exc
        hb_build.save(book, Path(out))
        return BuildReport(path=Path(out), exported_at=exported_at)

    def read(self, book: Path) -> ReadResult:
        """Read an edited book into a change set, or the refusal's problems,
        through the generic reader (``exchange.reader``)."""
        from estimating_tools.exchange.reader import ReadRefused, read_book

        try:
            return ReadResult(change_set=read_book(Path(book), pack=self))
        except ReadRefused as exc:
            return ReadResult(problems=[str(p) for p in exc.problems])

    def patch(self, book: Path, change_set, result: ApplyResult, payload: dict) -> PatchReport:
        from estimating_tools.exchange.patch import patch

        return patch(Path(book), change_set, result, payload, pack=self)

    def refresh(self, book: Path, payload: dict, *, dry_run: bool = False):
        """BidSheet.ai's changes since the baseline, written in place or
        reported (``exchange.refresh``)."""
        from estimating_tools.exchange.refresh import refresh

        return refresh(Path(book), payload, pack=self, dry_run=dry_run)

    def refresh_extras(self, book, payload: dict, fresh, *, exported_at: str):
        """The Checks sheet's figures and export line, and the cost-share
        guard (``heavybook.refresh``); optional on a pack, called by patch
        and refresh."""
        from estimating_tools.heavybook.refresh import extras

        return extras(book, fresh, exported_at=exported_at)

    def upgrade_stamp(self, raw: dict, wb) -> dict:
        """The current stamp document for any older stamp HeavyBook wrote;
        ``raw`` unchanged when it is current (or not one of ours). The
        generic reader asks the detected pack for every stamp, so it names
        no pack.

        - a book stamped before the exchange stamp
          (``exchange.stamp.is_legacy``): ``legacy.upgrade``, ``StampError``
          for a layout that does not upgrade;
        - a step-2a stamp (schema 1, its declaration without the activity
          block's ``within``): ``legacy.upgrade_step2a``;
        - a stamp written before step 3, whose declaration lists neither an
          item's hidden bid quantity nor a member's export rate as export
          values: ``legacy.upgrade_export_values``."""
        from estimating_tools.exchange import stamp as exchange_stamp
        from estimating_tools.heavybook import legacy

        if exchange_stamp.is_legacy(raw):
            return legacy.upgrade(raw, wb)
        return legacy.upgrade_export_values(legacy.upgrade_step2a(raw))

    def covered(self, book: Path) -> tuple:
        """``(page, item_ids)`` from the stamp (``exchange.stamp.covered``).
        Optional on a pack: the CLI asks for it with ``getattr``."""
        from estimating_tools.exchange import stamp as exchange_stamp

        return exchange_stamp.covered(Path(book))

    def templates(self) -> list[InsertKind]:
        """The prototype-row insert kinds, named by their ``hc.tpl.*`` ranges."""
        return [InsertKind(kind=k, name=n) for k, n in layout.TEMPLATE_NAMES.items()]

    def declaration(self):
        """HeavyBook's declaration with the default tab titles (a built book's
        stamp carries the styled titles)."""
        from estimating_tools.exchange.declaration import load
        from estimating_tools.heavybook.declaration import generate

        return load(generate())


def pack() -> HeavyBookPack:
    """The registered entry point: a HeavyBook pack."""
    return HeavyBookPack()
