"""Fieldbook registered as an exchange pack. Its declaration is
``packs/fieldbook/pack.yaml`` with ``format.yaml``'s layout map lifted in
(fieldbook spec, delivery 1). Building a book from the read model is
delivery 2, and reading, patching and refreshing one through the engine
delivery 3 (they turn on together, so no apply is ever committed that the
book cannot be patched from): until then build, read, patch and refresh
refuse here and name the path that works today."""
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
        raise NotYet("fieldbook patches through the engine in delivery 3 (roadmap 1.11)")

    def refresh(self, book: Path, payload, *, dry_run: bool = False):
        raise NotYet("fieldbook refreshes through the engine in delivery 3 (roadmap 1.11)")

    def templates(self) -> list[InsertKind]:
        """The prototype rows fieldbook names: the task row plus the layout map's kinds."""
        kinds = ("task", *layout_map.TEMPLATE_ROWS)
        return [InsertKind(kind=k, name=f"est.tpl.{k}") for k in kinds]

    def declaration(self):
        """``pack.yaml``, with the layout map's navigator section and
        prototypes lifted in (``exchange.declaration.lift_layout_map``)."""
        from importlib import resources

        import yaml

        from estimating_tools.estimate_spec.format_pack import bundled_pack
        from estimating_tools.exchange.declaration import lift_layout_map, load

        text = resources.files("estimating_tools.estimate_spec").joinpath(
            "packs/fieldbook/pack.yaml").read_text(encoding="utf-8")
        return load(lift_layout_map(bundled_pack().layout_map or {}, pack=FORMAT_NAME,
                                    version=FORMAT_VERSION, into=yaml.safe_load(text)))


def pack() -> FieldbookPack:
    """Entry-point factory for the exchange registry."""
    return FieldbookPack()
