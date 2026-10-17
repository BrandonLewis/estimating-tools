"""est-feedback -- build, check and list FeedbackReport payloads.

The report-issue skill sends exactly what ``build`` prints, and nothing it did
not print: every field is Markdown-only, scrubbed of home paths and token
shapes, and bounded, whatever the agent typed. The server applies the same
Markdown rules on receipt, so a built payload is stored unchanged.

Subcommands:
  build   fields -> payload JSON on stdout (or --out), ready for
          create_feedback_report. Exit 1 with the reason when a field cannot
          be made valid (too long, empty, bad choice).
  check   payload JSON file -> "OK" or the list of problems (exit 1). A payload
          passes only when rebuilding it changes nothing.
  drafts  list feedback-draft-*.json in a directory (default: cwd) with each
          one's check result -- the resend queue for a server that was down.

No network: filing stays at the skill layer through the MCP.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from estimating_tools.feedback.payload import (
    KINDS,
    PRODUCTS,
    PayloadError,
    build_payload,
    check_payload,
    scrub,
)

DRAFT_GLOB = "feedback-draft-*.json"
#: Lines of an error file kept, from the end, where the actual error is.
DEFAULT_ERROR_LINES = 40


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _parse_context_args(items) -> dict:
    """``key=value`` pairs; a value that parses as JSON (number, bool, null,
    list, object) is kept as that type, anything else is text."""
    context = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise PayloadError(f"--context expects key=value, got {item!r}.")
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        if not isinstance(parsed, (str, int, float, bool, list, dict)) and parsed is not None:
            parsed = value
        context[key.strip()] = parsed
    return context


def error_excerpt(text: str, *, lines: int = DEFAULT_ERROR_LINES) -> str:
    """The tail of an error dump, scrubbed. Trimming happens before scrubbing
    so the kept lines are the ones a reader actually needs."""
    kept = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(kept) > lines:
        kept = [f"... ({len(kept) - lines} earlier lines trimmed)"] + kept[-lines:]
    return scrub("\n".join(kept))


def cmd_build(args) -> int:
    try:
        if args.body_file:
            body = _read_text(args.body_file)
        else:
            body = args.body or ""
        context = _parse_context_args(args.context)
        if args.plugin_version:
            context["plugin_version"] = args.plugin_version
        if args.os:
            context["os"] = args.os
        if args.skill:
            context["skill"] = args.skill
        if args.cli_command:
            context["cli_command"] = scrub(args.cli_command)
        if args.error_file:
            context["error_excerpt"] = error_excerpt(_read_text(args.error_file),
                                                     lines=args.error_lines)
        payload = build_payload(product=args.product, kind=args.kind, title=args.title,
                                body=body, context=context)
    except FileNotFoundError as exc:
        print(f"est-feedback: no such file: {exc.filename}", file=sys.stderr)
        return 1
    except PayloadError as exc:
        print(f"est-feedback: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    if args.out:
        try:
            with Path(args.out).open("x", encoding="utf-8") as output:
                output.write(text + "\n")
        except FileExistsError:
            print(f"est-feedback: output file already exists: {args.out}; choose a new filename.",
                  file=sys.stderr)
            return 1
        print("WROTE:", args.out)
    else:
        # stdout may be a console that can't encode the text (cp1252 on
        # Windows has no "≥"); escaped JSON is the same JSON, and it prints
        # anywhere. The --out file above stays readable UTF-8.
        print(json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


def _check_file(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"no such file: {path}"]
    except ValueError as exc:
        return [f"not JSON: {exc}"]
    return check_payload(payload)


def cmd_check(args) -> int:
    problems = _check_file(Path(args.payload))
    if problems:
        for problem in problems:
            print(f"est-feedback: {problem}", file=sys.stderr)
        return 1
    print("OK: payload is sanitized Markdown and ready to send")
    return 0


def cmd_drafts(args) -> int:
    directory = Path(args.directory or ".")
    drafts = sorted(directory.glob(DRAFT_GLOB))
    if not drafts:
        print(f"no {DRAFT_GLOB} in {directory}")
        return 0
    bad = 0
    for draft in drafts:
        problems = _check_file(draft)
        if problems:
            bad += 1
            print(f"{draft}: NEEDS REBUILD -- {'; '.join(problems)}")
        else:
            print(f"{draft}: ready")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="est-feedback",
        description="Build, check and list FeedbackReport payloads (Markdown only, scrubbed).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="fields -> payload JSON")
    b.add_argument("--product", required=True, choices=PRODUCTS)
    b.add_argument("--kind", required=True, choices=KINDS)
    b.add_argument("--title", required=True)
    body = b.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="the description, Markdown")
    body.add_argument("--body-file", help="file holding the description")
    b.add_argument("--context", action="append", metavar="KEY=VALUE",
                   help="extra context entry; repeatable")
    b.add_argument("--plugin-version")
    b.add_argument("--os", help='e.g. "Windows 11", "macOS 15"')
    b.add_argument("--skill", help="the skill in play, when the report is about one")
    b.add_argument("--cli-command", help="the failing command line")
    b.add_argument("--error-file", help="raw error output; trimmed and scrubbed")
    b.add_argument("--error-lines", type=int, default=DEFAULT_ERROR_LINES,
                   help=f"lines of the error file to keep, from the end (default {DEFAULT_ERROR_LINES})")
    b.add_argument("--out", help="write the payload to a new file instead of stdout; must not exist")
    b.set_defaults(fn=cmd_build)

    c = sub.add_parser("check", help="payload JSON -> OK or problems")
    c.add_argument("payload")
    c.set_defaults(fn=cmd_check)

    d = sub.add_parser("drafts", help=f"list {DRAFT_GLOB} with each one's check result")
    d.add_argument("directory", nargs="?")
    d.set_defaults(fn=cmd_drafts)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
