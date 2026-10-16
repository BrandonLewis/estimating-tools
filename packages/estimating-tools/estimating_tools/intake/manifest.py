"""The project manifest — what was intaken, and the project's bid frame.

Pure: stdlib only. Lives at <project>/manifest.json (project root; document
paths are project-root-relative posix). The bid frame is the snapshot of
BidSheet.ai bid schedules/items: the official agency quantities (immutable —
BM #984) and the (schedule, item_number) keys the estimate-structures takeoff
push and price-estimate resolve rows by.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VALID_KINDS = ("plans", "specs", "addenda", "conformance", "other")
VALID_SOURCES = ("local", "bidmanager", "conformed")


@dataclass
class ManifestDocument:
    path: str            # project-root-relative, posix separators
    kind: str
    source: str
    sha256: str
    registered_at: str   # ISO-8601 UTC

    def __post_init__(self):
        if self.kind not in VALID_KINDS:
            raise ValueError(
                f"invalid document kind {self.kind!r} (expected one of {list(VALID_KINDS)})")
        if self.source not in VALID_SOURCES:
            raise ValueError(
                f"invalid document source {self.source!r} (expected one of {list(VALID_SOURCES)})")


@dataclass
class BidFrameItem:
    item_number: str
    schedule: str | None = None
    item_code: str | None = None
    description: str = ""
    unit: str = ""
    project_bid_item_id: int | None = None
    estimated_quantity: float | None = None


@dataclass
class ProjectManifest:
    name: str
    organization_id: int | None = None
    bm_project_id: int | None = None
    project_ref: str | None = None
    bid_number: str | None = None
    bid_date: str | None = None      # ISO date
    bid_dir: str | None = None       # project-root-relative bid working dir
    documents: list = field(default_factory=list)   # ManifestDocument
    bid_frame: list = field(default_factory=list)   # BidFrameItem
    bid_frame_snapshot_at: str | None = None
    version: int = 1

    def register_document(self, path: str, *, kind: str, source: str,
                          sha256: str, registered_at: str) -> ManifestDocument:
        """Add or replace (by path) a document record. Returns the record."""
        doc = ManifestDocument(path=path, kind=kind, source=source,
                               sha256=sha256, registered_at=registered_at)
        self.documents = [d for d in self.documents if d.path != path] + [doc]
        return doc

    def set_bid_frame(self, items: list, *, snapshot_at: str) -> None:
        self.bid_frame = list(items)
        self.bid_frame_snapshot_at = snapshot_at

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "ProjectManifest":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(
                f"manifest JSON must be a JSON object, got {type(data).__name__}")
        if "name" not in data:
            raise ValueError("manifest JSON is missing required 'name'")
        docs_data = data.get("documents", [])
        if not isinstance(docs_data, list):
            raise ValueError("manifest 'documents' must be a list")
        frame_data = data.get("bid_frame", [])
        if not isinstance(frame_data, list):
            raise ValueError("manifest 'bid_frame' must be a list")
        docs = [ManifestDocument(**d) for d in docs_data]
        frame = [BidFrameItem(**i) for i in frame_data]
        return cls(
            name=data["name"],
            organization_id=data.get("organization_id"),
            bm_project_id=data.get("bm_project_id"),
            project_ref=data.get("project_ref"),
            bid_number=data.get("bid_number"),
            bid_date=data.get("bid_date"),
            bid_dir=data.get("bid_dir"),
            documents=docs,
            bid_frame=frame,
            bid_frame_snapshot_at=data.get("bid_frame_snapshot_at"),
            version=data.get("version", 1),
        )

    def save(self, path: Path) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ProjectManifest":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
