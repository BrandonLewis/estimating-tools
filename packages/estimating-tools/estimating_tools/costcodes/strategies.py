"""Parent-derivation strategies: pure functions rows -> {code: parent_code}.

Each strategy takes (rows, mapping, **opts) and returns a dict mapping every
non-blank code to its parent code ("" = root). Codes are read via
mapping["code"]; some strategies also use mapping["parent_code"]/mapping["indent"].
The builder injects the result as each activity code's parent_code BEFORE
validation and topo-sort, which is why the canonical model never needs to know
how a given org encodes hierarchy. Stdlib only."""
from __future__ import annotations

import re


def _code(row, mapping):
    v = row.get(mapping["code"])
    return str(v).strip() if v is not None else ""


def _codes_in_order(rows, mapping):
    out = []
    for r in rows:
        c = _code(r, mapping)
        if c:
            out.append(c)
    return out


def flat(rows, mapping, **opts):
    return {c: "" for c in _codes_in_order(rows, mapping)}


def explicit_column(rows, mapping, **opts):
    col = mapping.get("parent_code")
    result = {}
    for r in rows:
        c = _code(r, mapping)
        if not c:
            continue
        pv = r.get(col) if col else None
        result[c] = str(pv).strip() if pv is not None else ""
    return result


def segment_truncate(rows, mapping, *, delimiters=(" ", "."), **opts):
    codes = _codes_in_order(rows, mapping)
    pattern = "[" + re.escape("".join(delimiters)) + "]+"
    segs = {c: tuple(s for s in re.split(pattern, c) if s) for c in codes}
    # Index codes by their segment tuple so a parent is a dict lookup, not a scan.
    # First code wins a given tuple, preserving the original input-order tie-break.
    by_tuple: dict[tuple, str] = {}
    for c in codes:
        by_tuple.setdefault(segs[c], c)
    result = {}
    for c in codes:
        own = segs[c]
        parent = ""
        # Parent = the longest existing code whose segments are a proper prefix.
        for cut in range(len(own) - 1, 0, -1):
            cand = by_tuple.get(own[:cut])
            if cand is not None and cand != c:
                parent = cand
                break
        result[c] = parent
    return result


def _numeric_stub_parent(code, codes):
    parts = code.split("-")
    if len(parts) != 2:
        return ""
    prefix, suffix = parts
    if suffix == "000":
        return ""
    try:
        n = int(suffix)
    except ValueError:
        return ""
    if n % 100 == 0:
        parent_suffix = "000"
    elif n % 10 == 0:
        parent_suffix = str((n // 100) * 100).zfill(3)
    else:
        parent_suffix = str((n // 10) * 10).zfill(3)
    parent = f"{prefix}-{parent_suffix}"
    return parent if parent in codes and parent != code else ""


def numeric_stub(rows, mapping, **opts):
    ordered = _codes_in_order(rows, mapping)
    codes = set(ordered)
    return {c: _numeric_stub_parent(c, codes) for c in ordered}


def indentation(rows, mapping, **opts):
    col = mapping.get("indent")
    result = {}
    stack = []  # (indent_level, code)
    for r in rows:
        c = _code(r, mapping)
        if not c:
            continue
        raw = r.get(col) if col else None
        try:
            lvl = int(float(str(raw).strip())) if raw not in (None, "") else 0
        except (ValueError, TypeError):
            lvl = 0
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        result[c] = stack[-1][1] if stack else ""
        stack.append((lvl, c))
    return result


REGISTRY = {
    "flat": flat,
    "explicit_column": explicit_column,
    "segment_truncate": segment_truncate,
    "numeric_stub": numeric_stub,
    "indentation": indentation,
}


def resolve_parents(strategy, rows, mapping, **opts):
    """Dispatch to a named strategy. Raises ValueError on an unknown name."""
    try:
        fn = REGISTRY[strategy]
    except KeyError:
        raise ValueError(
            f"unknown parent strategy {strategy!r}; known: {sorted(REGISTRY)}"
        )
    return fn(rows, mapping, **opts)
