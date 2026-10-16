"""Solicitation records — the quote-space journal (Phase 6).

Append-only JSONL at ``<bid working dir>/Subquotes/solicitations.jsonl``; the
latest record for a (work_package.name, vendor.org_name) pair wins — the
quote-revisions idiom: history preserved, last line is current state. The
schema is the draft of the BidSheet.ai upstream solicitation API (see the
Phase 6 spec's upstream asks). Received/leveled/awarded are DERIVED by
``coverage.py``, never stored here — one source of truth per fact.

Pure: stdlib only. MCP traffic stays at the skill layer."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHANNELS = ("email", "phone", "portal", "other")
STATUSES = ("planned", "sent", "declined")


@dataclass
class SolicitationRecord:
    """One vendor x one work package. ``items`` carries the covered bid items
    as Phase-1 bid-frame keys ``{"schedule", "item_number"}``; an empty list
    means "every item in the package"."""

    work_package: dict                      # {"name": str, "bm_work_package_id": int|None}
    vendor: dict                            # {"org_name": str, "bm_vendor_id": int|None}
    contacts: list[str] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    sent_at: str = ""                       # YYYY-MM-DD; required once status == "sent"
    channel: str = "email"
    status: str = "planned"
    notes: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        if not (self.work_package.get("name") or "").strip():
            raise ValueError("work_package.name is required")
        if not (self.vendor.get("org_name") or "").strip():
            raise ValueError("vendor.org_name is required")
        if self.channel not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}, got {self.channel!r}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")
        if self.status == "sent" and not self.sent_at:
            raise ValueError("a sent record requires sent_at (YYYY-MM-DD)")
        if not self.record_id:
            self.record_id = f"sol-{uuid.uuid4()}"

    @classmethod
    def from_bm(cls, row: dict, *, work_package_name: str,
                vendor_org_name: str) -> "SolicitationRecord":
        """Build a record from a BidSheet.ai list_solicitations row (BM#1020).

        BM rows are flat and carry ids; the skill resolves the work-package
        and vendor names (it has both) and passes them in."""
        return cls(
            work_package={"name": work_package_name,
                          "bm_work_package_id": row.get("work_package_id")},
            vendor={"org_name": vendor_org_name,
                    "bm_vendor_id": row.get("vendor_id")},
            contacts=list(row.get("contacts") or []),
            items=list(row.get("items") or []),
            sent_at=row.get("sent_at") or "",
            channel=row.get("channel") or "email",
            status=row.get("status") or "planned",
            notes=row.get("notes") or "")

    def key(self) -> tuple[str, str]:
        return (self.work_package["name"].strip().casefold(),
                self.vendor["org_name"].strip().casefold())

    def content_signature(self) -> tuple:
        """Order-insensitive content fingerprint for sync diffing.

        Items are compared by canonical JSON (key-order-insensitive) and
        contacts as a sorted list, so a BM ``list_solicitations`` row that
        differs from the journal only in serialization order does NOT read as a
        change — the diff idiom depends on this to avoid revision spam. Both
        the local record and the BM-sourced record go through this one method,
        so the two sides normalize identically."""
        return (
            self.status, self.sent_at, self.channel,
            tuple(sorted(self.contacts)),
            tuple(sorted(json.dumps(i, sort_keys=True) for i in self.items)),
            self.notes)

    def to_payload(self) -> dict:
        """One JSONL line / draft-API kwargs. Drops unset ("", None, empty
        containers) but keeps 0 and False."""
        out = {}
        for k, v in asdict(self).items():
            if v is None or (isinstance(v, str) and v == ""):
                continue
            if isinstance(v, (list, dict)) and not v:
                continue
            out[k] = v
        return out


def append_records(path: Path | str, records: list[SolicitationRecord]) -> Path:
    """Append records as JSONL lines — accepts any record exposing ``to_payload()``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_payload()) + "\n")
    return path


def read_journal(path: Path | str, record_cls=None) -> list:
    """Read a journal of `record_cls` lines (default SolicitationRecord).

    Works for any journal record class with this constructor/validation
    contract (``**data`` kwargs, ValueError on invalid)."""
    record_cls = record_cls or SolicitationRecord
    path = Path(path)
    if not path.is_file():
        return []
    records = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {n} of {path}: {exc}") from exc
        try:
            records.append(record_cls(**data))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid record on line {n} of {path}: {exc}") from exc
    return records


def current_records(records: list[SolicitationRecord]) -> dict[tuple[str, str], SolicitationRecord]:
    """Latest record per (package, vendor) key wins."""
    current: dict[tuple[str, str], SolicitationRecord] = {}
    for rec in records:
        current[rec.key()] = rec
    return current
