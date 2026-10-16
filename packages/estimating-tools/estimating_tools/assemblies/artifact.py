"""Editable live artifact for the assembly library — Phase 2a.

`render(library)` emits one `## <name> [<type>] (cost_code: <code>)` heading per
assembly, an optional `> description` blockquote, and a components table (via the
pipe-safe `md_table`). `parse(text)` reverses the render into the same
`CanonicalAssemblyLibrary` dataclass; round-trip preserves; every real structural edit
is tolerated; malformed input raises `ValueError` with a section+row locator.

Pure stdlib. Reuses `estimating_tools.artifacts.md_table` / `format_money` /
`format_qty` and the escape-aware splitters from `estimating_tools.artifact_common`."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from estimating_tools.artifact_common import (
    escape_string_field as _escape_string_field,
    split_pipes,
    unescape_string_field as _unescape_string_field,
)
from estimating_tools.artifacts import format_money, format_qty, md_table
from estimating_tools.assemblies.model import Assembly, CanonicalAssemblyLibrary, Component
from estimating_tools.assemblies.plan import VALID_COMPONENT_TYPES


_COMPONENT_TABLE_HEADERS = (
    "component_type", "component", "quantity", "unit", "unit_cost", "rate_ref", "trade",
    "description",
)
_HEADING_RE = re.compile(
    r"^## (?P<name>.+?) \[(?P<type>[^\]]*)\] \(cost_code: (?P<code>.+?)\)$"
)
_INVALID_HEADING_CHARS = "\n\r[]()"


def _cell_or_dash(value: str | None) -> str:
    """Renders `""` or `None` as `-` (unified sentinel across component cells).
    Non-sentinel values are JSON-escaped so ``\\n``, ``\\``, etc. round-trip cleanly."""
    if value is None or value == "":
        return "-"
    return _escape_string_field(value)


def _render_number_or_dash(value: float | None) -> str:
    return "-" if value is None else format_money(value)


def _validate_for_render(library: CanonicalAssemblyLibrary) -> None:
    """Reject characters that would break the heading regex or otherwise cause
    silent parse failure. Heading fields (`name`, `assembly_type`, `cost_code`)
    are not quote-delimited, so we cannot JSON-escape them; instead we reject
    illegal characters at render time with a per-field locator."""
    for i, a in enumerate(library.assemblies, start=1):
        for field, value in (("name", a.name), ("assembly_type", a.assembly_type),
                             ("cost_code", a.cost_code or "")):
            for ch in _INVALID_HEADING_CHARS:
                if ch in value:
                    raise ValueError(
                        f"assembly {i} field {field!r}: contains illegal heading "
                        f"character {ch!r} (cannot appear in name / assembly_type / cost_code)"
                    )


def render_assembly(a: Assembly) -> str:
    """Section body: optional description blockquote + components table. Emits no
    trailing newline (the library renderer supplies section joining)."""
    parts: list[str] = []
    if a.description:
        parts.append(f"> {_escape_string_field(a.description)}")
        parts.append("")
    rows = [
        [
            _escape_string_field(c.component_type),           # always literal, not sentinel — but still escape defensively
            _escape_string_field(c.name),
            format_qty(c.quantity),
            _cell_or_dash(c.unit),
            _render_number_or_dash(c.unit_cost),
            _cell_or_dash(c.rate_ref),
            _cell_or_dash(c.trade),
            _cell_or_dash(c.description),
        ]
        for c in a.components
    ]
    parts.append(md_table(list(_COMPONENT_TABLE_HEADERS), rows))
    return "\n".join(parts)


def render(library: CanonicalAssemblyLibrary) -> str:
    """One section per assembly; sections joined by `\\n\\n`. Empty library → `""`.

    Raises `ValueError` if any assembly's `name`, `assembly_type`, or `cost_code`
    contains a character (`\\n`, `\\r`, `[`, `]`, `(`, `)`) that would break the
    heading regex on round-trip."""
    _validate_for_render(library)
    sections: list[str] = []
    for a in library.assemblies:
        cost_code = a.cost_code if a.cost_code else "-"
        header = f"## {a.name} [{a.assembly_type}] (cost_code: {cost_code})"
        sections.append(f"{header}\n\n{render_assembly(a)}")
    return "\n\n".join(sections)


# ---------- parse ----------

def parse(text: str) -> CanonicalAssemblyLibrary:
    """Reverse `render` into a `CanonicalAssemblyLibrary`.

    Round-trip: `parse(render(lib)) == lib` for any library `lib` whose cells honor the
    sentinel conventions. Tolerates all real user edits: renaming, adding, removing, or
    reordering assemblies + components; toggling any optional field between value and `-`;
    indented table rows.

    Raises `ValueError` with a section-index and row-index locator on:
      - a heading that does not match `## <name> [<type>] (cost_code: <code>)`
      - a component row before any `## …` heading
      - a wrong-column-count table row
      - an unrecognized `component_type`
      - a blank required `component` cell
      - a non-numeric `quantity` or `unit_cost`
      - a duplicate assembly name
      - a mismatched table header row
    """
    sections = _split_into_sections(text)
    assemblies: list[Assembly] = []
    seen: set[str] = set()
    for i, (heading, body) in enumerate(sections, start=1):
        a = parse_assembly_section(i, heading, body)
        if a.name in seen:
            raise ValueError(
                f"assembly section {i}: duplicate assembly name {a.name!r}"
            )
        seen.add(a.name)
        assemblies.append(a)
    return CanonicalAssemblyLibrary(assemblies=assemblies)


def parse_assembly_section(section_index: int, heading: str, body_lines: list[str]) -> Assembly:
    m = _HEADING_RE.match(heading.strip())
    if not m:
        raise ValueError(
            f"assembly section {section_index}: heading {heading.strip()!r} does not match "
            f"'## <name> [<type>] (cost_code: <code>)'"
        )
    name = m.group("name")
    assembly_type = m.group("type")
    code_raw = m.group("code")
    cost_code = None if code_raw == "-" else code_raw

    description = ""
    table_lines: list[str] = []
    for raw in body_lines:
        line = raw.lstrip()
        if not line:
            continue
        if line.startswith(">"):
            description = _unescape_string_field(line[1:].lstrip())
            continue
        if line.startswith("|"):
            table_lines.append(line)
    components = _parse_component_table(name, table_lines)
    return Assembly(
        name=name,
        assembly_type=assembly_type,
        cost_code=cost_code,
        description=description,
        components=components,
    )


def library_diagnostics(library: CanonicalAssemblyLibrary) -> list[str]:
    """Non-fatal observations after `parse`. Returns an empty list on a healthy library."""
    out: list[str] = []
    for a in library.assemblies:
        if not a.components:
            out.append(f"assembly {a.name!r} has 0 components")
    return out


# ---------- parse internals ----------

def _split_into_sections(text: str) -> list[tuple[str, list[str]]]:
    """Split `text` into `(heading, body_lines)` pairs, one per `##` heading. Content
    before the first `##` that includes a table row is an error; blank content is ignored."""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for raw in text.splitlines():
        line = raw.lstrip()
        if line.startswith("## "):
            if current is not None:
                sections.append(current)
            current = (line.rstrip(), [])
        elif current is None:
            if line.startswith("|"):
                raise ValueError("component table before first '## …' heading")
            # otherwise: ignore stray text before the first heading (blank lines, prose).
        else:
            current[1].append(raw)
    if current is not None:
        sections.append(current)
    return sections


def _parse_component_table(assembly_name: str, table_lines: list[str]) -> list[Component]:
    if not table_lines:
        return []
    rows = [split_pipes(_strip_row_bars(ln)) for ln in table_lines]
    header_cells = tuple(_unescape(c).strip() for c in rows[0])
    if header_cells != _COMPONENT_TABLE_HEADERS:
        raise ValueError(
            f"assembly {assembly_name!r} — table header does not match "
            f"'{' | '.join(_COMPONENT_TABLE_HEADERS)}'"
        )
    components: list[Component] = []
    body_row_index = 0
    for row in rows[1:]:
        cells = [_unescape(c).strip() for c in row]
        if all(_is_separator(c) for c in cells):
            continue
        body_row_index += 1
        if len(cells) != len(_COMPONENT_TABLE_HEADERS):
            raise ValueError(
                f"assembly {assembly_name!r} row {body_row_index}: expected "
                f"{len(_COMPONENT_TABLE_HEADERS)} columns, got {len(cells)}"
            )
        # Unescape JSON-encoded string fields; numerics do not use JSON encoding.
        try:
            component_type = _unescape_string_field(cells[0])
            name = _unescape_string_field(cells[1])
        except ValueError as e:
            raise ValueError(
                f"assembly {assembly_name!r} row {body_row_index}: cell contains invalid "
                f"escape sequence ({e})"
            )
        qty, unit, uc, rref, trade, desc = (
            cells[2], cells[3], cells[4], cells[5], cells[6], cells[7],
        )
        if component_type not in VALID_COMPONENT_TYPES:
            raise ValueError(
                f"assembly {assembly_name!r} row {body_row_index}: unrecognized "
                f"component_type {component_type!r}"
            )
        if not name or name == "-":
            raise ValueError(
                f"assembly {assembly_name!r} row {body_row_index}: 'component' is required"
            )
        try:
            quantity = float(qty)
        except ValueError:
            raise ValueError(
                f"assembly {assembly_name!r} row {body_row_index}: 'quantity' expected a "
                f"number, got {qty!r}"
            )
        if uc in ("-", ""):
            unit_cost: float | None = None
        else:
            try:
                unit_cost = float(uc)
            except ValueError:
                raise ValueError(
                    f"assembly {assembly_name!r} row {body_row_index}: 'unit_cost' "
                    f"expected a number, got {uc!r}"
                )
        try:
            unit_val = "" if unit in ("-", "") else _unescape_string_field(unit)
            rref_val = None if rref in ("-", "") else _unescape_string_field(rref)
            trade_val = "" if trade in ("-", "") else _unescape_string_field(trade)
            desc_val = "" if desc in ("-", "") else _unescape_string_field(desc)
        except ValueError as e:
            raise ValueError(
                f"assembly {assembly_name!r} row {body_row_index}: cell contains invalid "
                f"escape sequence ({e})"
            )
        components.append(Component(
            component_type=component_type,
            name=name,
            quantity=quantity,
            unit=unit_val,
            unit_cost=unit_cost,
            rate_ref=rref_val,
            trade=trade_val,
            description=desc_val,
        ))
    return components


def _strip_row_bars(line: str) -> str:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return s


def _unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def _is_separator(cell: str) -> bool:
    stripped = cell.strip()
    return stripped != "" and set(stripped) <= {"-", ":"}


# ---------- single-assembly artifact (Phase 2b) ----------

# `render_single` is a re-export alias: single-assembly render emits the same body a
# library section would (optional `> description` + components table), without the `##`
# library heading. The caller frames the section however they like.
render_single = render_assembly


def parse_single(text: str) -> Assembly:
    """Parse a single assembly from `text`, which must contain exactly one `##` heading.

    Round-trip:
        parse_single(render(CanonicalAssemblyLibrary(assemblies=[a]))) == a
    for any assembly `a` that survives `render` (heading-char validation).

    Raises `ValueError` if `text` contains zero or more than one `##` heading, or if
    the heading / body is otherwise malformed (via the underlying `parse_assembly_section`
    error paths — same section+row locators as `parse`).
    """
    # Pre-count `##` headings so a body-only input (which _split_into_sections would
    # reject with "table before first heading") reports the semantic "exactly one" error.
    heading_count = sum(
        1 for line in text.splitlines() if line.lstrip().startswith("## ")
    )
    if heading_count != 1:
        raise ValueError(
            f"parse_single expected exactly one '##' heading, found {heading_count}"
        )
    sections = _split_into_sections(text)
    heading, body = sections[0]
    return parse_assembly_section(1, heading, body)


def parse_single_with_meta(
    text: str,
    *,
    name: str,
    assembly_type: str,
    cost_code: str | None = None,
) -> Assembly:
    """Parse a single assembly from `text` using caller-supplied meta.

    The `text` may be the body-only form (from `render_single`) OR a full library
    section (with a `##` heading); the heading is IGNORED — the caller's `name`,
    `assembly_type`, and `cost_code` are authoritative. This is the default entry point
    for `build-assemblies`, where the meta comes from the estimate item.

    The body's `> description` line (if present) still populates
    `Assembly.description`; component rows still populate `Assembly.components` via
    the shared `_parse_component_table` path with the same locator-bearing errors.
    """
    description = ""
    table_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.lstrip()
        if not line:
            continue
        if line.startswith("##"):
            continue                                              # caller's meta wins
        if line.startswith(">"):
            description = _unescape_string_field(line[1:].lstrip())
            continue
        if line.startswith("|"):
            table_lines.append(line)
    components = _parse_component_table(name, table_lines)
    return Assembly(
        name=name,
        assembly_type=assembly_type,
        cost_code=cost_code,
        description=description,
        components=components,
    )


# ---------- ComponentDiff (Phase 2b) ----------


@dataclass(frozen=True)
class ComponentDiff:
    """The result of comparing an assembly's components before and after a user edit.

    Match key is `(component_type, name)`. Entries in `to_update` are `(original, edited)`
    pairs — the caller sees both sides so it can log or route the update.
    """
    to_create: tuple[Component, ...]
    to_update: tuple[tuple[Component, Component], ...]
    to_delete: tuple[Component, ...]


def diff_components(
    original: list[Component],
    edited: list[Component],
) -> ComponentDiff:
    """Compute the create / update / delete plan to turn `original` into `edited`.

    Matching is on the `(component_type, name)` key — order-independent. If either list
    contains duplicate keys, the LAST occurrence for each key wins (documented
    limitation; the artifact does not enforce component uniqueness within an assembly).

    Returns a `ComponentDiff` with `to_create`, `to_update`, and `to_delete` in stable
    order:
      - `to_create`: entries in `edited`'s dict order, filtered to keys not in `original`.
      - `to_delete`: entries in `original`'s dict order, filtered to keys not in `edited`.
      - `to_update`: entries in `original`'s dict order, filtered to keys in both where
        the two `Component` dataclasses are not equal.
    """
    original_by_key = {(c.component_type, c.name): c for c in original}
    edited_by_key = {(c.component_type, c.name): c for c in edited}
    to_create = tuple(c for k, c in edited_by_key.items() if k not in original_by_key)
    to_delete = tuple(c for k, c in original_by_key.items() if k not in edited_by_key)
    to_update = tuple(
        (original_by_key[k], edited_by_key[k])
        for k in original_by_key
        if k in edited_by_key and original_by_key[k] != edited_by_key[k]
    )
    return ComponentDiff(to_create=to_create, to_update=to_update, to_delete=to_delete)
