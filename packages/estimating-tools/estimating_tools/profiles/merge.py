"""Layer-based deep merge: an ordered list of profile dicts, later wins.

The ordered-list signature is the forward-compatibility seam for the deferred
enforcement tier — a future managed/policy layer is simply appended as a top
layer with no change to this function's callers.
"""
from __future__ import annotations


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def merge(layers: list[dict]) -> dict:
    """Deep-merge an ordered list of layers; later layers win."""
    result: dict = {}
    for layer in layers:
        result = _deep_merge(result, layer)
    return result
