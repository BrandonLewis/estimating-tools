"""The generic verbs of `est-estimate` (engine spec "Surfaces"): packs, login,
fetch, build --pack, read, apply, refresh. They find the pack through the registry and
move payloads and change sets through files, never through the agent
(contract rule 14). Every committed apply carries a request_id; an apply
whose outcome is unknown is replayed with the same id (rule 12).

Exit codes:

- 0: done (a dry-run plan, "no changes", a clean patch).
- 1: a bad input -- a file, a payload, a style or profile, a malformed
  ``--host``, an empty or cancelled token, bad ``fetch`` ids, a page set that
  does not merge (the estimate changed between fetches), or a payload or
  workbook that cannot be written.
- 2: refused here, nothing sent -- no pack for the book (or a newer or damaged
  stamp), a read refused, a pack that cannot do this yet, an unknown
  ``--pack``, ``-o`` naming the book, a book that cannot be opened for writing
  before a commit, ``--request-id`` without ``--commit``, a book whose host
  stamp is damaged or disagrees with ``--host``, a request the client refused
  before sending it (no token stored, an unreadable token file, a host other
  than the stored token's), or a change set that cannot be written (kept from
  ``heavybook read``).
- 3: BidSheet.ai refused or did not answer (no answer or a 5xx to a commit that
  was sent is an unknown outcome: replay with ``--request-id``), or the apply went
  through but the book could not be patched (every such message ends with the
  advice not to apply again and the commands that rebuild the book). A page
  (the stamp says so; its ids are the stamp's or, when they did not fit the
  stamp cell, its baseline's) is fetched and rebuilt with its ``--items``; a
  whole book without. For ``refresh``: the fetch failed.
- 4: ``refresh`` found rows changed in BidSheet.ai and in the book, or changes
  the book cannot take in place: each is printed, nothing was written, and
  the book keeps its baseline (the estimator decides; the engine never
  resolves a collision).

A refresh that wrote the book gets the same opt-in calculating pass as
``apply --commit`` (``--recalc excel``; one line, never a failure). By
default there is none: the patch already stored cached values with the
built-in evaluator (#445).

``refresh`` is 0 when it wrote BidSheet.ai's changes (or the book was
already current, or ``--dry-run`` printed what it would write), 1 for a
malformed ``--host``, and 2 when refused here with nothing written: no pack
for the book, a read refused (a stale book among them), a pack that cannot
refresh, a locked book, a host that disagrees with the stamp, a request the
client refused before sending, or the refresh's own refusal (a copy that
would not read back as the book does; the book changed while refreshing)."""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
import uuid
from pathlib import Path

from estimating_tools.exchange import client, registry
from estimating_tools.exchange.facts import read_facts
from estimating_tools.exchange.types import NotYet

#: The custom document property a pack stamps with the BidSheet.ai host the
#: book was built from (HeavyBook writes a bare host such as ``www.bidsheet.ai``).
HOST_STAMP = "bidsheet_host"


def emit(text: str, *, file=None) -> None:
    """Print `text`, even to a console whose code page cannot show it (a
    Windows console piped through cp1252): arrows come out as escapes."""
    try:
        print(text, file=file)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"), file=file)


def _err(text: str) -> None:
    emit(text, file=sys.stderr)


def same_file(a: Path, b: Path) -> bool:
    """Do `a` and `b` name one file (case folding, relative paths, symlinks)?"""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def write_json(path: Path, doc) -> None:
    """Write `doc` whole or not at all (a temp file, then a rename). Raises
    OSError; the temp file is removed first."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def change_set_path(book: Path, output) -> Path | None:
    """`-o`, else BOOK.changes.json next to the workbook; None (after saying
    why) when `-o` names the workbook itself."""
    out = Path(output) if output else book.with_name(book.stem + ".changes.json")
    if same_file(out, book):
        _err(f"read refused: -o {out} is the workbook itself -- give the change set its "
             "own file name")
        return None
    return out


def write_change_set(out: Path, change_set) -> int:
    """The read verbs' shared tail: write the change set JSON whole or not at
    all, then print its summary. Returns the exit code."""
    try:
        write_json(out, change_set.as_json())
    except OSError as exc:
        _err(f"could not write the change set: {exc}")
        return 2
    emit(change_set.text())
    emit(f"WROTE: {out}")
    return 0


def _not_yet(pack, exc) -> int:
    """A pack's NotYet, without doubling its name ("fieldbook: fieldbook ...")."""
    text = str(exc)
    _err(text if text.startswith(pack.name) else f"{pack.name}: {text}")
    return 2


