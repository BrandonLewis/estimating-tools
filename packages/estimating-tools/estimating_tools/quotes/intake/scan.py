"""Walk the inbox, hash what is there, and unpack .eml containers."""
from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from estimating_tools.quotes.intake.inventory import (
    Document, Inventory, now_iso, sha256_file)

SUPPORTED = frozenset({".pdf", ".docx", ".xlsx", ".xls", ".csv", ".eml", ".png", ".jpg",
                       ".jpeg", ".txt", ".md"})
MSG_REASON = "save the message as .eml or save its attachments"
EML_HEADERS_MARKER = "[email headers -- not part of the quote body]"

_BLOCKS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
_SKIPPED = {"style", "script"}


@dataclass
class ScanReport:
    new: int = 0
    known: int = 0
    unsupported: dict[str, int] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    changed: bool = False        # the scan changed the inventory
    missing_inbox: bool = False  # the inbox folder does not exist

    def summary(self) -> str:
        return f"{self.new} new, {self.known} known, {sum(self.unsupported.values())} unsupported"


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED:
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCKS and tag != "br":
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def strip_html(html: str) -> str:
    parser = _Stripper()
    parser.feed(html)
    parser.close()
    lines = [ln.strip() for ln in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name.replace("\\", "/")).name).lstrip(".")
    if not base:
        return "attachment"
    if len(base) > 120:
        stem, dot, ext = base.rpartition(".")
        ext = ("." + ext[:20]) if dot else ""
        base = (stem if dot else base)[:120 - len(ext)] + ext
    return base


def unpack_eml(path: Path, out_dir: Path) -> list[Path]:
    """Write the body and every named part of the message into `out_dir`."""
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=email.policy.default)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body is not None else None
    if text is None:
        html_part = msg.get_body(preferencelist=("html",))
        text = strip_html(html_part.get_content()) if html_part is not None else None
    if text is not None:
        # The sender and date often say whose quote this is and when it was sent;
        # the block is marked so they are not read as part of the quote.
        headers = [f"{name}: {msg[name]}" for name in ("From", "Date", "Subject")
                   if msg[name] is not None]
        if headers:
            text = "\n".join([EML_HEADERS_MARKER, *headers, "", text])
        target = out_dir / "body.txt"
        target.write_text(text, encoding="utf-8")
        written.append(target)
    taken = {"body.txt"}
    for part in msg.walk():
        name = part.get_filename()
        if not name:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        safe = _safe_name(name)
        stem, dot, ext = safe.rpartition(".")
        if not dot:
            stem, ext = safe, ""
        candidate, n = safe, 1
        while candidate.casefold() in taken:
            n += 1
            candidate = f"{stem} ({n})" + (f".{ext}" if ext else "")
        taken.add(candidate.casefold())
        target = out_dir / candidate
        target.write_bytes(payload)
        written.append(target)
    return written


def _hidden(rel: Path) -> bool:
    return any(p == "_intake" or p.startswith(".") for p in rel.parts)


def _changed(inv: Inventory, report: ScanReport) -> None:
    inv.touch()
    report.changed = True


def _ingest(inv: Inventory, path: Path, report: ScanReport, state_dir: Path,
            seen: set[str], parent: str | None = None) -> None:
    suffix = path.suffix.casefold()
    if suffix not in SUPPORTED and suffix != ".msg":
        report.unsupported[suffix] = report.unsupported.get(suffix, 0) + 1
        return
    spath = str(path)
    try:
        sha = sha256_file(path)
        size = path.stat().st_size
    except OSError as exc:
        report.lines.append(f"error {spath}: {type(exc).__name__}: {exc}")
        return
    seen.add(sha)
    known = inv.get(sha)
    owner = inv.by_path(spath)
    if known is not None:
        if spath not in known.paths:
            known.paths.append(spath)
            _changed(inv, report)
        if owner is not None and owner is not known and owner.superseded_by != sha:
            owner.superseded_by = sha
            _changed(inv, report)
        report.known += 1
        return
    if owner is not None:
        owner.superseded_by = sha
    _changed(inv, report)
    doc = Document(sha256=sha, paths=[spath], first_seen=now_iso(), size=size,
                   kind=suffix.lstrip("."), status="new", parent=parent)
    report.new += 1
    if suffix == ".msg":
        doc.route, doc.status, doc.reason = "unsupported", "held", MSG_REASON
        inv.add(doc)
    elif suffix == ".eml":
        try:
            children = unpack_eml(path, state_dir / "docs" / sha)
        except Exception as exc:  # noqa: BLE001 - one bad message must not stop the scan
            doc.status = "error"
            doc.reason = f"{type(exc).__name__}: {exc}"
            inv.add(doc)
            return
        doc.status = "not_quote"
        doc.reason = f"email container: {len(children)} document(s) unpacked"
        inv.add(doc)
        for child in children:
            _ingest(inv, child, report, state_dir, seen, parent=sha)
    else:
        inv.add(doc)


def scan_inbox(inv: Inventory, inbox: Path, state_dir: Path) -> ScanReport:
    report = ScanReport()
    if not inbox.exists():
        report.lines.append(f"inbox {inbox} does not exist")
        report.missing_inbox = True
        return report
    seen: set[str] = set()
    for path in sorted(inbox.rglob("*")):
        if not path.is_file() or _hidden(path.relative_to(inbox)):
            continue
        _ingest(inv, path, report, state_dir, seen)
    # A record is superseded only while none of its bytes are in the inbox.
    for sha in seen:
        doc = inv.get(sha)
        if doc.superseded_by is not None:
            doc.superseded_by = None
            _changed(inv, report)
    return report
