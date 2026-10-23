"""The work file the extraction agent reads, and the results file it writes back."""
from __future__ import annotations

import copy
import json
from datetime import datetime
from importlib import resources
from pathlib import Path

from estimating_tools.estimate_spec.package_frames import PackageError, build_package_frames
from estimating_tools.quotes.intake.inventory import Document, Inventory
from estimating_tools.quotes.intake.text import image_paths, text_path

BATCH_VERSION = 1


def package_digest(spec: dict) -> list[dict]:
    """One entry per work package: its name, kind, scope, condition keys and lines."""
    # The digest levels no quotes, so the selector (a vendor name, per-item
    # picks, CARRY prices) has nothing to resolve against: neutralise it.
    bare = copy.deepcopy(spec)
    for pkg in bare.get("work_packages") or []:
        pkg["selected"] = "ARR"
        pkg.pop("picks", None)
        pkg.pop("carry", None)
    frames = build_package_frames(bare, [], spare_columns=0, taken=set())
    items = {str(i["item_no"]): i for i in spec.get("items") or []}
    default = spec.get("schedule") or "Base"
    out = []
    for pkg, frame in zip(spec.get("work_packages") or [], frames):
        lines = []
        for ln in frame.lines:
            if ln.item_no not in items:
                raise PackageError(f"{frame.name}: item '{ln.item_no}' is not in the spec")
            meta = items[ln.item_no].get("scaffold_meta") or {}
            lines.append({"schedule_name": meta.get("schedule") or default,
                          "item_number": ln.item_no, "line_name": ln.name,
                          "uom": ln.uom,
                          "qty": ln.qty if isinstance(ln.qty, (int, float)) else None})
        out.append({"name": frame.name, "kind": frame.kind, "scope": pkg.get("scope"),
                    "conditions": list(frame.conditions), "lines": lines})
    return out


def load_instructions() -> str:
    root = resources.files("estimating_tools.quotes.intake")
    return (root / "prompts" / "extract.md").read_text(encoding="utf-8")


def load_schema() -> dict:
    root = resources.files("estimating_tools.quotes.intake")
    return json.loads((root / "schemas" / "extract-result.schema.json").read_text(encoding="utf-8"))


def batch_candidates(inv: Inventory, state_dir: Path, *,
                     include_held: bool = False) -> tuple[list[Document], int]:
    """The documents a batch offers, and how many vision documents were held back
    because their pages are not rendered."""
    statuses = {"new", "held"} if include_held else {"new"}
    docs: list[Document] = []
    not_rendered = 0
    for doc in inv:
        if doc.route not in ("text", "vision") or doc.status not in statuses:
            continue
        if doc.route == "vision" and image_paths(doc, state_dir) is None:
            not_rendered += 1
            continue
        docs.append(doc)
    return docs, not_rendered


def _doc_entry(doc: Document, state_dir: Path) -> dict:
    entry = {"sha256": doc.sha256, "file_name": doc.file_name, "kind": doc.kind,
             "route": doc.route}
    if doc.route == "text":
        entry["text_path"] = str(Path(text_path(state_dir, doc.sha256)).resolve())
    else:
        entry["image_paths"] = [str(Path(p).resolve()) for p in image_paths(doc, state_dir)]
    return entry


def _batch_path(state_dir: Path) -> Path:
    folder = Path(state_dir) / "batches"
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path, n = folder / f"{stamp}.json", 1
    while path.exists():
        n += 1
        path = folder / f"{stamp}-{n}.json"
    return path


def write_batch(inv: Inventory, spec: dict, state_dir: Path, *, limit: int | None = None,
                include_held: bool = False, out: Path | None = None) -> tuple[Path | None, int]:
    """Write the work file. No record's status changes: a document stays offered
    until an import names it. Each offered record notes the batch in `offered_in`."""
    docs, not_rendered = batch_candidates(inv, state_dir, include_held=include_held)
    if limit is not None:
        docs = docs[:limit]
    if not docs:
        return None, not_rendered
    payload = {"stage": "extract", "schema_version": BATCH_VERSION,
               "instructions": load_instructions(), "packages": package_digest(spec),
               "docs": [_doc_entry(d, state_dir) for d in docs]}
    path = Path(out) if out is not None else _batch_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for doc in docs:
        doc.offered_in.append(path.name)
    inv.touch()
    return path, not_rendered


class ResultsError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _json_path(error) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in error.absolute_path)


def validate_results(payload) -> None:
    """Raise `ResultsError` listing every schema error and every cross-result defect."""
    import jsonschema

    errors: list[str] = []
    results = payload.get("results") if isinstance(payload, dict) else None

    def label(i: int) -> str:
        sha = results[i].get("sha256") if isinstance(results[i], dict) else None
        return f"result {i} ({sha[:8] if isinstance(sha, str) and sha else '?'})"

    for err in sorted(jsonschema.Draft202012Validator(load_schema()).iter_errors(payload),
                      key=lambda e: list(map(str, e.absolute_path))):
        path = list(err.absolute_path)
        if len(path) >= 2 and path[0] == "results" and isinstance(path[1], int) and results:
            rest = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in path[2:])
            errors.append(f"{label(path[1])}: {rest}: {err.message}")
        else:
            errors.append(f"{_json_path(err)}: {err.message}")

    if isinstance(results, list):
        seen: dict[tuple, int] = {}
        by_document: dict[str, list[str]] = {}
        for i, res in enumerate(results):
            if not isinstance(res, dict):
                continue
            if res.get("doc_type") == "quote":
                for key in ("vendor_name", "work_package_name"):
                    if not isinstance(res.get(key), str) or not res[key].strip():
                        errors.append(f"{label(i)}: a quote result needs {key}")
            sha, pkg = res.get("sha256"), res.get("work_package_name")
            if isinstance(sha, str):
                by_document.setdefault(sha, []).append(res.get("doc_type"))
            if isinstance(sha, str) and isinstance(pkg, str) and pkg:
                key = (sha, pkg.strip().casefold())
                if key in seen:
                    errors.append(f"results {seen[key]} and {i} both cover "
                                  f"{sha[:8]} on {pkg}")
                else:
                    seen[key] = i
            lines_seen: set[tuple] = set()
            lines = res.get("lines")
            for ln in lines if isinstance(lines, list) else []:
                # An alternate may repeat the priced line's key: the frames show it
                # under the vendor in the conditions grid.
                if not isinstance(ln, dict) or ln.get("is_alternate") is True:
                    continue
                item, name = ln.get("item_number"), ln.get("line_name")
                if not isinstance(item, str) or not (name is None or isinstance(name, str)):
                    continue
                if (item, name) in lines_seen:
                    errors.append(f"{label(i)}: two lines on item {item} / {name}")
                lines_seen.add((item, name))
        for sha, kinds in by_document.items():
            if len(kinds) > 1 and any(kind in ("not_quote", "unreadable") for kind in kinds):
                errors.append(f"{sha[:8]}: non-quote classifications must name a document once")
    if errors:
        raise ResultsError(errors)


def read_results(path: Path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResultsError([f"{Path(path).name}: cannot read results: {exc}"]) from exc
    if not isinstance(payload, dict):
        raise ResultsError([f"{Path(path).name}: results file must be a JSON object"])
    validate_results(payload)
    return payload