def _refused(what: str, problems, tail: str) -> int:
    _err(f"{what} refused -- {len(problems)} problem(s), {tail}:")
    for p in problems:
        _err(f"  {p}")
    return 2


# -- packs, login, fetch ---------------------------------------------------------------------

def cmd_packs(args) -> int:
    found = registry.discover()
    for p in found.packs:
        emit(f"{p.name} {p.version}  (contract {p.contract})")
    if not found.packs:
        emit("no exchange packs installed")
    for problem in found.problems:
        _err(f"problem: {problem}")
    return 0


def cmd_login(args) -> int:
    stdin = sys.stdin
    if stdin is not None and not stdin.isatty():
        token = stdin.readline().strip()
    else:
        try:
            token = getpass.getpass("BidSheet.ai API token: ")
        except (KeyboardInterrupt, EOFError):
            _err("login cancelled -- nothing stored")
            return 1
    try:
        path = client.login(args.host, token)
    except ValueError as exc:
        _err(f"login refused: {exc}")
        return 1
    except OSError as exc:
        _err(f"could not store the token: {exc}")
        return 1
    emit(f"token stored for {args.host} at {path}")
    return 0


def cmd_fetch(args) -> int:
    try:
        estimate_id = int(args.estimate)
        items = [int(x) for x in args.items.split(",") if x.strip()] if args.items else None
    except ValueError:
        _err("fetch refused: the estimate and --items must be whole-number ids")
        return 1
    if items is not None and not items:
        _err("fetch refused: no item ids given")
        return 1
    try:
        doc = client.fetch(estimate_id, item_ids=items, host=args.host)
    except ValueError as exc:
        _err(f"fetch refused: {exc}")
        return 1
    except client.ClientError as exc:
        if not exc.sent:
            _err(f"fetch refused: {exc}")
            return 2
        _err(f"fetch failed: {exc}")
        return 3
    out = Path(args.output or payload_name(estimate_id, items))
    try:
        write_json(out, doc)
    except OSError as exc:
        _err(f"could not write the payload: {exc}")
        return 1
    emit(f"WROTE: {out}")
    return 0


def payload_name(estimate_id: int, items) -> str:
    """`eID.workbook.json`, or `eID.items.workbook.json` for a page, so a page
    is visibly a page."""
    return f"e{estimate_id}.items.workbook.json" if items else f"e{estimate_id}.workbook.json"


# -- build --pack ----------------------------------------------------------------------------

#: The message prefix per ``BuildRefused.kind``; every pack's refusal of a
#: kind reads the same.
REFUSAL_PREFIX = {"payload": "payload refused", "style": "style pack refused",
                  "profile": "org profile refused", "host": "build refused",
                  "template": "template refused"}

_PAGE = re.compile(r"\.p\d+(?=\.json$)")


def _default_book_path(src: Path) -> Path:
    """`e1.workbook.json` or `e1.workbook.p1.json` -> `e1.workbook.xlsx`."""
    name = _PAGE.sub("", src.name)
    stem = name[:-len(".json")] if name.endswith(".json") else Path(name).stem
    return src.with_name(stem + ".xlsx")


def _load_pages(paths: list):
    """The payload the pages make (``merge_pages``), or an exit code after
    saying what was wrong with a file."""
    from estimating_tools.exchange.model import PayloadError, merge_pages

    docs = []
    for src in paths:
        try:
            docs.append(json.loads(src.read_text(encoding="utf-8")))
        except FileNotFoundError:
            _err(f"no such file: {src}")
            return 1
        except json.JSONDecodeError as exc:
            _err(f"invalid JSON in {src}: {exc}")
            return 1
        except (OSError, UnicodeDecodeError) as exc:
            _err(f"could not read {src}: {exc}")
            return 1
    try:
        payload = merge_pages(docs)
    except PayloadError as exc:
        _err(f"payload refused: {exc}")
        return 1
    if not isinstance(payload, dict):
        _err("payload refused: the payload must be a JSON object")
        return 1
    return payload


