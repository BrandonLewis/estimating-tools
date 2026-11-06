"""The pack interface (roadmap 1.2). A pack knows one layout. The CLI, the
skills and the Navigator discover packs through ``registry`` and never import
one by name."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from estimating_tools.exchange.types import (ApplyResult, BookFacts, BuildReport, InsertKind,
                                             PatchReport, ReadResult, RefreshReport, Verdict)

if TYPE_CHECKING:
    from estimating_tools.exchange.declaration import Declaration


@runtime_checkable
class Pack(Protocol):
    """One layout behind the exchange: detection, build, read, patch, its
    insert templates and its declaration.

    Optional on a pack (looked up with ``getattr``, so ``runtime_checkable``
    does not demand them):

    - ``upgrade_stamp(raw: dict, wb) -> dict``: a current exchange stamp
      document for any older stamp this pack wrote -- one written before the
      exchange stamp (``stamp.is_legacy``), or an exchange stamp whose
      declaration an older release of the pack wrote -- built from ``raw``
      and the open workbook; ``raw`` unchanged when it is current (or not
      the pack's). The reader calls it for every stamp, before parsing it,
      so it must tolerate any document; it raises ``stamp.StampError`` for
      an older stamp that does not upgrade. Without it the reader refuses a
      legacy stamp and reads the others as they are.
    - ``covered(book: Path) -> (page, item_ids)``: what the book covers
      (``stamp.covered``); the CLI asks for it with ``getattr``.
    - ``refresh_extras(book, payload, fresh, *, exported_at) -> RefreshExtras``:
      the pack's own cells for a new baseline that no declaration can say
      (HeavyBook's Checks figures), changes it cannot take in place, and
      notes. ``book`` is the reader's opened book, ``fresh`` the parsed
      payload. Patch and refresh call it through ``patch.verify.extras``.
    """

    name: str          # "heavybook", "fieldbook", "acme-bridge-book"
    version: str       # the pack's own version
    contract: str      # the contract major it targets, "1"

    def detect(self, facts: BookFacts) -> Verdict: ...

    def build(self, payload: dict, out: Path, *, options: dict) -> BuildReport: ...

    def read(self, book: Path) -> ReadResult: ...

    def patch(self, book: Path, change_set: object, result: ApplyResult,
              payload: dict) -> PatchReport: ...

    def refresh(self, book: Path, payload: dict, *, dry_run: bool = False) -> RefreshReport:
        """BidSheet.ai's changes since the book's baseline (``payload``, the
        fresh read model) written into the book in place, or reported
        (``exchange.refresh``); ``NotYet`` for a pack that cannot."""
        ...

    def templates(self) -> list[InsertKind]: ...

    def declaration(self) -> Declaration:
        """the pack's declaration (``exchange.declaration.load``): what the Navigator and the generic reader consume"""
        ...
