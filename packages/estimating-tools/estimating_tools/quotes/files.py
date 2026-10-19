"""Read and write CanonicalQuote JSON files (one per vendor and work package)."""
from __future__ import annotations

import json
import math
import re
from dataclasses import fields
from datetime import date
from pathlib import Path

from estimating_tools.quotes.model import CanonicalQuote, QuoteLine


class QuoteFileError(ValueError):
    pass


_QUOTE_KEYS = {f.name for f in fields(CanonicalQuote)}
_LINE_KEYS = {f.name for f in fields(QuoteLine)}


def _unknown(path: Path, data: dict, allowed: set[str]) -> None:
    for key in data:
        if key not in allowed:
            raise QuoteFileError(f"{path}: unknown key '{key}'")


def _number(path: Path, name: str, value) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise QuoteFileError(f"{path}: {name} must be a number")
    return value


#: Field types a quote file is checked against (None is allowed for every
#: optional field; the required ones are checked for presence first).
_NUMBERS = ("unit_price", "amount", "quantity", "surcharge")
_BOOLS = ("is_included", "is_alternate", "is_dbe")
_STRINGS = ("item_number", "schedule_name", "line_name", "folded_into", "vendor_name",
            "work_package_name", "quote_ref", "exclusion_notes", "notes", "contact_info")
_REQUIRED = ("vendor_name", "work_package_name", "schedule_name", "item_number")


def _check_types(path: Path, raw: dict, where: str = "") -> None:
    """Refuse a value of the wrong JSON type: `<path>: [line N: ]<key> must be ...`."""
    at = f"{path}: {where}"
    for key, value in raw.items():
        if value is None and key not in _REQUIRED and key not in _BOOLS:
            continue
        if key in _NUMBERS:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise QuoteFileError(f"{at}{key} must be a number")
        elif key in _BOOLS:
            if not isinstance(value, bool):
                raise QuoteFileError(f"{at}{key} must be true or false")
        elif key in _STRINGS:
            if not isinstance(value, str):
                raise QuoteFileError(f"{at}{key} must be a string")
        elif key == "vendor_id":
            if isinstance(value, bool) or not isinstance(value, int):
                raise QuoteFileError(f"{at}{key} must be an integer")


def _line(path: Path, n: int, raw) -> QuoteLine:
    if not isinstance(raw, dict):
        raise QuoteFileError(f"{path}: line {n} must be an object")
    _unknown(path, raw, _LINE_KEYS)
    for req in ("schedule_name", "item_number"):
        if req not in raw:
            raise QuoteFileError(f"{path}: line {n} missing '{req}'")
    _check_types(path, raw, f"line {n}: ")
    line = QuoteLine(**raw)
    if (line.unit_price is None and line.amount is None and line.is_included
            and not line.folded_into):
        raise QuoteFileError(f"{path}: line {n} has no price")
    return line


def load_quote_file(path: Path) -> CanonicalQuote:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise QuoteFileError(f"{path}: {e}") from e
    if not isinstance(data, dict):
        raise QuoteFileError(f"{path}: expected a JSON object")
    _unknown(path, data, _QUOTE_KEYS)
    for req in ("vendor_name", "work_package_name"):
        if req not in data:
            raise QuoteFileError(f"{path}: missing '{req}'")
    _check_types(path, {k: v for k, v in data.items() if k not in ("lines", "conditions")})
    raw_lines = data.get("lines", [])
    if not isinstance(raw_lines, list):
        raise QuoteFileError(f"{path}: lines must be a list")
    raw_cond = data.get("conditions", {})
    if not isinstance(raw_cond, dict):
        raise QuoteFileError(f"{path}: conditions must be a mapping of string to string")
    conditions = {}
    for k, v in raw_cond.items():
        if isinstance(v, (dict, list)) or v is None:
            raise QuoteFileError(f"{path}: conditions must be a mapping of string to string")
        conditions[str(k)] = str(v)
    surcharge = data.get("surcharge")
    if surcharge is not None:
        _number(path, "surcharge", surcharge)
    quote_date = data.get("quote_date")
    if quote_date is not None:
        try:
            if not isinstance(quote_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", quote_date):
                raise ValueError
            date.fromisoformat(quote_date)
        except ValueError:
            raise QuoteFileError(f"{path}: quote_date must be YYYY-MM-DD") from None
    header = {k: v for k, v in data.items() if k not in ("lines", "conditions")}
    quote = CanonicalQuote(
        **header,
        lines=[_line(path, i, raw) for i, raw in enumerate(raw_lines, start=1)],
        conditions=conditions,
    )
    # Not a field (never written back, never compared): the file it came from,
    # for a spread sheet's default quote ref.
    quote.source_file = path.name
    return quote


def load_quotes(directory: Path) -> list[CanonicalQuote]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    files = [p for p in directory.glob("*.json") if not p.name.endswith(".example.json")]
    quotes = [(load_quote_file(p), p.name) for p in files]
    quotes.sort(key=lambda qn: (qn[0].quote_date or "", qn[1]))
    return [q for q, _ in quotes]


def write_quote_file(path: Path, quote: CanonicalQuote) -> None:
    out = {}
    for f in fields(quote):
        value = getattr(quote, f.name)
        if f.name == "lines":
            value = [{lf.name: getattr(l, lf.name) for lf in fields(l)
                      if getattr(l, lf.name) is not None} for l in value]
        elif value is None:
            continue
        out[f.name] = value
    Path(path).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def quote_file_slug(vendor_name: str, package_name: str) -> str:
    return f"{_slug(vendor_name)}--{_slug(package_name)}.json"
