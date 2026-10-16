"""est-intake — project intake CLI: init, register, bid-frame, briefing.

Deterministic file operations only; all MCP calls live in the intake-project
skill, which feeds this CLI plain JSON/YAML files. Layout mirrors the Work
repo's `work` CLI (project shared dirs + B<bid>-<date> bid working dir);
inside the Work repo run `work project new` / `work bid new` first for the
xlsx seeding — every mkdir here is exist_ok, so layering is safe."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from estimating_tools.intake.bid_frame import normalize_bid_items, takeoff_map_skeleton
from estimating_tools.intake.briefing import build_briefing_pack
from estimating_tools.intake.manifest import ProjectManifest
from estimating_tools.profiles.scaffold import materialize_layout

_BID_NUMBER_RE = re.compile(r"[A-Za-z0-9._-]+")
_BID_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_manifest(project: str) -> tuple[Path, ProjectManifest]:
    base = Path(project)
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"no manifest at {manifest_path} — run 'est-intake init' first")
    return base, ProjectManifest.load(manifest_path)


def _bid_base(base: Path, manifest: ProjectManifest) -> Path | None:
    """The bid working dir, or None (caller reports) when init had no bid.
    Rejects a bid_dir that resolves outside the project root — manifest.json
    is hand-editable, so the stored value is not trusted as a path."""
    if not manifest.bid_dir:
        return None
    bid_base = (base / manifest.bid_dir).resolve()
    if not bid_base.is_relative_to(Path(base).resolve()):
        raise ValueError(
            f"manifest bid_dir {manifest.bid_dir!r} resolves outside the project root")
    return bid_base


def cmd_init(args) -> int:
    base = Path(args.parent) / args.name
    manifest_path = base / "manifest.json"
    if manifest_path.exists():
        print(f"refusing to init: {manifest_path} already exists")
        return 1
    bid_number = args.bid_number or None
    bid_date = args.bid_date or None
    if bool(bid_number) != bool(bid_date):
        print("--bid-number and --bid-date must be given together")
        return 1
    if bid_number and not _BID_NUMBER_RE.fullmatch(bid_number):
        print(f"invalid bid number {bid_number!r} — letters, digits, ., _, - only")
        return 1
    if bid_date and not _BID_DATE_RE.fullmatch(bid_date):
        print(f"invalid bid date {bid_date!r} — expected YYYY-MM-DD")
        return 1
    base.mkdir(parents=True, exist_ok=True)
    materialize_layout(base, "work-project", {"name": args.name})
    bid_dir = None
    if bid_number:
        bid_dir = f"B{bid_number}-{bid_date}"
        materialize_layout(base / bid_dir, "work-bid",
                           {"name": args.name, "bid_number": bid_number})
    manifest = ProjectManifest(
        name=args.name, organization_id=args.organization_id,
        bm_project_id=args.bm_project_id, project_ref=args.project_ref,
        bid_number=bid_number, bid_date=bid_date, bid_dir=bid_dir)
    manifest.save(manifest_path)
    where = f" + bid dir {bid_dir}" if bid_dir else ""
    print(f"initialized {base}{where} (manifest.json written)")
    return 0


def cmd_register(args) -> int:
    try:
        base, manifest = _load_manifest(args.project)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    f = Path(args.file)
    try:
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
    except OSError:
        print(f"cannot read {f}")
        return 1
    try:
        rel = f.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        print(f"{f} is outside the project root {base} — copy it into the "
              "project (e.g. Plans/) before registering")
        return 1
    manifest.register_document(rel, kind=args.kind, source=args.source,
                               sha256=digest, registered_at=_now())
    manifest.save(base / "manifest.json")
    print(f"registered {rel} ({args.kind}, {args.source})")
    return 0


def cmd_bid_frame(args) -> int:
    try:
        base, manifest = _load_manifest(args.project)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    try:
        raw = json.loads(Path(args.items).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such file: {args.items}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"invalid JSON in {args.items}: {exc}")
        return 1
    if not isinstance(raw, list):
        print(f"items JSON must be a list of bid items, got {type(raw).__name__}")
        return 1
    try:
        items = normalize_bid_items(raw)
    except ValueError as exc:
        print(exc)
        return 1
    manifest.set_bid_frame(items, snapshot_at=_now())
    manifest.save(base / "manifest.json")
    try:
        bid_base = _bid_base(base, manifest)
    except ValueError as exc:
        print(exc)
        return 1
    if bid_base is None:
        print(f"bid frame: {len(items)} items snapshotted; no bid dir on the "
              "manifest (re-run init with --bid-number), skipping takeoff_map skeleton")
        return 0
    if manifest.organization_id is None:
        print(f"bid frame: {len(items)} items snapshotted; no organization_id "
              "on the manifest, skipping takeoff_map skeleton")
        return 0
    skel = takeoff_map_skeleton(items, organization_id=manifest.organization_id,
                                project_ref=manifest.project_ref)
    out = bid_base / "Takeoff" / "takeoff_map.skel.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(skel, encoding="utf-8")
    print(f"bid frame: {len(items)} items snapshotted; seeded {out}")
    return 0


def cmd_briefing(args) -> int:
    try:
        base, manifest = _load_manifest(args.project)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    try:
        bid_base = _bid_base(base, manifest)
    except ValueError as exc:
        print(exc)
        return 1
    if bid_base is None:
        print("no bid dir on the manifest — re-run init with --bid-number/--bid-date")
        return 1
    try:
        spec = yaml.safe_load(Path(args.structures).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        print(f"no such file: {args.structures}")
        return 1
    except yaml.YAMLError as exc:
        print(f"invalid YAML in {args.structures}: {exc}")
        return 1
    if not isinstance(spec, dict):
        print("structures YAML must be a mapping with a 'structures' list")
        return 1
    structures = spec.get("structures", [])
    if not isinstance(structures, list) or not all(isinstance(s, dict) for s in structures):
        print("structures must be a list of mappings")
        return 1
    try:
        created = build_briefing_pack(manifest, structures, bid_base)
    except ValueError as exc:
        print(exc)
        return 1
    print(f"briefing pack: {len(created)} files created "
          f"({len(structures)} structures; existing files untouched)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-intake",
                                     description="Project intake: scaffold, manifest, bid frame, briefing pack.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Scaffold a Work-layout project (+ optional bid dir) and write its manifest.")
    p.add_argument("name")
    p.add_argument("--parent", default=".")
    p.add_argument("--bid-number", default=None, help="e.g. 1042 -> creates B1042-<date>/")
    p.add_argument("--bid-date", default=None, help="ISO date, e.g. 2026-07-16")
    p.add_argument("--organization-id", type=int, default=None)
    p.add_argument("--bm-project-id", type=int, default=None)
    p.add_argument("--project-ref", default=None)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("register", help="Register a document in the manifest.")
    p.add_argument("project")
    p.add_argument("file")
    p.add_argument("--kind", required=True,
                   choices=["plans", "specs", "addenda", "conformance", "other"])
    p.add_argument("--source", default="local",
                   choices=["local", "bidmanager", "conformed"])
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("bid-frame", help="Snapshot bid items (JSON) into the manifest; seed takeoff_map.skel.yaml.")
    p.add_argument("project")
    p.add_argument("--items", required=True, help="JSON file: raw list_bid_items output.")
    p.set_defaults(func=cmd_bid_frame)

    p = sub.add_parser("briefing", help="Build the briefing-pack skeleton from a structures.yaml.")
    p.add_argument("project")
    p.add_argument("--structures", required=True)
    p.set_defaults(func=cmd_briefing)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
