"""Cross-module invariants for the estimate spec.

Currently a single helper: `_is_valid_id`. Shared between `compact.py`'s
parse/render helpers and `sync.py`'s item-diff logic so both modules agree
on what counts as a "synced" (BM-anchored) id.
"""
from __future__ import annotations


def _is_valid_id(value) -> bool:
    """A valid `estimate_item_id` is a positive integer.

    Rejects: None, bool (int subclass), float, string, 0, negatives.
    Mirrors the schema's `estimate_item_id: {"type": "integer", "minimum": 1}`.
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, int):
        return False
    return value >= 1
