"""Build and check a FeedbackReport payload.

Two guarantees, both enforced here rather than asked of the agent:

* **Markdown only.** Every text field is normalized (NFC, LF), stripped of raw
  HTML tags and comments, of control characters and of the invisible
  zero-width / bidirectional-override code points, and bounded in length.
  These are the server's rules (BidSheet.ai ``feedback_markdown``), applied
  first on the client, and the function is idempotent: a clean payload is a
  fixed point, which is what ``check_payload`` tests.
* **Nothing identifying leaves by accident.** ``scrub`` replaces home-directory
  paths with ``~``, email addresses and the common token shapes (JWT, bearer,
  vendor API keys, ``key=value`` secrets) with bracketed placeholders --
  ``[redacted-token]``, not ``<redacted-token>``, which the Markdown rule
  would strip as a tag. It runs on the
  body and on every string in ``context`` -- the error excerpt is where paths
  and tokens hide. The server strips HTML, not secrets; this is the only place
  that does.

Pure functions, no I/O: ``est-feedback`` (``cli.py``) is the file layer.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata

PRODUCTS = ("estimating-plugin", "bidmanager")
KINDS = ("bug", "feature-request")

MAX_TITLE_CHARS = 255
MAX_BODY_CHARS = 20_000
MAX_CONTEXT_STRING_CHARS = 4_000
MAX_CONTEXT_KEY_CHARS = 64
MAX_CONTEXT_DEPTH = 3
#: The server's bound on the serialized ``context`` object.
MAX_CONTEXT_BYTES = 16_384

PAYLOAD_KEYS = ("product", "kind", "title", "body", "context")


class PayloadError(ValueError):
    """A field cannot be made into a valid payload; the message says why."""


# -- Markdown only -----------------------------------------------------------

_HTML_RE = re.compile(
    r"<!--.*?-->"
    r"|<!\[CDATA\[.*?\]\]>"
    r"|<\?.*?\?>"
    r"|<![A-Za-z][^>]*>"
    r"|</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*)?/?>",
    re.DOTALL,
)
_INVISIBLE_RE = re.compile(
    "[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f"
    "​-‏  ‪-‮⁠-⁤⁦-⁩﻿]"
)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _normalize_markdown(text: str) -> str:
    while True:
        previous = text
        text = unicodedata.normalize("NFC", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _INVISIBLE_RE.sub("", text)
        text = _HTML_RE.sub("", text)
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        text = _BLANK_RUN_RE.sub("\n\n", text).strip()
        if text == previous:
            return text


def sanitize_markdown(value, *, field: str, limit: int, required: bool = True) -> str:
    """Return ``value`` as bounded, Markdown-only text, or raise ``PayloadError``.

    Never truncates: a report cut off mid-sentence is worse than one refused
    with a reason the user can act on.
    """
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise PayloadError(f"{field} must be text, not {type(value).__name__}.")
    text = _normalize_markdown(value)
    if required and not text:
        raise PayloadError(f"{field} is required.")
    if len(text) > limit:
        raise PayloadError(f"{field} is too long ({len(text)} characters; limit {limit}).")
    return text


# -- Scrubbing ---------------------------------------------------------------

_SECRET_KEY = (
    r"(?:[A-Za-z0-9]+[_-])*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|"
    r"client[_-]?secret|password|passwd|pwd)"
)
_SECRET_KEY_RE = re.compile(_SECRET_KEY, re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>(?P<key_quote>[\"']?)\b" + _SECRET_KEY
    + r"(?P=key_quote)\s*[=:]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;&\"']+)",
    re.IGNORECASE,
)
_HOME_COMPONENT = r"(?:[^\\/\s:\"']+(?:[ \t]+[^\\/\s:\"']+)*(?=[\\/\"'])|[^\\/\s:\"']+)"


def _redact_assignment(match: re.Match) -> str:
    value = match.group("value")
    quote = value[0] if value[0] in "\"'" else ""
    return match.group("prefix") + quote + "[redacted]" + quote


_SCRUB = [
    # Home directories, both spellings on Windows and the two POSIX layouts.
    (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+" + _HOME_COMPONENT, re.IGNORECASE), "~"),
    (re.compile(r"(?<![\w/])/(?:home|Users)/" + _HOME_COMPONENT), "~"),
    # JWTs: three base64url segments, the first always starting "eyJ".
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
     "[redacted-token]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [redacted-token]"),
    # Vendor key shapes: OpenAI/Anthropic sk-, GitHub gh?_, Slack xox?-, AWS AKIA.
    (re.compile(r"\b(?:sk|ghp|gho|ghu|ghs|ghr|github_pat)[-_][A-Za-z0-9_-]{16,}"),
     "[redacted-token]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[redacted-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted-token]"),
    # key=value / key: value with a secret-looking key.
    (_SECRET_ASSIGNMENT_RE, _redact_assignment),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
]


def scrub(text: str) -> str:
    """Replace home paths, addresses and token shapes with placeholders."""
    for pattern, replacement in _SCRUB:
        text = pattern.sub(replacement, text)
    return text


def _sanitize_scrubbed(value, *, field: str, limit: int, required: bool = True,
                      single_line: bool = False) -> str:
    if isinstance(value, str):
        while True:
            previous = value
            value = _normalize_markdown(value)
            if single_line:
                value = " ".join(value.split())
            value = scrub(value)
            if value == previous:
                break
    return sanitize_markdown(value, field=field, limit=limit, required=required)


# -- Payload -----------------------------------------------------------------

def _choice(field: str, value, choices) -> str:
    if value not in choices:
        raise PayloadError(f"{field} must be one of {', '.join(choices)}; got {value!r}.")
    return value


def sanitize_title(value) -> str:
    return _sanitize_scrubbed(value, field="title", limit=MAX_TITLE_CHARS,
                              single_line=True)


def sanitize_body(value) -> str:
    return _sanitize_scrubbed(value, field="body", limit=MAX_BODY_CHARS)


def sanitize_context(value) -> dict:
    """``context`` with every string scrubbed and sanitized, bounded in depth
    and size. Secret-keyed values are redacted regardless of their type;
    other numbers, booleans and null pass through."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PayloadError(f"context must be a JSON object, not {type(value).__name__}.")
    clean = _context_value(value, path="context", depth=0)
    size = len(json.dumps(clean, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    if size > MAX_CONTEXT_BYTES:
        raise PayloadError(f"context is too large ({size} bytes; limit {MAX_CONTEXT_BYTES}). "
                           "Trim the error excerpt rather than attaching a whole log.")
    return clean


def _context_value(value, *, path: str, depth: int):
    if depth > MAX_CONTEXT_DEPTH:
        raise PayloadError(f"{path} is nested too deeply (limit {MAX_CONTEXT_DEPTH} levels).")
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PayloadError(f"{path} has a non-text key {key!r}.")
            clean_key = _sanitize_scrubbed(key, field=f"{path} key",
                                           limit=MAX_CONTEXT_KEY_CHARS, single_line=True)
            if _SECRET_KEY_RE.fullmatch(clean_key):
                out[clean_key] = "[redacted]"
            else:
                out[clean_key] = _context_value(item, path=f"{path}.{clean_key}", depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_context_value(item, path=f"{path}[{i}]", depth=depth + 1)
                for i, item in enumerate(value)]
    if isinstance(value, str):
        return _sanitize_scrubbed(value, field=path, limit=MAX_CONTEXT_STRING_CHARS,
                                  required=False)
    if isinstance(value, float) and not math.isfinite(value):
        raise PayloadError(f"{path} must be a finite number.")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise PayloadError(f"{path} has an unsupported type {type(value).__name__}.")


def build_payload(*, product: str, kind: str, title, body, context=None) -> dict:
    """The exact object ``create_feedback_report`` is called with."""
    return {
        "product": _choice("product", product, PRODUCTS),
        "kind": _choice("kind", kind, KINDS),
        "title": sanitize_title(title),
        "body": sanitize_body(body),
        "context": sanitize_context(context),
    }


def check_payload(payload) -> list[str]:
    """Problems with ``payload``; empty when it is exactly what ``build_payload``
    would produce from itself -- i.e. already Markdown-only, scrubbed, bounded."""
    if not isinstance(payload, dict):
        return [f"payload must be a JSON object, not {type(payload).__name__}."]
    problems = []
    extra = sorted(set(payload) - set(PAYLOAD_KEYS))
    missing = [k for k in PAYLOAD_KEYS if k not in payload]
    if extra:
        problems.append(f"unexpected field(s): {', '.join(extra)}.")
    if missing:
        problems.append(f"missing field(s): {', '.join(missing)}.")
    if problems:
        return problems
    try:
        rebuilt = build_payload(**payload)
    except PayloadError as exc:
        return [str(exc)]
    for key in PAYLOAD_KEYS:
        if rebuilt[key] != payload[key]:
            problems.append(f"{key} is not sanitized: rebuilding it changes it.")
    return problems
