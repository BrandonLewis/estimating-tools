"""Feedback payloads: what ``report-issue`` sends to BidSheet.ai, made deterministic.

The skill interviews the user and the agent writes the text; this package is
the part that must not be left to judgment. ``build_payload`` reduces every
field to bounded, Markdown-only text with user paths and secrets scrubbed, and
``check_payload`` proves a payload is in that form. The server applies the same
Markdown rules on receipt, so a payload built here is stored unchanged.
"""

from estimating_tools.feedback.payload import (
    KINDS,
    PRODUCTS,
    PayloadError,
    build_payload,
    check_payload,
    sanitize_markdown,
    scrub,
)

__all__ = [
    "KINDS",
    "PRODUCTS",
    "PayloadError",
    "build_payload",
    "check_payload",
    "sanitize_markdown",
    "scrub",
]
