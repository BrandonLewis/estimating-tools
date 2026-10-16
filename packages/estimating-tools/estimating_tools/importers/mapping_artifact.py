"""ProposedMapping — the editable live artifact for the importer skills.

A `ProposedMapping` is a list of `(canonical_field, spreadsheet_column, is_required,
sample_values)` rows, rendered as a pipe-safe markdown table for the user to review /
edit inline, and parsed back into the same dataclass. `to_mapping_dict` produces the
`{canonical_field: spreadsheet_column}` shape the existing importer builders consume.

Pure stdlib. No openpyxl, no MCP, no file IO. Uses `estimating_tools.artifacts.md_table`
for the render (pipe-safe)."""
from __future__ import annotations

from dataclasses import dataclass

from estimating_tools.artifact_common import split_pipes as _split_pipes, split_semicolons as _split_semicolons
from estimating_tools.artifacts import md_table


_HEADER_COMMENT = "<!-- editable — set column to '-' to skip a field -->"
_HEADERS = ("Canonical field", "Spreadsheet column", "Sample values")


@dataclass(frozen=True)
class MappingRow:
    canonical_field: str
    spreadsheet_column: str | None                 # None means "skip"
    is_required: bool
    sample_values: tuple[str, ...]

    def __post_init__(self) -> None:
        # '*' marks 'required' in the rendered table; a canonical name ending in '*'
        # would silently be renamed on parse. Reject at construction so the round-trip
        # invariant holds for every ProposedMapping that exists.
        if self.canonical_field.endswith("*"):
            raise ValueError(
                f"canonical_field must not end with '*': {self.canonical_field!r}"
            )


@dataclass(frozen=True)
class ProposedMapping:
    rows: tuple[MappingRow, ...]


def render(pm: ProposedMapping) -> str:
    body = []
    for r in pm.rows:
        name = r.canonical_field + ("*" if r.is_required else "")
        col = r.spreadsheet_column if r.spreadsheet_column is not None else "-"
        # Escape ';' so sample values containing it round-trip. The parser splits on
        # bare ';' and honors '\;' as a literal.
        samples = "; ".join(s.replace(";", "\\;") for s in r.sample_values)
        body.append([name, col, samples])
    return _HEADER_COMMENT + "\n" + md_table(list(_HEADERS), body)


def _unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def parse(text: str) -> ProposedMapping:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    body: list[list[str]] = []
    seen_header = False
    for raw_ln in lines:
        ln = raw_ln.lstrip()                                  # tolerate indentation
        if ln.startswith("<!--"):
            continue
        if not ln.startswith("|"):
            continue
        cells = _split_table_row(ln)
        if not seen_header:
            if [c.strip() for c in cells] == list(_HEADERS):
                seen_header = True
            continue
        if all(c.strip().strip("-") == "" for c in cells):    # separator row
            continue
        body.append(cells)
    if not seen_header:
        raise ValueError(
            "could not find header row "
            "'| Canonical field | Spreadsheet column | Sample values |' — "
            "was a header cell renamed or the header row deleted?"
        )
    rows: list[MappingRow] = []
    seen_fields: set[str] = set()
    for i, cells in enumerate(body, start=1):
        if len(cells) != 3:
            raise ValueError(
                f"row {i}: expected 3 columns ({', '.join(_HEADERS)}), got {len(cells)}"
            )
        raw_field, raw_col, raw_samples = (_unescape(c.strip()) for c in cells)
        is_required = raw_field.endswith("*")
        canonical_field = raw_field.rstrip("*").strip()
        if not canonical_field:
            raise ValueError(f"row {i}: canonical_field is empty")
        if canonical_field in seen_fields:
            raise ValueError(f"row {i}: duplicate canonical_field {canonical_field!r}")
        seen_fields.add(canonical_field)
        col: str | None = None if raw_col.strip() == "-" else (raw_col or None)
        samples = tuple(
            s2 for s2 in (
                s.replace("\\;", ";").strip() for s in _split_semicolons(raw_samples)
            ) if s2
        )
        rows.append(MappingRow(canonical_field, col, is_required, samples))
    return ProposedMapping(rows=tuple(rows))


def _split_table_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return _split_pipes(inner)


def to_mapping_dict(pm: ProposedMapping, required: set[str] | None = None) -> dict[str, str]:
    """The mapping the existing `build_<X>(rows, mapping=…)` builders expect. Omits
    rows where `spreadsheet_column is None` (skipped) or where the column equals the
    canonical field (identity — the builders' default handles it).

    Raises `ValueError` if any required field is marked skipped: the user's explicit
    'skip this' would otherwise silently drop and the downstream builder would either
    fail with a misleading identity-lookup error or (worse) silently accept a
    same-named column.

    If `required` is provided, it is the authoritative set of canonical field names
    that cannot be skipped (`-`); otherwise `row.is_required` is used. Pass the
    importer's `_REQUIRED` here so requiredness enforcement doesn't depend on the `*`
    marker surviving user edits."""
    if required is not None:
        skipped_required = [
            r.canonical_field for r in pm.rows
            if r.canonical_field in required and r.spreadsheet_column is None
        ]
    else:
        skipped_required = [
            r.canonical_field for r in pm.rows
            if r.is_required and r.spreadsheet_column is None
        ]
    if skipped_required:
        raise ValueError(
            f"required field(s) cannot be skipped: {', '.join(skipped_required)}"
        )
    return {
        r.canonical_field: r.spreadsheet_column
        for r in pm.rows
        if r.spreadsheet_column is not None and r.spreadsheet_column != r.canonical_field
    }


def propose_mapping(
    canonical_fields,
    required,
    header_row,
    sample_rows,
    *,
    max_samples: int = 3,
) -> ProposedMapping:
    required_set = set(required)
    normalized = {_normalize(h): h for h in header_row}
    rows: list[MappingRow] = []
    for cf in canonical_fields:
        guessed = normalized.get(_normalize(cf))
        samples: tuple[str, ...] = ()
        if guessed is not None:
            seen: list[str] = []
            for r in sample_rows:
                v = r.get(guessed)
                if v is None or v == "":
                    continue
                text = str(v).strip()
                if text and text not in seen:
                    seen.append(text)
                if len(seen) >= max_samples:
                    break
            samples = tuple(seen)
        rows.append(MappingRow(cf, guessed, cf in required_set, samples))
    return ProposedMapping(rows=tuple(rows))


def _normalize(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())