def cmd_build_pack(args) -> int:
    """`est-estimate build --pack NAME payload.json [page.json ...] -o OUT`: the
    pack builds the book from a read-model payload (pages are merged first).
    A refusal is printed with the prefix its kind gets for every pack."""
    from estimating_tools.exchange.types import BuildRefused

    found = registry.discover()
    pack = next((p for p in found.packs if p.name == args.pack), None)
    if pack is None:
        _err(f"no pack named {args.pack!r}; installed: "
             + (", ".join(p.name for p in found.packs) or "none"))
        for problem in found.problems:
            _err(f"problem: {problem}")
        return 2
    if getattr(args, "format", None):
        _err("--format applies only to a spec build; ignored")
    config = args.config if isinstance(args.config, list) else [args.config]
    paths = [Path(p) for p in config]
    payload = _load_pages(paths)
    if isinstance(payload, int):
        return payload
    out = Path(args.output) if args.output else _default_book_path(paths[0])
    options = {"exported_at": getattr(args, "exported_at", None),
               "host": getattr(args, "host", None), "style": getattr(args, "style", None)}
    try:
        report = pack.build(payload, out, options={k: v for k, v in options.items() if v})
    except NotYet as exc:
        return _not_yet(pack, exc)
    except BuildRefused as exc:
        _err(f"{REFUSAL_PREFIX[exc.kind]}: {exc}")
        return 1
    except OSError as exc:
        _err(f"could not write the workbook: {exc}")
        return 1
    emit(f"WROTE: {report.path}")
    _recalc(report.path, args)
    return 0


def _recalc(book: Path, args) -> None:
    """The opt-in calculating pass (#370): the write already stored cached
    values with the built-in evaluator (#445); ``--recalc excel`` (or
    auto/libreoffice) also has an engine recalculate the book. One line; no
    engine is a note, not a failure (the book is as written). Off, the
    default: nothing runs and nothing is printed."""
    engine = getattr(args, "recalc", None) or "off"
    if engine == "off":
        return
    from estimating_tools import xlsx_recalc
    emit(xlsx_recalc.recalculate(book, engine=engine).message())


# -- read, apply -----------------------------------------------------------------------------

def _detect(book: Path):
    """``(pack, facts)``: the book's facts, read once, and the pack they name."""
    facts = read_facts(book)
    if facts.error:
        raise LookupError(facts.error)
    return registry.pack_for(facts), facts


def _read(verb: str, book: Path, tail: str):
    """Detect the pack and read the book. Returns (pack, change_set, facts) or
    an exit code."""
    tail_note = " (nothing sent)" if verb == "apply" else ""
    try:
        pack, facts = _detect(book)
    except LookupError as exc:
        _err(f"{verb} refused: {exc}{tail_note}")
        return 2
    try:
        result = pack.read(book)
    except NotYet as exc:
        return _not_yet(pack, exc)
    if result.refused:
        return _refused("read", result.problems, tail)
    return pack, result.change_set, facts


def _apply_host(facts, given) -> str | None:
    """The origin an apply goes to. A book stamped with the host it was built
    from (``HOST_STAMP``: a bare host or an https origin) submits there and
    nowhere else -- another deployment may hold an unrelated estimate with
    the same id -- so ``--host`` may only repeat the stamp. An unstamped book
    goes to ``--host``, else to the stored token's host. Raises ValueError
    for a malformed ``--host`` and LookupError for a damaged stamp or a
    ``--host`` that disagrees with it."""
    wanted = client._check_host(given) if given else None
    stamp = str(facts.properties.get(HOST_STAMP) or "").strip()
    if not stamp:
        return wanted
    try:
        expected = client._check_host(stamp if "://" in stamp else f"https://{stamp}")
    except ValueError:
        raise LookupError(f"this book's host stamp {stamp!r} is not an https origin -- "
                          "rebuild the book") from None
    if wanted is not None and wanted != expected:
        raise LookupError(f"this book was built from {expected}; --host says {wanted}")
    return expected


