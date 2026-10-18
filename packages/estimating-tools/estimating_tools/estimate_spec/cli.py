"""est-estimate — build / scaffold / apply-takeoff for estimate specs.

Subcommands:
  build          render a *.estimate.yaml to .xlsx (the original surface;
                 `est-estimate <config.yaml>` without a subcommand still works)
  scaffold       manifest.json bid frame + structures.yaml [+ scaffolds.json]
                 -> a schema-valid *.estimate.yaml skeleton (scaffold.py)
  apply-takeoff  CanonicalTakeoff JSON -> item qty + takeoff geometry (apply.py)
  scaffold-save  priced *.estimate.yaml -> BidItemScaffold payload JSON
                 (scaffold_save.py; the save-scaffolds skill does the writes)
  cip-buildup    render a CIP concrete-structure JSON config to a buildup
                 .xlsx (Rates / per-structure / Summary [/ Sub Spread]);
                 --init writes a sample config (cip.py)
  summarize      price a *.estimate.yaml in pure Python and print per-item
                 totals + the bid — openpyxl never evaluates formulas, so
                 this is how the number is known before Excel opens the
                 workbook (summarize.py; arithmetic-consistency only, NOT
                 a rate check)
  read-back      an edited fieldbook workbook -> the updated spec and a
                 Markdown report; a dry run unless --write, which first
                 saves a timestamped backup of the spec (readback/)

Deterministic file operations only; MCP lookups stay at the skill layer
(build-estimate-workbook fetches BM bid-item scaffolds to scaffolds.json)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

_SUBCOMMANDS = ("build", "scaffold", "apply-takeoff", "scaffold-save",
                "cip-buildup", "summarize", "read-back")


def cmd_build(args) -> int:
    """Render the workbook.

    Every predictable input defect gets a sentence and an exit code, the way
    cmd_cip and cmd_summarize do: a missing file, unparseable YAML, or a spec
    the pack refuses is a user error, not a traceback.
    """
    from estimating_tools.addin.brand import workbook_brand
    from estimating_tools.estimate_spec.build import build
    from estimating_tools.estimate_spec.recipe import RecipeError

    pack = _resolve_pack_or_report(args)
    if pack is None:
        return 2
    brand = None if args.no_brand else workbook_brand(_load_profile())
    try:
        out = build(args.config, args.output, pack=pack,
                    stamp=not args.no_stamp, lint=not args.no_lint, brand=brand)
    except FileNotFoundError:
        print(f"no such file: {args.config}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"invalid YAML in {args.config}: {exc}", file=sys.stderr)
        return 1
    except (RecipeError, ValueError, KeyError, TypeError) as exc:
        # ValueError is what validate_cross_references raises; RecipeError
        # names the offending unit or recipe; KeyError is a spec missing a
        # field the pack requires.
        print(f"invalid spec {args.config}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"could not write the workbook: {exc}", file=sys.stderr)
        return 1
    print("WROTE:", out)
    return 0


def cmd_cip(args) -> int:
    from estimating_tools.estimate_spec.cip import SAMPLE, build
    if args.init:
        Path(args.init).write_text(json.dumps(SAMPLE, indent=2),
                                   encoding="utf-8")
        print("Wrote sample config:", args.init)
        return 0
    if not args.config:
        print("provide a config JSON (or use --init to create one)")
        return 1
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such file: {args.config}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"invalid JSON in {args.config}: {exc}")
        return 1
    cfg_path = Path(args.config)
    out = Path(args.output or config.get("output")
               or cfg_path.with_suffix(".xlsx"))
    if not out.is_absolute():
        out = cfg_path.resolve().parent / out
    try:
        print("WROTE:", build(config, str(out)))
    except ValueError as exc:
        print(f"invalid config: {exc}")
        return 1
    return 0


def cmd_summarize(args) -> int:
    from estimating_tools.estimate_spec.format_pack import FormatPackError, require_support
    from estimating_tools.estimate_spec.summarize import (
        FormulaError, render_summary, summarize)
    pack = _resolve_pack_or_report(args)
    if pack is None:
        return 2
    try:
        require_support(pack, "summarize")
    except FormatPackError as exc:
        print(f"format pack error: {exc}", file=sys.stderr)
        return 2
    try:
        spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        print(f"no such file: {args.spec}")
        return 1
    except yaml.YAMLError as exc:
        print(f"invalid YAML in {args.spec}: {exc}")
        return 1
    if not isinstance(spec, dict):
        print(f"invalid spec: expected a mapping, got {type(spec).__name__}")
        return 1
    try:
        print(render_summary(summarize(spec, pack=pack)))
    except (FormulaError, KeyError, TypeError) as exc:
        print(f"invalid spec: {exc}")
        return 1
    return 0


def _load_profile():
    """Active org profile, or an empty one (profiles are optional here)."""
    try:
        from estimating_tools.profiles.loader import load
        return load()
    except Exception:  # jsonschema missing, malformed profile — stay agnostic
        from estimating_tools.profiles.model import Profile
        return Profile(data={})


def _profile_for_pack():
    """The org profile, loaded strictly for pack resolution (Decision 5).

    With no profile directory configured this is the empty profile. When
    ESTIMATING_PROFILES names at least one directory, a profile that fails to
    load, or one whose raw profile.yaml sets `estimating.format` that field
    validation then dropped, raises FormatPackError — a pack the org named is
    never silently replaced by the bundled one.
    """
    from estimating_tools.estimate_spec.format_pack import FormatPackError
    from estimating_tools.profiles.model import Profile

    try:
        from estimating_tools.profiles.loader import discover, load, load_one
    except ImportError:  # profiles extras missing: nothing can be configured
        return Profile(data={})
    dirs = discover()
    if not dirs:
        return Profile(data={})
    try:
        profile = load(dirs)
        for d in dirs:
            # Checked per directory, so one layer's dropped format is not
            # masked by another layer's valid one.
            raw = yaml.safe_load((Path(d) / "profile.yaml").read_text(encoding="utf-8"))
            est = raw.get("estimating") if isinstance(raw, dict) else None
            if (isinstance(est, dict) and est.get("format")
                    and not (load_one(d).get("estimating") or {}).get("format")):
                raise FormatPackError(
                    f"profile {d} sets estimating.format but its estimating "
                    "section failed validation and was dropped (see the warning)")
    except FormatPackError:
        raise
    except Exception as exc:  # noqa: BLE001 — any load failure is fatal here
        raise FormatPackError(f"org profile could not be loaded: {exc}") from exc
    return profile


def _resolve_pack_or_report(args, *, writes=None):
    """The pack named by --format / the org profile / the bundled pack,
    or None after printing why it could not be loaded.

    `writes=VERB` additionally refuses a pack nothing named: the verbs that
    write a pack-shaped artifact from non-spec inputs must not take their
    shapes from `resolve_pack`'s silent last resort. See `require_chosen`.
    """
    from estimating_tools.estimate_spec.format_pack import (
        FormatPackError, require_chosen, resolve_pack)

    try:
        cli_path = getattr(args, "format", None)
        pack = resolve_pack(cli_path, None if cli_path else _profile_for_pack())
        if writes:
            require_chosen(pack, writes)
        return pack
    except FormatPackError as exc:
        print(f"format pack error: {exc}", file=sys.stderr)
        return None


def cmd_scaffold(args) -> int:
    from estimating_tools.estimate_spec.scaffold import (
        load_profile_scaffolds, load_scaffolds_file, merge_scaffold,
        scaffold_spec, validate_spec)
    from estimating_tools.intake.manifest import ProjectManifest

    profile = _load_profile()
    pack = _resolve_pack_or_report(args, writes="scaffold")
    if pack is None:
        return 2

    try:
        manifest = ProjectManifest.load(Path(args.manifest))
    except FileNotFoundError:
        print(f"no such file: {args.manifest}")
        return 1
    except ValueError as exc:
        print(f"invalid manifest: {exc}")
        return 1

    structures = []
    if args.structures:
        try:
            doc = yaml.safe_load(Path(args.structures).read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            print(f"no such file: {args.structures}")
            return 1
        except yaml.YAMLError as exc:
            print(f"invalid YAML in {args.structures}: {exc}")
            return 1
        structures = doc.get("structures", []) if isinstance(doc, dict) else []

    mob_codes = tuple(profile.section("estimating").get("mob_item_codes") or ())

    # Bridge 3 precedence: scaffolds.json (BM catalog, agent-fetched) wins
    # over the org profile's estimate_scaffolds.yaml; blank skeleton last.
    entries: dict = {}
    try:
        entries.update(load_profile_scaffolds(profile.sources, pack=pack))
        if args.scaffolds:
            entries.update(load_scaffolds_file(Path(args.scaffolds), pack=pack))
    except FileNotFoundError as exc:
        print(f"no such file: {exc.filename or exc}")
        return 1
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"invalid scaffolds: {exc}")
        return 1

    try:
        result = scaffold_spec(
            manifest, structures, items=args.items, scaffold_entries=entries,
            mob_codes=mob_codes,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            pack=pack)
    except ValueError as exc:
        print(exc)
        return 1

    out = Path(args.output)
    spec = result.spec
    merge_note = ""
    if out.exists():
        if not args.merge:
            print(f"refusing to overwrite {out} — pass --merge to update "
                  "scaffold-owned fields in place")
            return 2
        existing = yaml.safe_load(out.read_text(encoding="utf-8")) or {}
        spec, report = merge_scaffold(existing, spec)
        merge_note = (f"; merged (updated {len(report.updated)}, "
                      f"added {len(report.added)}, skipped {len(report.skipped)}, "
                      f"kept {len(report.kept)})")
        for item_no, reason in report.skipped:
            print(f"  merge: {item_no} skipped — {reason}")

    try:
        validate_spec(spec, pack=pack)
    except ValueError as exc:
        print(f"scaffold produced an invalid spec (bug): {exc}")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    prefills = f", {len(result.prefilled)} prefilled" if result.prefilled else ""
    host = " (+ rate-host sheet: no mob item selected)" if result.injected_rate_host else ""
    print(f"scaffolded {len(result.selected)} items{prefills}{host} -> {out}{merge_note}")
    return 0


def cmd_apply_takeoff(args) -> int:
    from estimating_tools.estimate_spec.apply import apply_takeoff, render_apply_report
    from estimating_tools.estimate_spec.scaffold import validate_spec
    from estimating_tools.takeoff.model import CanonicalTakeoff

    pack = _resolve_pack_or_report(args, writes="apply-takeoff")
    if pack is None:
        return 2

    spec_path = Path(args.spec)
    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        print(f"no such file: {spec_path}")
        return 1
    except yaml.YAMLError as exc:
        print(f"invalid YAML in {spec_path}: {exc}")
        return 1
    try:
        takeoff = CanonicalTakeoff.from_json(
            Path(args.takeoff).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such file: {args.takeoff}")
        return 1
    except (ValueError, TypeError) as exc:
        print(f"invalid takeoff JSON: {exc}")
        return 1

    result = apply_takeoff(spec, takeoff, pack=pack, force=args.force)
    try:
        validate_spec(result.spec, pack=pack)
    except ValueError as exc:
        print(f"apply-takeoff produced an invalid spec (bug): {exc}")
        return 1
    changed = bool(result.matched)
    if changed:
        spec_path.write_text(
            yaml.safe_dump(result.spec, sort_keys=False, allow_unicode=True),
            encoding="utf-8")
    report = render_apply_report(result)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
        print(f"report -> {args.report}")
    print(f"{len(result.matched)} applied, {len(result.unchanged)} unchanged, "
          f"{len(result.skipped)} skipped, {len(result.unmatched_rows)} unmatched "
          f"rows, {len(result.unmatched_items)} unmatched items"
          + ("" if changed else " (spec unchanged on disk)"))
    if result.skipped and not args.force:
        for s in result.skipped:
            print(f"  skipped: {s['item_no']} — {s['reason']}")
    return 0


def cmd_scaffold_save(args) -> int:
    # Errors to stderr (the est-hist convention) so the payload path and
    # skip reasons on stdout stay clean for the calling skill.
    from estimating_tools.estimate_spec.scaffold_save import extract_scaffold_saves

    pack = _resolve_pack_or_report(args, writes="scaffold-save")
    if pack is None:
        return 2

    spec_path = Path(args.spec)
    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        print(f"no such file: {args.spec}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"invalid spec YAML: {exc}", file=sys.stderr)
        return 1
    if not isinstance(spec, dict):
        print(f"invalid spec YAML: expected a mapping, "
              f"got {type(spec).__name__}", file=sys.stderr)
        return 1
    code_map = {}
    if args.code_map:
        try:
            code_map = json.loads(Path(args.code_map).read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"no such file: {args.code_map}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"invalid code map JSON: {exc}", file=sys.stderr)
            return 1
        if not isinstance(code_map, dict):
            print(f"invalid code map JSON: expected an object, "
                  f"got {type(code_map).__name__}", file=sys.stderr)
            return 1
    saves, skipped = extract_scaffold_saves(
        spec, agency=args.agency, project_ref=args.project_ref,
        saved_on=date.today().isoformat(), code_map=code_map, pack=pack)
    out = Path(args.output or spec_path.with_suffix(".scaffold_saves.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"saves": saves, "skipped": skipped}, indent=2),
                   encoding="utf-8")
    print("WROTE:", out, f"({len(saves)} saves, {len(skipped)} skipped)")
    for s in skipped:
        print(f"  ! item {s['item_no']}: {s['reason']}")
    return 0


def _emit(text: str, *, file=None) -> None:
    """Print `text`, even to a console whose code page cannot show it (a
    Windows console piped through cp1252): the report's arrows and dots
    come out as escapes there instead of a UnicodeEncodeError."""
    try:
        print(text, file=file)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"), file=file)


def _backup_path(spec_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = spec_path.with_name(f"{spec_path.name}.bak-{stamp}")
    n = 2
    while backup.exists():
        backup = spec_path.with_name(f"{spec_path.name}.bak-{stamp}-{n}")
        n += 1
    return backup


def _same_file(a: Path, b: Path) -> bool:
    """Do `a` and `b` name one file -- by another case on a case-folding file
    system, relative vs absolute, through `..` or a symlink? `samefile` when
    both exist, else the normalised real paths."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def cmd_read_back(args) -> int:
    """Read an edited fieldbook workbook back into its spec.

    Prints the report (and writes it to --report). Exit 0: read -- a dry
    run, or written with --write, or nothing to write. Exit 1: problems
    that block writing (the report lists them; nothing is written) --
    including a workbook built from an older version of the spec, unless
    --force. Exit 2: refused -- a file cannot be read, or the workbook is not
    a fieldbook workbook built from this spec.
    """
    try:
        from ruamel.yaml import YAMLError

        from estimating_tools.estimate_spec.readback.spec_io import SpecYaml, SpecYamlError
    except ImportError:
        _emit("read-back needs ruamel.yaml: pip install 'estimating_tools[estimate_spec]'",
              file=sys.stderr)
        return 2
    from estimating_tools.estimate_spec.readback import (
        ReadBackRefused, load_workbook, read_back, render_report)

    spec_path = Path(args.spec)
    if args.report:
        for what, path in (("spec", spec_path), ("workbook", Path(args.workbook))):
            if _same_file(Path(args.report), path):
                _emit(f"read-back refused: --report {args.report} is the {what} itself "
                      f"({path}) -- give the report its own file name", file=sys.stderr)
                return 2
    try:
        raw = spec_path.read_bytes().decode("utf-8")
        doc = SpecYaml(raw.replace("\r\n", "\n"))
    except FileNotFoundError:
        _emit(f"no such file: {spec_path}", file=sys.stderr)
        return 2
    except (UnicodeDecodeError, YAMLError) as exc:
        _emit(f"invalid YAML in {spec_path}: {exc}", file=sys.stderr)
        return 2
    except SpecYamlError as exc:
        _emit(f"read-back refused: {spec_path} cannot be read the way build reads it: {exc}",
              file=sys.stderr)
        return 2
    spec = doc.spec
    if not isinstance(spec, dict):
        _emit(f"invalid spec {spec_path}: expected a mapping", file=sys.stderr)
        return 2
    try:
        result = read_back(spec, load_workbook(args.workbook), force=args.force)
    except ReadBackRefused as exc:
        _emit(f"read-back refused: {exc}", file=sys.stderr)
        return 2
    report = render_report(result, workbook=Path(args.workbook).name, spec=spec_path.name)
    _emit(report)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        _emit(f"report -> {args.report}")
    problems = result.findings.problems
    if problems:
        _emit(f"blocked: {len(problems)} problem(s) -- nothing written", file=sys.stderr)
        return 1
    if not result.changed:
        _emit("nothing to write: the workbook matches the spec")
        return 0
    changes = len(result.findings.changes)
    if not args.write:
        _emit(f"dry run: {changes} change(s) -- run again with --write to apply them")
        return 0
    # Round-trip YAML: the spec's comments, key order and quoting survive,
    # and so do its line endings.
    try:
        text = doc.dumps(result.spec)
    except SpecYamlError as exc:
        _emit(f"blocked: {exc}", file=sys.stderr)
        return 1
    backup = _backup_path(spec_path)
    shutil.copy2(spec_path, backup)
    spec_path.write_text(text, encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n")
    _emit(f"wrote {changes} change(s) to {spec_path} (backup: {backup.name})")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="est-estimate",
        description="Estimate-spec toolchain: scaffold a spec from intake, "
                    "apply a measured takeoff, build the workbook.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="Render an estimate config to .xlsx.")
    p.add_argument("config", help="estimate config YAML")
    p.add_argument("-o", "--output", help="output .xlsx path")
    p.add_argument("--format", default=None,
                   help="format pack directory (default: the org profile's "
                        "estimating.format, else the bundled pack)")
    p.add_argument("--no-stamp", action="store_true",
                   help="omit the estimate_format workbook property")
    p.add_argument("--no-lint", action="store_true",
                   help="skip consumer-registered pre-render config checks (#256)")
    p.add_argument("--no-brand", action="store_true",
                   help="do not stamp the org profile's brand into the workbook")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("scaffold",
                       help="Bid frame + structure rollups -> *.estimate.yaml skeleton.")
    p.add_argument("--manifest", required=True, help="<project>/manifest.json")
    p.add_argument("--structures", default=None,
                   help="Briefing/structures.yaml (structure -> bid-item rollups)")
    p.add_argument("--items", default="structures",
                   help="'structures' (rollup-referenced + mob, default), 'all', "
                        "or a CSV of item_numbers")
    p.add_argument("--scaffolds", default=None,
                   help="scaffolds.json — BM bid-item scaffold entries fetched "
                        "by the agent (see build-estimate-workbook)")
    p.add_argument("--merge", action="store_true",
                   help="update scaffold-owned fields on an existing output "
                        "in place (without this, an existing file is refused)")
    p.add_argument("-o", "--output", required=True, help="output *.estimate.yaml")
    p.add_argument("--format", default=None,
                   help="format pack directory (default: the org profile's "
                        "estimating.format; this verb writes, so it refuses "
                        "the bundled pack unless you name it here)")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("apply-takeoff",
                       help="Apply a CanonicalTakeoff's measured quantities + "
                            "geometry to a spec (in place).")
    p.add_argument("spec", help="*.estimate.yaml to update")
    p.add_argument("--takeoff", required=True, help="CanonicalTakeoff JSON")
    p.add_argument("--force", action="store_true",
                   help="overwrite hand-edited qty/takeoff fields")
    p.add_argument("--report", default=None, help="write the markdown report here")
    p.add_argument("--format", default=None,
                   help="format pack directory (default: the org profile's "
                        "estimating.format; this verb writes, so it refuses "
                        "the bundled pack unless you name it here)")
    p.set_defaults(func=cmd_apply_takeoff)

    p = sub.add_parser("cip-buildup",
                       help="Render a CIP concrete-structure JSON config to a "
                            "buildup .xlsx (or --init a sample config).")
    p.add_argument("config", nargs="?",
                   help="JSON config describing structures (see --init)")
    p.add_argument("--init", metavar="PATH",
                   help="write a sample JSON config to PATH and exit")
    p.add_argument("-o", "--output",
                   help='output .xlsx path (overrides config "output")')
    p.set_defaults(func=cmd_cip)

    p = sub.add_parser("summarize",
                       help="Price a *.estimate.yaml in pure Python and print "
                            "per-item totals + the bid (internal-arithmetic "
                            "check only — not a rate check).")
    p.add_argument("spec", help="*.estimate.yaml to price")
    p.add_argument("--format", default=None,
                   help="format pack directory (default: the org profile's "
                        "estimating.format, else the bundled pack)")
    p.set_defaults(func=cmd_summarize)

    p = sub.add_parser("scaffold-save",
                       help="Priced spec items -> BidItemScaffold payload JSON")
    p.add_argument("--spec", required=True, help="priced *.estimate.yaml")
    p.add_argument("--agency", default="", help="lowercase agency slug")
    p.add_argument("--project-ref", dest="project_ref", default="",
                   help="provenance; defaults to the spec's project name")
    p.add_argument("--code-map", dest="code_map", default="",
                   help='JSON {"<schedule>::<item#>" | "<item#>": bid_item_code}')
    p.add_argument("-o", "--output")
    p.add_argument("--format", default=None,
                   help="format pack directory (default: the org profile's "
                        "estimating.format; this verb writes, so it refuses "
                        "the bundled pack unless you name it here)")
    p.set_defaults(func=cmd_scaffold_save)

    p = sub.add_parser("read-back",
                       help="Read an edited fieldbook workbook back into its spec "
                            "(a dry run unless --write).")
    p.add_argument("spec", help="the *.estimate.yaml the workbook was built from")
    p.add_argument("workbook", help="the edited .xlsx")
    p.add_argument("--write", action="store_true",
                   help="write the updated spec (after saving SPEC.bak-YYYYmmdd-HHMMSS)")
    p.add_argument("--report", default=None, help="also write the Markdown report here")
    p.add_argument("--force", action="store_true",
                   help="apply a workbook built from an older version of the spec (its "
                        "estimate_spec_sha stamp differs) over the current spec -- a notice, "
                        "not a problem; it undoes every spec edit made since it was built")
    p.set_defaults(func=cmd_read_back)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Back-compat: `est-estimate <config.yaml> [-o out.xlsx]` == build.
    if argv and argv[0] not in _SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["build"] + argv
    args = _parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
