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
  read-back      an edited fieldbook (or derived_from: fieldbook) workbook
                 -> the updated spec and a Markdown report; a dry run
                 unless --write, which first saves a timestamped backup
                 of the spec (readback/)
  assemblies     a *.estimate.yaml -> per-item bulk_create_assemblies payload
                 JSON + a report; --existing adds the re-push plan, --compare
                 checks the payloads against an earlier push's files
                 (assemblies_gen.py; sends nothing)
  heavybook      build: alias of build --pack heavybook (pages merge);
                 read: an edited HeavyBook .xlsx -> a change-set JSON
                 (sends nothing)
  packs, login, fetch, read, apply, build --pack
                 the generic exchange verbs (exchange/cli.py): list the
                 packs, store a BidSheet.ai token, fetch a payload, build a
                 book with a named pack, read any pack's book into a change
                 set, dry-run or --commit it and patch the book

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

from estimating_tools.estimate_spec.format_pack import profile_for_pack as _profile_for_pack

_SUBCOMMANDS = ("build", "scaffold", "apply-takeoff", "scaffold-save",
                "cip-buildup", "summarize", "read-back", "packages", "heavybook", "heavycivil",
                "assemblies", "packs", "login", "fetch", "read", "apply",
                "refresh")


def cmd_build(args) -> int:
    """Render the workbook.

    Every predictable input defect gets a sentence and an exit code, the way
    cmd_cip and cmd_summarize do: a missing file, unparseable YAML, or a spec
    the pack refuses is a user error, not a traceback.

    With --pack the input is a read-model JSON and the named exchange pack
    builds it (est-estimate build --pack heavybook e1.workbook.json).
    """
    if getattr(args, "pack", None):
        from estimating_tools.exchange.cli import cmd_build_pack
        return cmd_build_pack(args)
    if len(args.config) != 1:
        print("build takes one spec YAML (several files are pages: use --pack)", file=sys.stderr)
        return 1
    args.config = args.config[0]
    if args.style or args.host or args.exported_at:
        print("--style/--host/--exported-at apply only with --pack; ignored", file=sys.stderr)
    from estimating_tools.addin.brand import workbook_brand
    from estimating_tools.estimate_spec.build import build
    from estimating_tools.estimate_spec.layout_map import LayoutMapError
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
    except LayoutMapError as exc:
        # The pack's layout_map does not fit what the pack lays out: a pack
        # defect, whatever the spec says.
        print(f"format pack error: {exc}", file=sys.stderr)
        return 2
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
    # The build already stored cached values with the built-in evaluator
    # (xlcalc, #445). The engine pass (#370) is opt-in: ``--recalc excel``
    # (or auto/libreoffice) also has Excel recalculate, one line; no engine
    # is a note, not a failure (the book is as written). Off: no line.
    engine = getattr(args, "recalc", None) or "off"
    if engine != "off":
        from estimating_tools import xlsx_recalc
        print(xlsx_recalc.recalculate(out, engine=engine).message())
    return 0


def add_recalc_option(parser, *, auto: str) -> None:
    """``--recalc`` for a build verb (#370)."""
    parser.add_argument(
        "--recalc", choices=("auto", "excel", "libreoffice", "off"), default="off",
        help="after the build, also have a calculating engine recalculate the book "
             "(default off: the built-in evaluator already stores cached values, so "
             "Protected View, previews and data_only readers show numbers; excel: Excel "
             "recalculates too, for functions the built-in evaluator does not cover; "
             f"auto: {auto}; libreoffice: unverified, only when named). An engine pass "
             "makes the build not byte-reproducible. ESTIMATING_RECALC=off switches it "
             "off everywhere.")


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


def cmd_heavybook_build(args) -> int:
    """`est-estimate heavybook build PAGE.json [...]`: the HeavyBook pack's
    build with its style options -- the same path as
    `est-estimate build --pack heavybook`, kept as the named alias."""
    from estimating_tools.exchange.cli import cmd_build_pack

    args.pack = "heavybook"
    args.config = list(args.workbook_json)
    args.format = None
    return cmd_build_pack(args)


