"""Fieldbook registered as an exchange pack. Until roadmap 1.11 (the fieldbook
design spec, 2026-10-31-fieldbook-on-the-contract-design.md) lands, fieldbook
builds from a spec and reads back into it, so build, read and patch refuse
here and name the path that works today."""
from __future__ import annotations

from pathlib import Path

from estimating_tools.estimate_spec import layout_map
from estimating_tools.exchange.types import BookFacts, InsertKind, NotYet, Verdict

FORMAT_NAME = "fieldbook"
#: Must equal the version in packs/fieldbook/format.yaml (a test pins it).
FORMAT_VERSION = "2"


class FieldbookPack:
    """The fieldbook estimate workbook: detects its books, refuses the rest."""
    name = FORMAT_NAME
    version = FORMAT_VERSION
    contract = "1"

    def detect(self, facts: BookFacts) -> Verdict:
        """Judge the `estimate_format` stamp; a derived pack's chain counts if it has fieldbook."""
        value = str(facts.properties.get("estimate_format", ""))
        for link in value.split(" / "):
            fmt, _, ver = link.strip().partition(" ")
            if fmt != FORMAT_NAME:
                continue
            try:
                n = int(ver)
            except ValueError:
                return "bad"
            if n < 1:
                return "bad"
            return "newer" if n > int(FORMAT_VERSION) else "ok"
        return "none"

    def build(self, payload, out: Path, *, options: dict):
        raise NotYet("fieldbook builds from a spec today: `est-estimate build SPEC.yaml` "
                     "(building from the read model is roadmap 1.11)")

    def read(self, book: Path):
        raise NotYet("fieldbook reads back into its spec today: "
                     "`est-estimate read-back SPEC.yaml BOOK` "
                     "(reading into a change set is roadmap 1.11)")

    def patch(self, book: Path, change_set, result, payload):
        raise NotYet("fieldbook has no server identity to patch yet (roadmap 1.11)")

    def refresh(self, book: Path, payload, *, dry_run: bool = False):
        raise NotYet("fieldbook has no server identity to refresh yet (roadmap 1.11)")

    def templates(self) -> list[InsertKind]:
        """The prototype rows fieldbook names: the task row plus the layout map's kinds."""
        kinds = ("task", *layout_map.TEMPLATE_ROWS)
        return [InsertKind(kind=k, name=f"est.tpl.{k}") for k in kinds]

    def declaration(self):
        """Fieldbook's layout map, lifted (``exchange.declaration.lift_layout_map``)."""
        from estimating_tools.estimate_spec.format_pack import bundled_pack
        from estimating_tools.exchange.declaration import lift_layout_map, load

        pack = bundled_pack()
        return load(lift_layout_map(pack.layout_map or {}, pack=FORMAT_NAME,
                                    version=FORMAT_VERSION))


def pack() -> FieldbookPack:
    """Entry-point factory for the exchange registry."""
    return FieldbookPack()