def cmd_read(args) -> int:
    book = Path(args.book)
    out = change_set_path(book, args.output)
    if out is None:
        return 2
    got = _read("read", book, "nothing written")
    if isinstance(got, int):
        return got
    pack, change_set, _facts = got
    emit(f"pack: {pack.name} {pack.version}")
    return write_change_set(out, change_set)


def _plan_text(result, change_set, dry_run: bool) -> str:
    head = f"{'dry run' if dry_run else 'applied'} -- request {result.request_id}"
    lines = [head + (" (replayed)" if result.replayed else ""), change_set.text()]
    lines += [f"  deleted: {d}" for d in result.deleted]
    lines += [f"  warning: {w}" for w in result.warnings]
    if result.totals:
        lines.append("  totals: " + json.dumps(result.totals, default=str))
    return "\n".join(lines)


def _locked(book: Path) -> bool:
    """Can the book not be opened for writing -- held open by Excel (Windows)
    or read-only? Any other open error is left for the patch to report."""
    try:
        with open(book, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _report_apply_failure(exc, change_set, dry_run: bool, request_id) -> None:
    _err(f"apply failed: {exc}")
    body = exc.body if isinstance(getattr(exc, "body", None), dict) else {}
    idx = body.get("op_index")
    if isinstance(idx, int) and not isinstance(idx, bool):
        for where in change_set.rows:
            if where.get("op_index") == idx:
                row = where.get("row")
                place = f"{where.get('sheet')} row {row}" if row is not None else \
                    f"{where.get('sheet')} (a deleted row)"
                _err(f"  op {idx} came from {place}")
    for c in body.get("conflicts") or []:
        _err(f"  conflict: {c}")
    rid = getattr(exc, "request_id", None) or request_id
    # No answer, or a server error, to a request that went out may have come
    # after the apply was done.
    unknown = exc.sent and (exc.status is None or exc.status >= 500)
    if unknown and not dry_run and rid:
        _err(f"  the outcome is unknown. Re-run with --commit --request-id {rid}; a server with "
             "request-id support (#1676) replays it safely. Against an older server, check the "
             "estimate in BidSheet.ai first")


def _do_not_reapply(pack, estimate_id: int, book: Path, items=None, host=None) -> str:
    """The line every failure after a committed apply ends with: runnable
    commands that rebuild the book to a new file next to it, never over the
    edited book. A page (``items``) stays a page: its fetch keeps
    ``--items``; a whole book is fetched whole."""
    payload = book.with_name(payload_name(estimate_id, items))
    rebuilt = book.with_name(book.stem + ".rebuilt.xlsx")
    pages = f" --items {','.join(str(i) for i in items)}" if items else ""
    on = f" --host {host}" if host else ""
    return ("The apply is done -- do not run apply on this book again; rebuild it from "
            f"BidSheet.ai: est-estimate fetch {estimate_id}{pages}{on} -o {payload}, then "
            f"est-estimate build --pack {pack.name} {payload}{on} -o {rebuilt}")


def _covered(pack, book: Path) -> tuple:
    """``(page, item_ids)``: what the book covers, when its pack can say
    (a page's ids may come from its stamp or from its baseline).
    ``(False, None)`` is the whole estimate; a pack that cannot say gets
    the whole estimate too."""
    covered = getattr(pack, "covered", None)
    if covered is None:
        return False, None
    try:
        page, ids = covered(book)
    except Exception:  # noqa: BLE001 -- a pack that cannot say gets the whole estimate
        return False, None
    return (True, list(ids)) if page and ids else (False, None)


def cmd_apply(args) -> int:
    book = Path(args.book)
    if args.request_id and not args.commit:
        _err("apply refused: --request-id replays a commit -- add --commit (nothing sent)")
        return 2
    got = _read("apply", book, "nothing sent")
    if isinstance(got, int):
        return got
    pack, cs, facts = got
    if not cs.ops:
        emit("no changes -- nothing to send")
        return 0
    try:
        host = _apply_host(facts, args.host)
    except ValueError as exc:
        _err(f"apply refused: {exc} (nothing sent)")
        return 1
    except LookupError as exc:
        _err(f"apply refused: {exc} (nothing sent)")
        return 2
    dry_run = not args.commit
    if not dry_run and _locked(book):
        _err(f"apply refused: cannot open {book} for writing (open in Excel, or read-only) -- "
             "close it or make it writable and retry (nothing sent)")
        return 2
    try:
        estimate_id = int(cs.estimate_id)
    except (TypeError, ValueError):
        _err(f"apply refused: the book's estimate id {cs.estimate_id!r} is not a number -- "
             "rebuild it (nothing sent)")
        return 2
    _, items = (False, None) if dry_run else _covered(pack, book)
    # A commit names its request here, so an unknown outcome can be replayed with it.
    request_id = args.request_id or (None if dry_run else str(uuid.uuid4()))
    try:
        outcome = client.apply(estimate_id, cs.ops, dry_run=dry_run,
                               request_id=request_id, host=host)
    except ValueError as exc:
        _err(f"apply refused: {exc} (nothing sent)")
        return 1
    except client.ClientError as exc:
        if not exc.sent:
            _err(f"apply refused: {exc} (nothing sent)")
            return 2
        _report_apply_failure(exc, cs, dry_run, request_id)
        return 3
    emit(_plan_text(outcome, cs, dry_run))
    if dry_run:
        emit("Re-run with --commit to apply.")
        return 0
    advice = _do_not_reapply(pack, estimate_id, book, items, host)
    try:
        # Only the items the book covers: their fetch becomes its baseline.
        fresh = client.fetch(estimate_id, item_ids=items, host=host)
    except (client.ClientError, ValueError) as exc:
        _err(f"applied, but the fetch for the patch failed: {exc}")
        _err(advice)
        return 3
    except Exception as exc:  # noqa: BLE001 -- the apply is done; never end without the advice
        _err(f"applied, but the fetch for the patch failed: {type(exc).__name__}: {exc}")
        _err(advice)
        return 3
    try:
        report = pack.patch(book, cs, outcome, fresh)
    except (ValueError, KeyError, OSError) as exc:
        hint = " -- close the workbook in Excel first" if isinstance(exc, PermissionError) else ""
        _err(f"applied, but the book could not be patched: {exc}{hint}")
        _err(advice)
        return 3
    except Exception as exc:  # noqa: BLE001 -- the apply is done; never end without the advice
        _err(f"applied, but the book could not be patched: {type(exc).__name__}: {exc}")
        _err(advice)
        return 3
    emit(f"patched {book}: {report.text()}")
    if getattr(report, "recalc", False):
        # The patch rewrote cells other formulas read; the built-in evaluator
        # re-cached them (#445). ``--recalc excel`` also has Excel recalculate.
        _recalc(book, args)
    if report.problems:
        _err(advice)
        return 3
    return 0


def cmd_refresh(args) -> int:
    """`est-estimate refresh BOOK [--dry-run] [--host H] [--recalc E]`: bring
    BidSheet.ai's changes since the book's baseline into the book, in place
    (engine spec, "Refresh"). The book is read first (a refused read is
    refused here), the estimate is fetched from the host stamped in the book
    -- a page with its items -- and the pack refreshes the book from that
    payload. Collisions and changes the book cannot take are reported,
    nothing written (exit 4). A refresh that wrote the book gets apply's
    opt-in calculating pass (``_recalc``, #370)."""
    book = Path(args.book)
    got = _read("refresh", book, "nothing written")
    if isinstance(got, int):
        return got
    pack, cs, facts = got
    try:
        host = _apply_host(facts, args.host)
    except ValueError as exc:
        _err(f"refresh refused: {exc} (nothing written)")
        return 1
    except LookupError as exc:
        _err(f"refresh refused: {exc} (nothing written)")
        return 2
    if not args.dry_run and _locked(book):
        _err(f"refresh refused: cannot open {book} for writing (open in Excel, or read-only) -- "
             "close it or make it writable and retry (nothing written)")
        return 2
    try:
        estimate_id = int(cs.estimate_id)
    except (TypeError, ValueError):
        _err(f"refresh refused: the book's estimate id {cs.estimate_id!r} is not a number -- "
             "rebuild it (nothing written)")
        return 2
    _page, items = _covered(pack, book)
    try:
        fresh = client.fetch(estimate_id, item_ids=items, host=host)
    except client.ClientError as exc:
        if not exc.sent:
            _err(f"refresh refused: {exc} (nothing written)")
            return 2
        _err(f"refresh failed: the fetch from BidSheet.ai failed: {exc} (nothing written)")
        return 3
    except ValueError as exc:
        # The ids and host come from the book, already checked: what is left
        # is BidSheet.ai's answer (pages that do not merge, a bad payload).
        _err(f"refresh failed: the fetch from BidSheet.ai failed: {exc} (nothing written)")
        return 3
    try:
        report = pack.refresh(book, fresh, dry_run=args.dry_run)
    except NotYet as exc:
        return _not_yet(pack, exc)
    except (ValueError, KeyError, OSError) as exc:
        hint = " -- close the workbook in Excel first" if isinstance(exc, PermissionError) else ""
        _err(f"refresh refused: {exc}{hint} (nothing written)")
        return 2
    emit(report.text())
    if report.baseline_replaced:
        # The refresh rewrote cells other formulas read (it never does on a
        # dry run, or when anything was reported): the built-in evaluator
        # re-cached them (#445); the opt-in pass is as after apply --commit.
        _recalc(book, args)
    return 0 if report.clean else 4


def add_subparsers(sub) -> None:
    """Add the generic verbs to `est-estimate`'s subparsers (`build --pack` is a
    flag on the existing `build`)."""
    p = sub.add_parser("packs", help="List the installed exchange packs.")
    p.set_defaults(func=cmd_packs)

    p = sub.add_parser("login",
                       help="Store your BidSheet.ai API token (read from stdin or a prompt).")
    p.add_argument("--host", default="https://www.bidsheet.ai")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("fetch", help="Fetch an estimate's workbook payload to a JSON file.")
    p.add_argument("estimate", help="estimate id")
    p.add_argument("--items", default=None, help="comma-separated item ids (a page)")
    p.add_argument("--host", default=None,
                   help="must match the stored token's host (an https origin)")
    p.add_argument("-o", "--output", default=None,
                   help="payload JSON (default: eID.workbook.json, or "
                        "eID.items.workbook.json with --items)")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("read", help="Read an edited workbook into a change set "
                                    "(the pack is detected from the book's stamp).")
    p.add_argument("book")
    p.add_argument("-o", "--output", default=None,
                   help="change-set JSON (default: BOOK.changes.json next to the workbook)")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("apply", help="Dry-run a workbook's change set against BidSheet.ai; "
                                     "--commit applies it and patches the book.")
    p.add_argument("book")
    p.add_argument("--commit", action="store_true", help="apply for real (default: dry run)")
    p.add_argument("--request-id", default=None,
                   help="resend a previous commit's request id (an unknown outcome)")
    p.add_argument("--host", default=None,
                   help="must match the host stamped in the book (an https origin); the stamp "
                        "decides where the apply goes, and it must be the stored token's host")
    p.add_argument("--recalc", choices=("auto", "excel", "libreoffice", "off"), default="off",
                   help="after --commit patches the book, also have a calculating engine "
                        "recalculate it (default off: the built-in evaluator already stored "
                        "cached values; excel: Excel recalculates too, for functions the "
                        "built-in evaluator does not cover; auto: Excel when present; "
                        "libreoffice is unverified). ESTIMATING_RECALC=off switches it off "
                        "everywhere.")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("refresh", help="Bring BidSheet.ai's changes since the book's baseline "
                                       "into the book, in place; collisions are reported, "
                                       "never resolved.")
    p.add_argument("book")
    p.add_argument("--dry-run", action="store_true",
                   help="say what would change, verified on a copy; write nothing")
    p.add_argument("--host", default=None,
                   help="must match the host stamped in the book (an https origin)")
    p.add_argument("--recalc", choices=("auto", "excel", "libreoffice", "off"), default="off",
                   help="after the refresh writes the book, also have a calculating engine "
                        "recalculate it (default off: the built-in evaluator already stored "
                        "cached values; excel: Excel recalculates too, for functions the "
                        "built-in evaluator does not cover; auto: Excel when present; "
                        "libreoffice is unverified). ESTIMATING_RECALC=off switches it off "
                        "everywhere.")
    p.set_defaults(func=cmd_refresh)
