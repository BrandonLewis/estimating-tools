"""The sha256-keyed inventory of quote documents, and the folders it lives in."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path


@dataclass
class Document:
    sha256: str
    paths: list[str]
    first_seen: str
    size: int
    kind: str
    route: str | None = None
    pages: int | None = None
    status: str = "new"
    reason: str | None = None
    parent: str | None = None
    superseded_by: str | None = None
    results: list[dict] = field(default_factory=list)
    #: Result entries a `requeue` cleared: kept, so the importer still knows which
    #: quote file this document's earlier extraction went into.
    requeued_from: list[dict] = field(default_factory=list)
    #: The batch files (by name) that have offered this document.
    offered_in: list[str] = field(default_factory=list)

    @property
    def file_name(self) -> str:
        return Path(self.paths[0]).name

    @property
    def short(self) -> str:
        return self.sha256[:8]


_DOC_KEYS = {f.name for f in fields(Document)}


class Inventory:
    def __init__(self, path: Path, documents: dict[str, Document] | None = None):
        self.path = path
        self._docs: dict[str, Document] = documents if documents is not None else {}
        #: Set by every change made through the library; `save()` clears it. Not persisted.
        self.dirty = False

    def touch(self) -> None:
        """Mark the inventory changed, so a caller saving `if inv.dirty` writes it."""
        self.dirty = True

    @classmethod
    def load(cls, state_dir: Path) -> "Inventory":
        path = Path(state_dir) / "inventory.json"
        if not path.exists():
            return cls(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        docs = {sha: Document(**{k: v for k, v in rec.items() if k in _DOC_KEYS})
                for sha, rec in raw.get("documents", {}).items()}
        return cls(path, docs)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1,
                "documents": {sha: asdict(d) for sha, d in self._docs.items()}}
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self.dirty = False

    def get(self, sha: str) -> Document | None:
        return self._docs.get(sha)

    def find(self, prefix: str) -> Document:
        prefix = prefix.lower()
        hits = [d for sha, d in self._docs.items() if len(prefix) >= 8 and sha.startswith(prefix)]
        if not hits:
            raise ValueError(f"no document {prefix}")
        if len(hits) > 1:
            raise ValueError(f"ambiguous {prefix}")
        return hits[0]

    def add(self, doc: Document) -> None:
        self._docs[doc.sha256] = doc
        self.dirty = True

    def requeue(self, doc: Document) -> None:
        """Reopen `doc` for the next batch. Its result entries move to
        `requeued_from` (not dropped), so a new extraction still finds the quote
        file the old one went into."""
        doc.requeued_from.extend(doc.results)
        doc.status, doc.reason, doc.results = "new", None, []
        self.dirty = True

    def by_path(self, path: str) -> Document | None:
        for doc in self._docs.values():
            if doc.superseded_by is None and path in doc.paths:
                return doc
        return None

    def all(self) -> list[Document]:
        return sorted(self._docs.values(), key=lambda d: (d.first_seen, d.sha256))

    def __iter__(self):
        return iter([d for d in self.all() if d.superseded_by is None])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# The folders are resolved: the paths the inventory stores must not depend on the
# working directory a later command runs from.
def quotes_dir_for(spec_path: Path, spec: dict) -> Path:
    return (Path(spec_path).parent / (spec.get("work_packages_quotes_dir") or "quotes")).resolve()


def state_dir_for(spec_path: Path, spec: dict) -> Path:
    return quotes_dir_for(spec_path, spec) / "_intake"


def inbox_dir_for(spec_path: Path, spec: dict, override: str | None = None) -> Path:
    rel = override or spec.get("work_packages_inbox_dir") or "../Subquotes/inbox"
    return (Path(spec_path).parent / rel).resolve()
