"""The bm-sync sidecar: what the last push to BidSheet.ai created, so the next one can diff."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class QuoteSync:
    quote_id: int
    revision: int
    vendor_id: int | None
    file_sha: str
    lines: dict[str, int] = field(default_factory=dict)      # item_no -> line_id


@dataclass
class PackageSync:
    work_package_id: int | None = None
    estimate_package_id: int | None = None
    synced_at: str | None = None
    spec_choice: dict | None = None
    bm_choice: dict | None = None
    # item_no -> [{"assembly_id", "component_id", "name"}] (see `plug_entry`)
    plugs_removed: dict[str, list[dict]] = field(default_factory=dict)
    quotes: dict[str, QuoteSync] = field(default_factory=dict)          # quote file name -> sync state


@dataclass
class Sidecar:
    project_id: int | None = None
    estimate_id: int | None = None
    packages: dict[str, PackageSync] = field(default_factory=dict)

    def package(self, name: str) -> PackageSync:
        """The sync state of a package, created empty on first access (exact spec name)."""
        return self.packages.setdefault(name, PackageSync())

    @classmethod
    def load(cls, path: Path) -> "Sidecar":
        path = Path(path)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        sc = cls(project_id=raw.get("project_id"), estimate_id=raw.get("estimate_id"))
        for name, p in (raw.get("packages") or {}).items():
            quotes = {k: QuoteSync(**q) for k, q in (p.get("quotes") or {}).items()}
            plugs = {item: [plug_entry(e) for e in entries]
                     for item, entries in (p.get("plugs_removed") or {}).items()}
            sc.packages[name] = PackageSync(**{**p, "quotes": quotes, "plugs_removed": plugs})
        return sc

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), sort_keys=True, indent=2) + "\n")


def plug_entry(value) -> dict:
    """A `plugs_removed` entry as `{"assembly_id", "component_id", "name"}`. A sidecar
    written before #428 holds `"<assembly_id>:<component_id>"` strings: those load with
    no name. Ids are ints when they look like ints."""
    if isinstance(value, dict):
        return {"assembly_id": _int(value.get("assembly_id")), "component_id": _int(value.get("component_id")),
                "name": value.get("name")}
    head, _, tail = str(value).partition(":")
    return {"assembly_id": _int(head), "component_id": _int(tail), "name": None}


def plug_key(entry: dict) -> tuple:
    """`(assembly_id, component_id)` of a `plugs_removed` entry, the identity readers compare on."""
    return (entry.get("assembly_id"), entry.get("component_id"))


def plug_text(entry: dict) -> str:
    """`<assembly_id>:<component_id> <name>` for a notice; just the ids when no name was recorded."""
    ids = f"{entry.get('assembly_id')}:{entry.get('component_id')}"
    return f"{ids} {entry['name']}" if entry.get("name") else ids


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


def file_sha(path: Path) -> str:
    """sha256 hex of the file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def choice_of(pkg: dict) -> dict:
    """The part of a spec package that decides who is awarded it."""
    return {"selected": pkg.get("selected", "ARR"), "pinned": bool(pkg.get("pinned")),
            "picks": {str(n): v for n, v in (pkg.get("picks") or {}).items()}}
