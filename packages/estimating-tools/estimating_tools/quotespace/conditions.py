"""Quote-condition records — scope folds + separate-acceptance flags
(EP-6, spec 2026-08-07-quote-scope-split-design.md).

Append-only JSONL at ``<bid working dir>/Subquotes/quote-conditions.jsonl``;
latest record per (work_package.name, vendor.org_name) pair wins — the same
journal idiom as ``solicitations.jsonl`` (helpers reused from ``model``).
The schema is the draft of the BM upstream ask: a
``separate_acceptance_permitted``/``acceptance_notes`` pair on
WorkPackageQuote plus scope-tag rows on quote lines.

Pure: stdlib only. MCP traffic stays at the skill layer."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from estimating_tools.quotespace.model import read_journal

TREATMENTS = ("separate", "folded")


@dataclass
class QuoteConditionRecord:
    """One vendor x one work package. ``separate_acceptance_permitted`` is
    tri-state: True / False / None (= unknown, the default when the quote is
    silent) — False MUST survive ``to_payload`` (drop-empties keeps False).

    ``scope_tags`` entries: ``{"group": str, "items": [{"schedule",
    "item_number"}], "treatment": "separate"|"folded",
    "folded_into": {"schedule", "item_number"} | None, "notes": str}``.
    A group's identity is its casefolded name across all vendors' records."""

    work_package: dict
    vendor: dict
    separate_acceptance_permitted: bool | None = None
    acceptance_notes: str = ""
    scope_tags: list[dict] = field(default_factory=list)
    notes: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        if not (self.work_package.get("name") or "").strip():
            raise ValueError("work_package.name is required")
        if not (self.vendor.get("org_name") or "").strip():
            raise ValueError("vendor.org_name is required")
        for tag in self.scope_tags:
            if not isinstance(tag, dict):
                raise ValueError("scope tag must be a JSON object")
            if not (tag.get("group") or "").strip():
                raise ValueError("scope tag requires a non-empty group name")
            treatment = tag.get("treatment")
            if treatment not in TREATMENTS:
                raise ValueError(
                    f"scope tag treatment must be one of {TREATMENTS}, "
                    f"got {treatment!r}")
            if treatment == "folded" and not tag.get("folded_into"):
                raise ValueError('treatment "folded" requires folded_into')
            if treatment == "separate" and tag.get("folded_into"):
                raise ValueError('treatment "separate" forbids folded_into')
            for item in tag.get("items") or []:
                if not isinstance(item, dict) or not (
                        (item.get("item_number") or "").strip()):
                    raise ValueError(
                        "scope tag items entries must be JSON objects with "
                        "a non-empty item_number")
            folded = tag.get("folded_into")
            if folded is not None and (
                    not isinstance(folded, dict)
                    or not (folded.get("item_number") or "").strip()):
                raise ValueError(
                    "folded_into must be a JSON object with a non-empty "
                    "item_number")
        if not self.record_id:
            self.record_id = f"qc-{uuid.uuid4()}"

    @classmethod
    def from_bm_quote(cls, quote: dict, *,
                      work_package_name: str) -> "QuoteConditionRecord":
        """Build a condition record from a BidSheet.ai quote export (BM#1045).

        get_quote / list_work_package_quotes serialize
        separate_acceptance_permitted, acceptance_notes, and scope_tags."""
        return cls(
            work_package={"name": work_package_name,
                          "bm_work_package_id": quote.get("work_package_id")},
            vendor={"org_name": quote.get("vendor_display_name")
                    or quote.get("vendor_name") or "",
                    "bm_vendor_id": quote.get("vendor_id")},
            separate_acceptance_permitted=quote.get("separate_acceptance_permitted"),
            acceptance_notes=quote.get("acceptance_notes") or "",
            scope_tags=list(quote.get("scope_tags") or []))

    def key(self) -> tuple[str, str]:
        return (self.work_package["name"].strip().casefold(),
                self.vendor["org_name"].strip().casefold())

    def to_payload(self) -> dict:
        """One JSONL line. Drops None/""/empty containers but keeps False."""
        out = {}
        for k, v in asdict(self).items():
            if v is None or (isinstance(v, str) and v == ""):
                continue
            if isinstance(v, (list, dict)) and not v:
                continue
            out[k] = v
        return out


def read_conditions(path: Path | str) -> list[QuoteConditionRecord]:
    return read_journal(path, QuoteConditionRecord)