def cmd_heavybook_read(args) -> int:
    """Alias of ``est-estimate read``: the book's pack is detected and its
    read goes through the generic reader. Sends nothing.

    Exit 0: the change set is written (``ops`` empty when nothing changed --
    "no changes"). Exit 2: the read was refused -- every problem is printed
    and nothing is written (an earlier change set at the output path is left
    as it was; the file is written whole or not at all)."""
    from estimating_tools.exchange.cli import cmd_read

    return cmd_read(args)


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
    """Exit 0: applied (or nothing to do). Exit 1: a file cannot be read,
    or the result does not validate; nothing is written.

    Exit 2 has two meanings, told apart by the output:
    - the format pack was refused: NOTHING is written;
    - rows were refused (a generic takeoff name, a unit that does not add
      up, lines that predate takeoff ownership): a `REFUSED: N row(s) not
      applied` line is printed, the refused items are left as they were,
      and the OTHER rows were applied and written."""
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

    # a takeoff's identity is its source_id, else its file's stem (never the
    # directory): name per-structure takeoff files distinctly (#376)
    result = apply_takeoff(spec, takeoff, pack=pack, force=args.force,
                           replace=args.replace,
                           adopt_legacy=args.adopt_legacy,
                           source_name=Path(args.takeoff).stem,
                           source_id=args.source_id)
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
          + (f", {len(result.refused)} refused" if result.refused else "")
          + ("" if changed else " (spec unchanged on disk)"))
    if result.skipped and not args.force:
        for s in result.skipped:
            print(f"  skipped: {s['item_no']} — {s['reason']}")
    for m in result.merged:
        print(f"  item {m['item_no']}: {len(m['takeoffs'])} takeoffs "
              f"contributed ({', '.join(m['takeoffs'])})")
    for w in result.warnings:
        print(f"  warning: {w}")
    for r in result.refused:
        print(f"  refused: item {r['item_no']} — {r['reason']}")
    if result.refused:
        print(f"REFUSED: {len(result.refused)} row(s) not applied — those items "
              "are unchanged; see the refused lines above (exit 2)")
        return 2
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
    --force. Exit 2: refused -- a file cannot be read, the format pack cannot
    be resolved, or the workbook is not one that pack (fieldbook, or a pack
    derived from it) built from this spec.

    The pack is resolved the way build resolves it: --format, then the org
    profile's estimating.format, then the bundled pack.
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
    pack = _resolve_pack_or_report(args)
    if pack is None:
        return 2
    quotes_dir = (spec_path.parent / (spec.get("work_packages_quotes_dir") or "quotes")
                  if spec.get("work_packages") else None)
    try:
        result = read_back(spec, load_workbook(args.workbook), pack=pack, force=args.force,
                           quotes_dir=quotes_dir)
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
    if not result.changed and not result.quote_writes:
        _emit("nothing to write: the workbook matches the spec")
        return 0
    # Edits to existing quote files are not spec changes (the spec stays as it
    # is); new quotes already appear among the changes.
    changes = len(result.findings.changes) + len(result.findings.quote_edits)
    if not args.write:
        _emit(f"dry run: {changes} change(s) -- run again with --write to apply them")
        return 0
    # Round-trip YAML: the spec's comments, key order and quoting survive,
    # and so do its line endings. A read-back that only edits quote files
    # leaves the spec alone.
    if result.changed:
        try:
            text = doc.dumps(result.spec)
        except SpecYamlError as exc:
            _emit(f"blocked: {exc}", file=sys.stderr)
            return 1
        backup = _backup_path(spec_path)
        shutil.copy2(spec_path, backup)
        spec_path.write_text(text, encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n")
        _emit(f"wrote {changes} change(s) to {spec_path} (backup: {backup.name})")
    if result.quote_writes:
        from estimating_tools.quotes import files as quote_files
        for w in result.quote_writes:
            path = quotes_dir / w.file_name
            qbackup = None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    # An existing quote file is the vendor's record: kept as
                    # <name>.bak-<timestamp> (never *.json, so never loaded).
                    qbackup = _backup_path(path)
                    shutil.copy2(path, qbackup)
                quote_files.write_quote_file(path, w.quote)
            except OSError as exc:
                _emit(f"could not write {path}: {exc} "
                      f"({'spec written; ' if result.changed else ''}quote file failed)",
                      file=sys.stderr)
                return 1
            _emit((f"quote updated -> {path}" if w.reason.startswith("edited")
                   else f"quote -> {path}")
                  + (f" (backup: {qbackup.name})" if qbackup else ""))
    return 0


def cmd_packages(args) -> int:
    """`packages init | sync | coverage | push | pull`: work packages in the spec.

    Exit 0 ok, 1 a ValueError (nothing written), 2 a file cannot be read.
    """
    try:
        from ruamel.yaml import YAMLError

        from estimating_tools.estimate_spec.readback.spec_io import SpecYaml, SpecYamlError
    except ImportError:
        _emit("packages needs ruamel.yaml: pip install 'estimating_tools[estimate_spec]'",
              file=sys.stderr)
        return 2
    from estimating_tools.estimate_spec import packages as pk
    from estimating_tools.estimate_spec.validate import validate_cross_references

    spec_path = Path(args.spec)
    try:
        raw = spec_path.read_bytes().decode("utf-8")
        doc = SpecYaml(raw.replace("\r\n", "\n"))
    except FileNotFoundError:
        _emit(f"no such file: {spec_path}", file=sys.stderr)
        return 2
    except (UnicodeDecodeError, YAMLError, SpecYamlError) as exc:
        _emit(f"invalid YAML in {spec_path}: {exc}", file=sys.stderr)
        return 2
    spec = doc.spec
    if not isinstance(spec, dict):
        _emit(f"invalid spec {spec_path}: expected a mapping", file=sys.stderr)
        return 2

    if args.packages_command == "push" and args.apply:
        return _packages_apply(args, spec_path, spec)
    if args.packages_command in ("push", "pull"):
        return _packages_plan(args, spec_path, spec)

    if args.packages_command == "coverage":
        from estimating_tools.quotes.files import QuoteFileError, load_quotes
        qdir = spec_path.parent / (spec.get("work_packages_quotes_dir") or "quotes")
        try:
            lines = pk.package_coverage(spec, load_quotes(qdir))
        except QuoteFileError as exc:
            _emit(f"quote file problem: {exc}", file=sys.stderr)
            return 2
        for line in lines:
            _emit(line)
        _emit(f"{len(lines)} coverage gap(s)")
        return 0

    try:
        if args.packages_command == "init":
            try:
                src = yaml.safe_load(Path(args.source).read_text(encoding="utf-8"))
            except FileNotFoundError:
                _emit(f"no such file: {args.source}", file=sys.stderr)
                return 2
            except (UnicodeDecodeError, yaml.YAMLError) as exc:
                _emit(f"invalid YAML in {args.source}: {exc}", file=sys.stderr)
                return 2
            if not isinstance(src, dict):
                _emit(f"invalid {args.source}: expected a mapping", file=sys.stderr)
                return 2
            report = pk.init_packages(spec, src)
            changes = len(report)
        else:
            result = pk.sync_package_lines(spec)
            report, changes = result.lines(), result.changes
        validate_cross_references(spec)
    except ValueError as exc:
        _emit(f"packages {args.packages_command}: {exc}", file=sys.stderr)
        return 1
    for line in report:
        _emit(line)
    if not changes:
        _emit("nothing to write")
        return 0
    if not args.write:
        _emit(f"dry run: {changes} change(s) -- run again with --write to apply them")
        return 0
    try:
        text = doc.dumps(spec)
    except SpecYamlError as exc:
        _emit(f"blocked: {exc}", file=sys.stderr)
        return 1
    backup = _backup_path(spec_path)
    shutil.copy2(spec_path, backup)
    spec_path.write_text(text, encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n")
    _emit(f"wrote {changes} change(s) to {spec_path} (backup: {backup.name})")
    return 0


def _bm_dir(spec_path: Path, spec: dict) -> tuple[Path, Path]:
    """The quotes dir and its `_bm/` dir (sidecar and plan JSON; kept out of the
    quotes dir itself, whose `*.json` are all read as quote files)."""
    qdir = spec_path.parent / (spec.get("work_packages_quotes_dir") or "quotes")
    return qdir, qdir / "_bm"


def _packages_plan(args, spec_path: Path, spec: dict) -> int:
    """`packages push SPEC --bm EXPORT` / `packages pull SPEC --bm EXPORT [--write]`:
    print the plan and write its JSON. Exit 0 ok (push `--strict`: 1 when the plan
    has a conflict or refusal), 1 a ValueError, 2 unreadable input or a stale export."""
    from estimating_tools.estimate_spec.bm_sync.export import BmExport, ExportError
    from estimating_tools.estimate_spec.bm_sync.ops import render_plan
    from estimating_tools.estimate_spec.bm_sync.sidecar import Sidecar, file_sha
    from estimating_tools.quotes.files import QuoteFileError, load_quote_file

    cmd = args.packages_command
    if not args.bm:
        _emit(f"packages {cmd}: --bm EXPORT.json is required", file=sys.stderr)
        return 2
    qdir, bm_dir = _bm_dir(spec_path, spec)
    try:
        export = BmExport.from_dict(json.loads(Path(args.bm).read_text(encoding="utf-8")))
    except FileNotFoundError:
        _emit(f"no such file: {args.bm}", file=sys.stderr)
        return 2
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _emit(f"invalid JSON in {args.bm}: {exc}", file=sys.stderr)
        return 2
    except (ExportError, AttributeError, KeyError, TypeError) as exc:
        _emit(f"unusable export {args.bm}: {exc}", file=sys.stderr)
        return 2
    quotes = []
    for path in sorted(qdir.glob("*.json")) if qdir.is_dir() else []:
        if path.name.endswith(".example.json"):
            continue
        try:
            quotes.append((path.name, load_quote_file(path), file_sha(path)))
        except QuoteFileError as exc:
            _emit(f"quote file problem in {path.name}: {exc}", file=sys.stderr)
            return 2
    sidecar_path = bm_dir / "bm-sync.json"
    try:
        sidecar = Sidecar.load(sidecar_path)
    except (ValueError, TypeError) as exc:
        _emit(f"unreadable sidecar {sidecar_path}: {exc}", file=sys.stderr)
        return 2
    now = datetime.now().isoformat(timespec="seconds")
    try:
        if cmd == "push":
            from estimating_tools.estimate_spec.bm_sync.plan_push import plan_push
            plan = plan_push(spec, quotes, export, sidecar, spec_name=spec_path.name,
                             force=args.force, now=now)
        else:
            from estimating_tools.estimate_spec.bm_sync.plan_pull import plan_pull
            plan = plan_pull(spec, quotes, export, sidecar, spec_name=spec_path.name,
                             force=args.force, now=now)
    except ValueError as exc:
        _emit(f"packages {cmd}: {exc}", file=sys.stderr)
        return 1
    _emit(render_plan(plan).rstrip("\n"))
    out = Path(args.output) if args.output else bm_dir / f"{cmd}.plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(plan.to_json() + "\n", encoding="utf-8")
    _emit(f"plan: {out}")
    if cmd == "push":
        blocked = [e for e in plan.entries if e.kind in ("conflict", "refused")]
        return 1 if blocked and args.strict else 0
    if not (plan.ops or plan.spec_changes or plan.sidecar_updates):
        _emit("nothing to write")
        return 0
    if not args.write:
        _emit(f"dry run: {len(plan.ops)} op(s) -- run again with --write to apply them")
        return 0
    from estimating_tools.estimate_spec.bm_sync.plan_pull import write_pull
    bm_dir.mkdir(parents=True, exist_ok=True)
    if plan.spec_changes:
        backup = _backup_path(spec_path)
        shutil.copy2(spec_path, backup)
        _emit(f"spec backup: {backup.name}")
    for path in write_pull(plan, spec_path, qdir, sidecar_path):
        _emit(f"wrote {path}")
    return 0


def _packages_apply(args, spec_path: Path, spec: dict) -> int:
    """`packages push --apply RESULTS --plan PLAN SPEC`: the skill's MCP results onto
    the sidecar. Exit 0 ok, 1 any op errored, 2 unreadable input."""
    from estimating_tools.estimate_spec.bm_sync.apply import apply_results
    from estimating_tools.estimate_spec.bm_sync.ops import Plan
    from estimating_tools.estimate_spec.bm_sync.sidecar import Sidecar

    _qdir, bm_dir = _bm_dir(spec_path, spec)
    plan_path = Path(args.plan) if args.plan else bm_dir / "push.plan.json"
    sidecar_path = bm_dir / "bm-sync.json"
    try:
        plan = Plan.from_json(plan_path.read_text(encoding="utf-8"))
        results = json.loads(Path(args.apply).read_text(encoding="utf-8"))
        sidecar = Sidecar.load(sidecar_path)
    except FileNotFoundError as exc:
        _emit(f"no such file: {exc.filename}", file=sys.stderr)
        return 2
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        _emit(f"unreadable plan, results or sidecar: {exc}", file=sys.stderr)
        return 2
    if plan.direction != "push":
        _emit(f"{plan_path} is a {plan.direction} plan; --apply takes a push plan", file=sys.stderr)
        return 2
    if plan.spec != spec_path.name:
        _emit(f"plan is for {plan.spec}, not {spec_path.name}", file=sys.stderr)
        return 2
    if not isinstance(results, dict):
        _emit(f"invalid {args.apply}: expected a mapping with 'results'", file=sys.stderr)
        return 2
    report = apply_results(plan, results, sidecar, now=datetime.now().isoformat(timespec="seconds"))
    _emit(f"applied {len(report.applied)}")
    for op_id, reason in report.skipped:
        _emit(f"skipped {op_id}: {reason}")
    for op_id, text in report.errors:
        _emit(f"error {op_id}: {text}")
    for text in report.warnings:
        _emit(f"warning {text}")
    for text in report.pruned:
        _emit(f"pruned stale plug record {text}")
    bm_dir.mkdir(parents=True, exist_ok=True)
    sidecar.save(sidecar_path)
    _emit(f"wrote {sidecar_path}")
    return 1 if report.errors else 0


def cmd_assemblies(args) -> int:
    """`assemblies SPEC -o DIR --bid BID [--existing IDS] [--compare DIR2]`.

    Exit 0 ok, 1 the spec cannot be generated (or --compare finds differences),
    2 an input cannot be read."""
    from estimating_tools.estimate_spec.assemblies_gen import (
        compare_payloads, generate_assemblies, repush_plan)
    from estimating_tools.estimate_spec.bm_sync.sidecar import Sidecar

    spec_path = Path(args.spec)
    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        _emit(f"cannot read {spec_path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(spec, dict):
        _emit(f"invalid spec {spec_path}: expected a mapping", file=sys.stderr)
        return 2
    existing = sidecar = None
    if args.existing:
        try:
            existing = json.loads(Path(args.existing).read_text(encoding="utf-8"))
            sidecar_path = _bm_dir(spec_path, spec)[1] / "bm-sync.json"
            sidecar = Sidecar.load(sidecar_path) if sidecar_path.exists() else None
        except (OSError, ValueError, TypeError) as exc:
            _emit(f"cannot read the existing ids or the sidecar: {exc}", file=sys.stderr)
            return 2
        if not isinstance(existing, dict):
            _emit(f"invalid {args.existing}: expected a mapping", file=sys.stderr)
            return 2
    pack = _resolve_pack_or_report(args)
    if pack is None:
        return 2
    try:
        result = generate_assemblies(spec, bid=args.bid, pack=pack)
    except (ValueError, KeyError, TypeError) as exc:     # GenError, FormulaError, a bad spec
        _emit(f"assemblies: {exc}", file=sys.stderr)
        return 1
    report = result.report
    if existing is not None:
        report = report.rstrip("\n") + "\n\n" + repush_plan(result, existing, sidecar)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    for item_no, payloads in result.payloads.items():
        (out / f"{item_no}.json").write_text(json.dumps(payloads, indent=2) + "\n", encoding="utf-8")
    (out / "assemblies-report.md").write_text(report.rstrip("\n") + "\n", encoding="utf-8")
    _emit(report)
    if not args.compare:
        return 0
    try:
        cmp = compare_payloads(result, Path(args.compare))
    except (OSError, ValueError) as exc:
        _emit(f"cannot read the existing payloads: {exc}", file=sys.stderr)
        return 2
    _emit(cmp.render())
    return 0 if cmp.ok else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="est-estimate",
        description="Estimate-spec toolchain: scaffold a spec from intake, "
                    "apply a measured takeoff, build the workbook.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="Render an estimate config to .xlsx.")
    p.add_argument("config", nargs="+",
                   help="estimate config YAML (with --pack: one or more read-model JSON "
                        "files, the pages of one estimate)")
    p.add_argument("-o", "--output", help="output .xlsx path")
    p.add_argument("--pack", default=None,
                   help="build from a read-model JSON with this exchange pack instead of a "
                        "spec YAML")
    p.add_argument("--exported-at", default=None, help=argparse.SUPPRESS)
    p.add_argument("--host", default=None, help=argparse.SUPPRESS)
    p.add_argument("--style", default=None, help=argparse.SUPPRESS)
    p.add_argument("--format", default=None,
                   help="format pack directory (default: the org profile's "
                        "estimating.format, else the bundled pack)")
    p.add_argument("--no-stamp", action="store_true",
                   help="omit the estimate_format workbook property")
    p.add_argument("--no-lint", action="store_true",
                   help="skip consumer-registered pre-render config checks (#256)")
    p.add_argument("--no-brand", action="store_true",
                   help="do not stamp the org profile's brand into the workbook")
    add_recalc_option(p, auto="Excel when present")
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
                            "geometry to a spec (in place). Exit 2 when any "
                            "row is refused (the other rows still apply).")
    p.add_argument("spec", help="*.estimate.yaml to update")
    p.add_argument("--takeoff", required=True, help="CanonicalTakeoff JSON")
    p.add_argument("--force", action="store_true",
                   help="overwrite hand-edited qty/takeoff fields")
    p.add_argument("--source-id", default=None,
                   help="this takeoff's identity (e.g. the structure it "
                        "measured); overrides the takeoff's own source_id and "
                        "its file name. Re-applying with the same id replaces "
                        "that takeoff's lines; a different id adds")
    p.add_argument("--adopt-legacy", action="store_true",
                   help="on items whose lines predate takeoff ownership (no "
                        "owner recorded), this takeoff takes them over: its "
                        "lines and qty replace theirs, no sum. Items that "
                        "already record owners merge as usual")
    p.add_argument("--replace", action="store_true",
                   help="this takeoff's rows replace everything on EVERY item "
                        "they match, dropping the lines and quantity other "
                        "takeoffs contributed there (by default takeoffs "
                        "applied in sequence merge into shared items: lines "
                        "kept, quantities summed)")
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

    p = sub.add_parser("heavybook", aliases=["heavycivil"],
                       help="HeavyBook workbook: render BidSheet.ai's estimate "
                            "workbook payload (get_estimate_workbook JSON), or read an "
                            "edited workbook back into a change set.")
    hsub = p.add_subparsers(dest="heavybook_command", required=True, metavar="{build,read}")
    q = hsub.add_parser("build", help="Render a get_estimate_workbook JSON to .xlsx.")
    q.add_argument("workbook_json", nargs="+",
                   help="one or more saved get_estimate_workbook responses "
                        "(pages of one estimate)")
    q.add_argument("-o", "--output", help="output .xlsx (default: next to the JSON)")
    q.add_argument("--style", default=None,
                   help="style pack directory (tokens.yaml and/or sheets.yaml; default: the "
                        "org profile's estimating.heavycivil_style, else the bundled style)")
    q.add_argument("--exported-at", default=None,
                   help="export timestamp to stamp (default: now, UTC)")
    q.add_argument("--host", default="www.bidsheet.ai",
                   help="BidSheet.ai host the payload came from (stamped for read-back)")
    add_recalc_option(q, auto="Excel when present")
    q.set_defaults(func=cmd_heavybook_build)
    q = hsub.add_parser("read", help="Read an edited HeavyBook .xlsx back into a change set "
                                     "(JSON ops for apply_estimate_workbook_changes).")
    q.add_argument("book", help="the edited HeavyBook workbook")
    q.add_argument("-o", "--output",
                   help="change-set JSON (default: BOOK.changes.json next to the workbook)")
    q.set_defaults(func=cmd_heavybook_read)

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
    p.add_argument("--format", default=None,
                   help="the format pack that built the workbook (default: the org "
                        "profile's estimating.format, else the bundled pack) -- "
                        "fieldbook, or a pack whose format.yaml declares "
                        "derived_from: fieldbook or extends: fieldbook")
    p.add_argument("--force", action="store_true",
                   help="apply a workbook built from an older version of the spec (its "
                        "estimate_spec_sha stamp differs) over the current spec -- a notice, "
                        "not a problem; it undoes every spec edit made since it was built")
    p.set_defaults(func=cmd_read_back)

    p = sub.add_parser("packages",
                       help="Work packages in the spec: init from work-packages.yaml, "
                            "sync the lines they price, report quote coverage.")
    psub = p.add_subparsers(dest="packages_command", required=True)
    q = psub.add_parser("init", help="Copy a work-packages.yaml into the spec.")
    q.add_argument("spec", help="*.estimate.yaml")
    q.add_argument("--from", dest="source", required=True, help="work-packages.yaml")
    q = psub.add_parser("sync", help="Tag (or add) the lines each package prices.")
    q.add_argument("spec", help="*.estimate.yaml")
    for q in tuple(psub.choices.values()):
        q.add_argument("--write", action="store_true",
                       help="write the spec (after saving SPEC.bak-YYYYmmdd-HHMMSS)")
    q = psub.add_parser("coverage", help="Report what the quotes leave unpriced.")
    q.add_argument("spec", help="*.estimate.yaml")
    q = psub.add_parser("push", help="Plan the BidSheet.ai ops for the packages, quote files "
                                     "and choices; --apply records the results in the sidecar.")
    q.add_argument("spec", help="*.estimate.yaml")
    q.add_argument("--bm", help="the BidSheet.ai export JSON (required unless --apply)")
    q.add_argument("-o", "--output", help="plan JSON (default <quotes dir>/_bm/push.plan.json)")
    q.add_argument("--force", choices=["spec"], help="push the spec's side of a conflict")
    q.add_argument("--strict", action="store_true",
                   help="exit 1 when the plan has a conflict or refusal")
    q.add_argument("--apply", metavar="RESULTS.json",
                   help="record the skill's MCP results for a push plan in the sidecar")
    q.add_argument("--plan", help="the push plan --apply records (default "
                                  "<quotes dir>/_bm/push.plan.json)")
    q = psub.add_parser("pull", help="Plan BidSheet.ai's quotes and pinned choices into quote "
                                     "files and the spec; --write writes them.")
    q.add_argument("spec", help="*.estimate.yaml")
    q.add_argument("--bm", required=True, help="the BidSheet.ai export JSON")
    q.add_argument("-o", "--output", help="plan JSON (default <quotes dir>/_bm/pull.plan.json)")
    q.add_argument("--force", choices=["bm"], help="pull BidSheet.ai's side of a conflict")
    q.add_argument("--write", action="store_true",
                   help="write the quote files (after a .bak copy), the spec and the sidecar")
    p.set_defaults(func=cmd_packages)

    p = sub.add_parser("assemblies",
                       help="Per-item bulk_create_assemblies payloads and a report "
                            "(re-push plan with --existing, regression check with --compare).")
    p.add_argument("spec", help="*.estimate.yaml")
    p.add_argument("-o", "--output", required=True, help="directory for <item_no>.json and the report")
    p.add_argument("--bid", required=True, help="bid tag in each external_id")
    p.add_argument("--existing", metavar="IDS.json",
                   help="the bid's bm-assembly-ids.json: adds the re-push plan to the report")
    p.add_argument("--compare", metavar="DIR",
                   help="an earlier push's payload dir: print the differences, exit 1 on any")
    p.add_argument("--format", default=None,
                   help="format pack directory (default: the org profile's "
                        "estimating.format, else the bundled pack)")
    p.set_defaults(func=cmd_assemblies)

    from estimating_tools.exchange.cli import add_subparsers as _exchange_subparsers
    _exchange_subparsers(sub)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Back-compat: `est-estimate <config.yaml> [-o out.xlsx]` == build.
    if argv and argv[0] not in _SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["build"] + argv
    if argv and argv[0] == "heavycivil":
        print("`heavycivil` is now `heavybook`; the old name goes away next release",
              file=sys.stderr)
    args = _parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
