"""Shared row splitters for editable live artifacts.

Both splitters preserve the literal escape sequence (`\\|` or `\\;`) in the returned
tokens; callers unescape after splitting. Pure stdlib. Used by
`importers/mapping_artifact.py` (Phase 1) and `assemblies/artifact.py` (Phase 2a)."""
from __future__ import annotations


def split_pipes(s: str) -> list[str]:
    """Split `s` on `|`, treating `\\|` as a literal pipe that stays with its token."""
    return _split_on(s, "|")


def split_semicolons(s: str) -> list[str]:
    """Split `s` on `;`, treating `\\;` as a literal semicolon that stays with its token."""
    return _split_on(s, ";")


def _split_on(s: str, sep: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] == sep:
            cur.append("\\" + sep)
            i += 2
            continue
        if c == sep:
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def escape_string_field(s: str) -> str:
    """JSON-style escape for a table cell / blockquote line (`\\`, `\\n`, `\\r`, `\\t`,
    control chars). `ensure_ascii=False` keeps non-ASCII characters human-readable in the
    rendered artifact (accented names, symbols). Wraps the result unquoted so md_table's
    pipe escape composes cleanly on top."""
    import json
    return json.dumps(s, ensure_ascii=False)[1:-1]


def unescape_string_field(s: str) -> str:
    """Reverse `escape_string_field`. Short-circuits when the cell contains no backslash —
    plain user text (e.g. `4" PVC`) passes through unchanged even though it contains a
    double quote JSON would ordinarily require escaped."""
    if "\\" not in s:
        return s
    import json
    return json.loads(f'"{s}"')
