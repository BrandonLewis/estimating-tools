"""HeavyBook behind the ``Pack`` protocol. From version 2 it is a template
pack: ``heavybook/template/`` (``pack.yaml``, ``template.xlsx``) filled by
the engine (``exchange.template.TemplatePack``); read, patch and refresh are
the engine's. Books the code writers built (version 1, ``kind: code`` in
their stamp) still read, apply, patch and refresh: they carry their own
declaration and prototypes, ``upgrade_stamp`` upgrades the older stamps as
before, and ``refresh_extras`` refreshes their Checks figures as before
(``heavybook.refresh``)."""
from __future__ import annotations

import json
from pathlib import Path

from estimating_tools.exchange.types import (ApplyResult, BookFacts, BuildReport, InsertKind,
                                             PatchReport, ReadResult, Verdict)
from estimating_tools.exchange.stamp import DEFAULT_HOST, bare_host  # noqa: F401 -- re-exported
from estimating_tools.heavybook import ACCEPTED_FORMATS, FORMAT_VERSION, codebook

LAYOUT_NAME = "hc.layout"
#: The pack versions this plugin reads: 1, a code-built book; 2, the
#: template's.
READ_VERSIONS = ("1", "2")


class HeavyBookPack:
    """The HeavyBook estimate workbook behind the exchange ``Pack`` protocol."""

    name = "heavybook"
    version = FORMAT_VERSION
    contract = "1"

    def detect(self, facts: BookFacts) -> Verdict:
        """Whether a book is HeavyBook: none, ok, bad (damaged stamp) or newer
        (a later pack version than ``READ_VERSIONS``, or a later stamp).
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
            return "newer" if version > codebook.LAYOUT_VERSION else "ok"
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
        version = str(st.pack.get("version", ""))
        if version not in READ_VERSIONS:
            # A later version is a book this plugin cannot read: the
            # registry says to update the plugin.
            newest = max(map(int, READ_VERSIONS))
            return "newer" if version.isdigit() and int(version) > newest else "bad"
        version = (st.extra.get("layout") or {}).get("layout_version")
        if isinstance(version, int) and not isinstance(version, bool) \
                and version > codebook.LAYOUT_VERSION:
            return "newer"
        return "ok"

    def _template(self):
        from estimating_tools.exchange.template import TemplatePack

        if not hasattr(self, "_pack"):
            self._pack = TemplatePack.from_package("estimating_tools.heavybook.template")
        return self._pack

    def build(self, payload: dict, out: Path, *, options: dict) -> BuildReport:
        """Fill HeavyBook's template from ``payload`` (``exchange.fill``).
        Options: ``exported_at``, ``host``, ``allow_dropped`` (the template
        pack's). A ``style`` option or the profile's
        ``estimating.heavycivil_style`` no longer applies -- the book's look is
        its template -- and is ignored with one warning line. ``template``: a
        template pack directory to build from instead of the shipped one (an
        edited copy of ``heavybook/template/``)."""
        import sys

        from estimating_tools.estimate_spec.format_pack import FormatPackError, profile_for_pack

        styled = bool(options.get("style"))
        profile = options.get("profile")
        if profile is None and not styled:
            try:
                profile = profile_for_pack("heavycivil_style")
            except FormatPackError:
                profile = None
        if profile is not None and (profile.section("estimating") or {}).get("heavycivil_style"):
            styled = True
        if styled:
            print("warning: a HeavyBook style pack no longer applies -- the book's look is its "
                  "template now (heavybook/template/README.md); ignored", file=sys.stderr)
        keep = {k: options[k] for k in ("exported_at", "host", "allow_dropped") if k in options}
        return self._template_for(options.get("template")).build(payload, Path(out),
                                                                 options=keep)

    def _template_for(self, directory):
        """The shipped template pack, or the one in ``directory`` (``--template``:
        an edited copy of ``heavybook/template/``). Its declaration must load,
        be a template pack's and declare pack ``heavybook`` -- the book it
        builds is a HeavyBook book, read back by this pack from its stamp --
        else ``BuildRefused("template")``; the fill then lints it as any
        template, and refuses with nothing written what the lint refuses."""
        import yaml

        from estimating_tools.exchange.declaration import DeclarationError
        from estimating_tools.exchange.template import DECLARATION, TEMPLATE, TemplatePack
        from estimating_tools.exchange.types import BuildRefused

        if not directory:
            return self._template()
        root = Path(directory)
        missing = [n for n in (DECLARATION, TEMPLATE) if not (root / n).is_file()]
        if missing:
            raise BuildRefused("template", f"{root}: a template pack directory holds "
                               f"{DECLARATION} and {TEMPLATE} ({', '.join(missing)} missing)")
        try:
            doc = yaml.safe_load((root / DECLARATION).read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError(f"{DECLARATION} is not a mapping")
            pack = TemplatePack(root)
            pack.declaration()
        except (DeclarationError, OSError, ValueError, yaml.YAMLError) as exc:
            raise BuildRefused("template", f"{root}: {exc}") from exc
        if pack.version != FORMAT_VERSION:
            # Version 1 books still read, but only the retired code writers
            # built them: a template builds this plugin's version alone.
            raise BuildRefused("template", f"{root}: {DECLARATION} declares {self.name} version "
                               f"{pack.version!r}; this plugin builds version {FORMAT_VERSION} "
                               f"from a template -- keep the copy's version at {FORMAT_VERSION}, "
                               "or update the plugin for a later one")
        if pack.name != self.name:
            raise BuildRefused("template", f"{root}: {DECLARATION} declares pack {pack.name!r}; "
                               f"--template builds a {self.name} book from a copy of its "
                               "template (pack name heavybook)")
        return pack

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
        """A code-built book's Checks figures and cost-share guard
        (``heavybook.refresh``), or a template book's display rows
        (``TemplatePack.refresh_extras``)."""
        if book.decl.kind == "code":
            from estimating_tools.heavybook.refresh import extras

            return extras(book, fresh, exported_at=exported_at)
        return self._template().refresh_extras(book, payload, fresh, exported_at=exported_at)

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
        return self._template().templates()

    def declaration(self):
        """HeavyBook's declaration: the template pack's."""
        return self._template().declaration()


def pack() -> HeavyBookPack:
    """The registered entry point: a HeavyBook pack."""
    return HeavyBookPack()
