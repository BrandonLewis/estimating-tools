"""Editable live artifact for estimate spec items — Phase 4a.

Per-item render/parse plus small orchestration helpers so a skill can address one item
within a whole spec file. See docs/superpowers/specs/2026-07-06-editable-live-artifacts-
phase4-estimate-item-design.md for the design.

Public surface:
    render_item(item: dict) -> str
    parse_item(text: str, *, item_no: str, pack=None) -> dict
    find_item(spec: dict, item_no: str) -> dict
    replace_item(spec: dict, item_no: str, new_item: dict) -> dict

Pure. No file IO, no MCP. Reuses `artifacts.md_table`, `artifact_common.split_pipes`,
`artifact_common.escape_string_field` / `unescape_string_field`. Schema validation via
`jsonschema` (already a dep of `estimating_tools`)."""
from __future__ import annotations

import jsonschema

from estimating_tools.artifact_common import (
    escape_string_field,
    split_pipes,
    unescape_string_field,
)
from estimating_tools.artifacts import md_table


# ---------- orchestration helpers ----------

def find_item(spec: dict, item_no: str) -> dict:
    """Return the item dict with matching `item_no` (identity, not a copy).

    Raises `KeyError` with a locator listing existing item_no values when missing."""
    for it in spec.get("items", []):
        if it.get("item_no") == item_no:
            return it
    existing = ", ".join(repr(it.get("item_no", "")) for it in spec.get("items", []))
    raise KeyError(f"item_no {item_no!r} not found; existing: {existing}")


def replace_item(spec: dict, item_no: str, new_item: dict) -> dict:
    """Return a new spec dict with the target item swapped for `new_item`.

    Other items are byte-identical to the input; item order is preserved.
    Raises `KeyError` when the target is missing. Does NOT mutate the input.

    Namespaced `x-*` item metadata (#257) is machine-managed and never surfaced
    in the editable artifact, so `render_item -> parse_item` drops it. Any `x-`
    key the existing item carries that `new_item` does not set is carried
    forward, so a render/parse/replace round trip preserves it (`new_item`'s own
    `x-*` still wins). A blanket merge is deliberately avoided — it would
    resurrect editable sections the user removed in the artifact."""
    items = spec.get("items", [])
    for i, it in enumerate(items):
        if it.get("item_no") == item_no:
            merged = dict(new_item)
            for key, value in it.items():
                if key.startswith("x-") and key not in merged:
                    merged[key] = value
            new_items = list(items)
            new_items[i] = merged
            return {**spec, "items": new_items}
    existing = ", ".join(repr(it.get("item_no", "")) for it in items)
    raise KeyError(f"item_no {item_no!r} not found; existing: {existing}")


# ---------- render ----------

_METADATA_FIELDS = ("description", "recipe", "sheet", "qty", "uom")
_OPTIONAL_METADATA_FIELDS = ("wbs", "cost_code", "crew_id", "estimate_item_id")
_TAKEOFF_GEOMETRY_COLS = ("label", "length", "height", "ftg_cy", "ftg_cf", "wall_cy", "wall_cf")
_TAKEOFF_SUBCON_COLS = ("item", "qty", "uom", "unit_price")
_LABOR_SLOT_KV_KEYS = ("crew_factor", "driver", "uom", "note")
_CREW_COLS = ("trade", "count", "days")
_SPREADS_KV_KEYS = ("ftg_qty", "wall_qty", "ftg_waste", "wall_waste")
_MATERIALS_COLS = ("name", "qty", "uom", "unit_price")
_COST_DETAIL_COLS = ("name", "uom", "qty", "unit_price")


def _dash(value) -> str:
    """Render a string cell. `None` / empty → '-'; else escape and return.

    For md_table cells only — md_table adds the `|` -> `\\|` escape on top."""
    if value is None or value == "":
        return "-"
    return escape_string_field(str(value))


def _bullet_text(value) -> str:
    """Escape a bullet-body string. Unlike table cells, bullets aren't run through
    md_table, so `|` must be escaped here for full round-trip parity."""
    return escape_string_field(str(value)).replace("|", "\\|")


def _render_num_or_formula(value) -> str:
    """Render a schema `numOrFormula` cell. `None` → '-'; string starting with '=' →
    verbatim (via escape); numbers → `str(value)`."""
    if value is None:
        return "-"
    if isinstance(value, str):
        if value.startswith("="):
            return escape_string_field(value)
        raise TypeError(f"expected number-or-formula, got string {value!r}")
    if isinstance(value, (int, float)):
        return str(value)
    raise TypeError(f"expected number-or-formula, got {type(value).__name__}")


def _render_number(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return str(value)
    raise TypeError(f"expected number, got {type(value).__name__}")


def _render_metadata(item: dict) -> str:
    rows = []
    for field_name in _METADATA_FIELDS:
        if field_name == "qty":
            value = _render_num_or_formula(item.get("qty"))
        else:
            value = _dash(item.get(field_name))
        rows.append([field_name, value])
    # Optional Phase 4.5 metadata: emit a row only when the field is present AND has
    # a non-empty value. Emitting a "-" sentinel for None/"" would render fine but
    # parse back as absent, breaking round-trip for items that carry an explicit empty.
    for field_name in _OPTIONAL_METADATA_FIELDS:
        value = item.get(field_name)
        if value:
            rows.append([field_name, _dash(value)])
    return "## Metadata\n\n" + md_table(["field", "value"], rows)


def _render_notes(notes: list) -> str:
    if not notes:
        return "## Notes"
    body = "\n".join(f"- {_bullet_text(n)}" for n in notes)
    return "## Notes\n\n" + body


def _render_takeoff(takeoff: dict) -> str:
    kind = takeoff.get("kind")
    header = f"## Takeoff (kind: {kind})\n\n"
    if kind == "geometry":
        rows = []
        for ln in takeoff.get("lines", []):
            rows.append([
                _dash(ln.get("label")),
                _render_number(ln.get("length")),
                _render_number(ln.get("height")),
                _render_number(ln.get("ftg_cy")),
                _render_number(ln.get("ftg_cf")),
                _render_number(ln.get("wall_cy")),
                _render_number(ln.get("wall_cf")),
            ])
        return header + md_table(list(_TAKEOFF_GEOMETRY_COLS), rows)
    if kind == "subcontractor":
        parts = []
        for k in ("galvanize", "tax_rate", "freight"):
            if k in takeoff:
                if k == "galvanize":
                    parts.append(f"- {k}: {_render_num_or_formula(takeoff[k])}")
                else:
                    parts.append(f"- {k}: {_render_number(takeoff[k])}")
        rows = []
        for ln in takeoff.get("lines", []):
            rows.append([
                _dash(ln.get("item")),
                _render_num_or_formula(ln.get("qty")),
                _dash(ln.get("uom")),
                _render_number(ln.get("unit_price")),
            ])
        table = md_table(list(_TAKEOFF_SUBCON_COLS), rows)
        if parts:
            return header + "\n".join(parts) + "\n\n" + table
        return header + table
    raise ValueError(f"unknown takeoff kind {kind!r} (expected 'geometry' or 'subcontractor')")


def _render_labor_slot(slot: dict) -> str:
    letter = slot.get("slot", "")
    desc = escape_string_field(slot.get("description", ""))
    kv_bullets = []
    for k in _LABOR_SLOT_KV_KEYS:
        if k in slot:
            if k == "driver":
                kv_bullets.append(f"- {k}: {_render_num_or_formula(slot[k])}")
            elif k == "crew_factor":
                kv_bullets.append(f"- {k}: {_render_number(slot[k])}")
            else:
                kv_bullets.append(f"- {k}: {_dash(slot[k])}")
    activities_line = ""
    # Emit an `Activities:` line whenever the key is present (even for an empty list) so
    # the parse-side can distinguish `activities: []` from absent. Task 3 dropped empty
    # activities; several slots in sample-outfalls.estimate.yaml have `activities: []`
    # and the Phase 4 round-trip invariant requires preservation.
    if "activities" in slot:
        entries = ", ".join(
            f"{escape_string_field(a['name'])} ({a['factor']})" for a in slot["activities"]
        )
        activities_line = f"\nActivities: {entries}".rstrip()
    crew_rows = []
    for c in slot.get("crew", []):
        crew_rows.append([
            _dash(c.get("trade")),
            _dash(c.get("count")),
            _render_num_or_formula(c.get("days")),
        ])
    crew_table = "\nCrew:\n\n" + md_table(list(_CREW_COLS), crew_rows)
    header = f"### {letter}: {desc}"
    body = ""
    if kv_bullets:
        body += "\n\n" + "\n".join(kv_bullets)
    if activities_line:
        body += "\n" + activities_line
    body += "\n" + crew_table
    return header + body


def _render_labor(labor: list) -> str:
    if not labor:
        # Emit heading + trailing newline so the invariant `\n## Labor\n` holds
        # even when labor is empty and the section is last in the artifact.
        return "## Labor\n"
    slot_blocks = [_render_labor_slot(s) for s in labor]
    return "## Labor\n\n" + "\n\n".join(slot_blocks)


def _render_spreads(spreads: dict) -> str:
    kv_bullets = []
    for k in _SPREADS_KV_KEYS:
        if k in spreads:
            if k in ("ftg_qty", "wall_qty"):
                kv_bullets.append(f"- {k}: {_render_num_or_formula(spreads[k])}")
            else:
                kv_bullets.append(f"- {k}: {_render_number(spreads[k])}")
    parts = ["## Spreads"]
    if kv_bullets:
        parts.append("\n".join(kv_bullets))
    if "materials" in spreads:
        rows = []
        for m in spreads["materials"]:
            rows.append([
                _dash(m.get("name")),
                _render_num_or_formula(m.get("qty")),
                _dash(m.get("uom")),
                _render_number(m.get("unit_price")),
            ])
        parts.append("### Materials\n\n" + md_table(list(_MATERIALS_COLS), rows))
    return "\n\n".join(parts)


def _render_cost_details(cost_details: list) -> str:
    if not cost_details:
        return "## Cost details"
    blocks = []
    for cd in cost_details:
        name = cd["name"]
        marker = ""
        if "header_price" in cd:
            marker = f" (header_price: {cd['header_price']})"
        header = f"### {name}{marker}"
        rows = []
        for ln in cd.get("lines", []):
            rows.append([
                _dash(ln.get("name")),
                _dash(ln.get("uom")),
                _render_num_or_formula(ln.get("qty")),
                _render_number(ln.get("unit_price")),
            ])
        blocks.append(header + "\n\n" + md_table(list(_COST_DETAIL_COLS), rows))
    return "## Cost details\n\n" + "\n\n".join(blocks)


def render_item(item: dict, pack=None) -> str:
    """Render a single estimate item as a six-section artifact per the Phase 4 spec.

    Raises FormatPackError if the pack does not declare 'artifact' support."""
    from estimating_tools.estimate_spec.format_pack import bundled_pack, require_support

    require_support(pack or bundled_pack(), "artifact")
    parts: list[str] = [f"# {item['item_no']}"]
    parts.append(_render_metadata(item))
    if "notes" in item:
        parts.append(_render_notes(item["notes"]))
    if "takeoff" in item:
        parts.append(_render_takeoff(item["takeoff"]))
    parts.append(_render_labor(item.get("labor", [])))
    if "spreads" in item:
        parts.append(_render_spreads(item["spreads"]))
    if "cost_details" in item:
        parts.append(_render_cost_details(item["cost_details"]))
    return "\n\n".join(parts)


# ---------- parse ----------

_ITEM_SCHEMAS: dict[tuple, dict] = {}


def _item_schema(pack=None) -> dict:
    """The pack's item subschema for jsonschema.validate, with $defs embedded so
    internal $refs resolve. Cached per pack.key; safe on hot paths."""
    from estimating_tools.estimate_spec.format_pack import bundled_pack

    pack = pack or bundled_pack()
    cached = _ITEM_SCHEMAS.get(pack.key)
    if cached is None:
        root = pack.schema
        cached = _ITEM_SCHEMAS[pack.key] = {"$defs": root["$defs"], **root["$defs"]["item"]}
    return cached


def _valid_trades(pack=None) -> tuple[str, ...]:
    # Read from the schema rather than repeated here: the parser's own copy
    # drifted once already, rejecting the WELD, PILE and TEAM the schema had gained.
    return tuple(_item_schema(pack)["$defs"]["labor_block"]["properties"]
                 ["crew"]["items"]["properties"]["trade"]["enum"])


def _valid_recipes(pack=None) -> tuple[str, ...]:
    return tuple(_item_schema(pack)["properties"]["recipe"]["enum"])


def _valid_takeoff_kinds(pack=None) -> tuple[str, ...]:
    return tuple(_item_schema(pack)["$defs"]["takeoff"]["properties"]["kind"]["enum"])


def _valid_cost_detail_names(pack=None) -> tuple[str, ...]:
    return tuple(_item_schema(pack)["$defs"]["cost_detail"]["properties"]["name"]["enum"])


def parse_item(text: str, *, item_no: str, pack=None) -> dict:
    """Parse a single-item artifact text back into an item dict.

    Forces `item_no` to the caller's meta (ignores the `#` heading text). Runs
    `jsonschema.validate` against the item subschema before returning; violations surface
    as `ValueError` prefixed `schema violation:` with the JSON path. A pack that
    does not declare `supports: [artifact]` raises FormatPackError."""
    from estimating_tools.estimate_spec.format_pack import bundled_pack, require_support

    require_support(pack or bundled_pack(), "artifact")
    sections = _split_top_sections(text)
    result: dict = {"item_no": item_no}
    seen_headings: set[str] = set()

    for heading, body in sections:
        base = heading.split("(", 1)[0].strip()                   # 'Takeoff' out of '## Takeoff (kind: geometry)'
        if base in seen_headings:
            raise ValueError(f"duplicate top-level section {base!r}")
        seen_headings.add(base)

        if base == "Metadata":
            result.update(_parse_metadata(body, pack=pack))
        elif base == "Notes":
            result["notes"] = _parse_notes(body)
        elif base == "Takeoff":
            result["takeoff"] = _parse_takeoff(heading, body, pack=pack)
        elif base == "Labor":
            result["labor"] = _parse_labor(body, pack=pack)
        elif base == "Spreads":
            result["spreads"] = _parse_spreads(body)
        elif base == "Cost details":
            result["cost_details"] = _parse_cost_details(body, pack=pack)
        else:
            raise ValueError(
                f"section {base!r}: unknown heading (expected one of Metadata, Notes, "
                f"Takeoff, Labor, Spreads, Cost details)"
            )

    # Caller's meta wins.
    result["item_no"] = item_no

    try:
        jsonschema.validate(result, _item_schema(pack))
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(f"schema violation: {path}: {e.message}") from e

    return result


# ---------- section parsers ----------

def _split_top_sections(text: str) -> list[tuple[str, list[str]]]:
    """Split `text` into `(heading_after_##, body_lines)` pairs, one per `##` heading.

    The `# item_no` line is ignored (caller's meta wins). Content before the first `##`
    that isn't blank/heading-1 is a parse error."""
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("## "):
            if current is not None:
                sections.append(current)
            current = (stripped[3:].strip(), [])
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            continue                                              # item heading — ignored
        if current is None:
            if stripped.strip():
                raise ValueError("content before first '##' heading")
            continue
        current[1].append(raw)
    if current is not None:
        sections.append(current)
    return sections


def _parse_metadata(body: list[str], *, pack=None) -> dict:
    rows = _parse_table(body, expected_cols=("field", "value"), section="Metadata")
    out: dict = {}
    valid_recipes = _valid_recipes(pack)
    for i, row in enumerate(rows, start=1):
        field_name, value = row
        if field_name == "recipe":
            if value not in valid_recipes:
                raise ValueError(
                    f"section 'Metadata' row {i}: unrecognized recipe {value!r} "
                    f"(expected one of {list(valid_recipes)})"
                )
            out["recipe"] = value
        elif field_name == "qty":
            parsed = _parse_num_or_formula("Metadata", i, "qty", value, allow_dash=True)
            if parsed is not None:
                out["qty"] = parsed
        elif field_name in _METADATA_FIELDS + _OPTIONAL_METADATA_FIELDS:
            if value == "-" or not value:
                if field_name in ("description", "sheet", "uom"):
                    raise ValueError(
                        f"section 'Metadata' row {i}: {field_name!r} is required"
                    )
                continue
            if field_name == "estimate_item_id":
                try:
                    out[field_name] = int(value)
                except ValueError:
                    raise ValueError(
                        f"section 'Metadata' row {i}: estimate_item_id {value!r} "
                        f"is not an integer"
                    )
            else:
                out[field_name] = unescape_string_field(value)
        else:
            raise ValueError(
                f"section 'Metadata' row {i}: unknown field {field_name!r}"
            )
    return out


def _parse_notes(body: list[str]) -> list[str]:
    out: list[str] = []
    for raw in body:
        s = raw.lstrip()
        if not s:
            continue
        if s.startswith("- "):
            content = s[2:].rstrip("\r\n").rstrip()
            out.append(_text_from_bullet(content))
    return out


def _parse_takeoff(heading: str, body: list[str], *, pack=None) -> dict:
    if "(kind:" not in heading:
        raise ValueError(
            "section 'Takeoff': missing '(kind: geometry)' or '(kind: subcontractor)' "
            "marker"
        )
    kind = heading.split("(kind:", 1)[1].rstrip(")").strip()
    if kind not in _valid_takeoff_kinds(pack):
        raise ValueError(
            f"section 'Takeoff': unrecognized kind {kind!r} "
            f"(expected 'geometry' or 'subcontractor')"
        )
    if kind == "geometry":
        rows = _parse_table(body, expected_cols=_TAKEOFF_GEOMETRY_COLS, section="Takeoff")
        lines: list[dict] = []
        for i, row in enumerate(rows, start=1):
            label, length, height, ftg_cy, ftg_cf, wall_cy, wall_cf = row
            if not label or label == "-":
                raise ValueError(f"section 'Takeoff' row {i}: 'label' is required")
            entry: dict = {
                "label": unescape_string_field(label),
                "length": _parse_number("Takeoff", i, "length", length),
                "ftg_cy": _parse_number("Takeoff", i, "ftg_cy", ftg_cy),
                "wall_cy": _parse_number("Takeoff", i, "wall_cy", wall_cy),
                "wall_cf": _parse_number("Takeoff", i, "wall_cf", wall_cf),
            }
            if height != "-":
                entry["height"] = _parse_number("Takeoff", i, "height", height)
            if ftg_cf != "-":
                entry["ftg_cf"] = _parse_number("Takeoff", i, "ftg_cf", ftg_cf)
            lines.append(entry)
        return {"kind": "geometry", "lines": lines}
    # subcontractor
    out: dict = {"kind": "subcontractor"}
    _consume_kv_bullets(body, out, {
        "galvanize": "num_or_formula",
        "tax_rate":  "number",
        "freight":   "number",
    }, section="Takeoff")
    rows = _parse_table(body, expected_cols=_TAKEOFF_SUBCON_COLS, section="Takeoff")
    lines = []
    for i, row in enumerate(rows, start=1):
        item, qty, uom, unit_price = row
        if not item or item == "-":
            raise ValueError(f"section 'Takeoff' row {i}: 'item' is required")
        if uom == "-":
            raise ValueError(
                f"section 'Takeoff' row {i}: 'uom' is required"
            )
        lines.append({
            "item": unescape_string_field(item),
            "qty": _parse_num_or_formula("Takeoff", i, "qty", qty),
            "uom": unescape_string_field(uom),
            "unit_price": _parse_number("Takeoff", i, "unit_price", unit_price),
        })
    out["lines"] = lines
    return out


def _parse_labor(body: list[str], *, pack=None) -> list[dict]:
    """Body has one `### <letter>: <description>` sub-heading per slot with kv bullets +
    an optional Activities: line + Crew: header + trade/count/days table."""
    slots: list[dict] = []
    seen_letters: set[str] = set()
    for slot_heading, slot_body in _chunk_h3(body):
        if ":" not in slot_heading:
            raise ValueError(
                f"section 'Labor': slot heading {slot_heading!r} missing ':' "
                f"(expected '<LETTER>: <description>')"
            )
        letter, desc = slot_heading.split(":", 1)
        letter = letter.strip()
        desc = unescape_string_field(desc.strip())
        if letter in seen_letters:
            raise ValueError(f"duplicate labor slot {letter!r}")
        seen_letters.add(letter)
        slot: dict = {"slot": letter, "description": desc}
        _consume_kv_bullets(slot_body, slot, {
            "crew_factor": "number",
            "driver":      "num_or_formula",
            "uom":         "string",
            "note":        "string",
        }, section="Labor")
        # Activities: line — present iff the source had an `activities` key (even []).
        for raw in slot_body:
            s = raw.lstrip()
            if s.startswith("Activities:"):
                slot["activities"] = _parse_activities_line(s[len("Activities:"):])
                break
        # Crew: table
        crew_body: list[str] = []
        in_crew = False
        for raw in slot_body:
            s = raw.lstrip()
            if s.startswith("Crew:"):
                in_crew = True
                continue
            if in_crew:
                crew_body.append(raw)
        crew_rows = _parse_table(crew_body, expected_cols=_CREW_COLS,
                                 section=f"Labor slot {letter}")
        crew: list[dict] = []
        valid = _valid_trades(pack)
        for i, row in enumerate(crew_rows, start=1):
            trade, count, days = row
            if trade not in valid:
                raise ValueError(
                    f"section 'Labor' slot {letter} row {i}: unrecognized trade "
                    f"{trade!r} (expected one of {list(valid)})"
                )
            member: dict = {"trade": trade}
            if count != "-":
                try:
                    member["count"] = int(count)
                except ValueError:
                    raise ValueError(
                        f"section 'Labor' slot {letter} row {i}: 'count' expected an "
                        f"integer, got {count!r}"
                    )
            member["days"] = _parse_num_or_formula(
                f"Labor slot {letter}", i, "days", days,
            )
            crew.append(member)
        slot["crew"] = crew
        slots.append(slot)
    return slots


def _parse_spreads(body: list[str]) -> dict:
    out: dict = {}
    materials_body: list[str] | None = None
    top_body: list[str] = []
    current_target = top_body
    for raw in body:
        line = raw.lstrip()
        if line.startswith("### Materials"):
            materials_body = []
            current_target = materials_body
            continue
        current_target.append(raw)
    _consume_kv_bullets(top_body, out, {
        "ftg_qty":    "num_or_formula",
        "wall_qty":   "num_or_formula",
        "ftg_waste":  "number",
        "wall_waste": "number",
    }, section="Spreads")
    if materials_body is not None:
        rows = _parse_table(materials_body, expected_cols=_MATERIALS_COLS,
                            section="Spreads / Materials")
        materials: list[dict] = []
        for i, row in enumerate(rows, start=1):
            name, qty, uom, unit_price = row
            if not name or name == "-":
                raise ValueError(
                    f"section 'Spreads / Materials' row {i}: 'name' is required"
                )
            if uom == "-":
                raise ValueError(
                    f"section 'Spreads / Materials' row {i}: 'uom' is required"
                )
            materials.append({
                "name": unescape_string_field(name),
                "qty": _parse_num_or_formula("Spreads / Materials", i, "qty", qty),
                "uom": unescape_string_field(uom),
                "unit_price": _parse_number(
                    "Spreads / Materials", i, "unit_price", unit_price,
                ),
            })
        out["materials"] = materials
    return out


def _parse_cost_details(body: list[str], *, pack=None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    valid_names = _valid_cost_detail_names(pack)
    for heading_text, chunk_body in _chunk_h3(body):
        name = heading_text
        header_price = None
        if "(header_price:" in heading_text:
            name = heading_text.split("(header_price:", 1)[0].strip()
            hp_text = heading_text.split(
                "(header_price:", 1
            )[1].rstrip(")").strip()
            header_price = _parse_number("Cost details", 0, "header_price", hp_text)
        if name not in valid_names:
            raise ValueError(
                f"section 'Cost details': unrecognized name {name!r} "
                f"(expected one of {list(valid_names)})"
            )
        if name in seen:
            raise ValueError(f"duplicate cost-detail section {name!r}")
        seen.add(name)
        rows = _parse_table(chunk_body, expected_cols=_COST_DETAIL_COLS,
                            section=f"Cost details / {name}")
        lines: list[dict] = []
        for i, row in enumerate(rows, start=1):
            ln_name, uom, qty, unit_price = row
            if not ln_name or ln_name == "-":
                raise ValueError(
                    f"section 'Cost details / {name}' row {i}: 'name' is required"
                )
            entry: dict = {
                "name": unescape_string_field(ln_name),
                "qty": _parse_num_or_formula(
                    f"Cost details / {name}", i, "qty", qty,
                ),
                "unit_price": _parse_number(
                    f"Cost details / {name}", i, "unit_price", unit_price,
                ),
            }
            if uom != "-":
                entry["uom"] = unescape_string_field(uom)
            # Move name/uom to canonical order name, uom, qty, unit_price to match source.
            ordered: dict = {"name": entry["name"]}
            if "uom" in entry:
                ordered["uom"] = entry["uom"]
            ordered["qty"] = entry["qty"]
            ordered["unit_price"] = entry["unit_price"]
            lines.append(ordered)
        block: dict = {"name": name}
        if header_price is not None:
            block["header_price"] = header_price
        block["lines"] = lines
        out.append(block)
    return out


# ---------- parse internals ----------

def _chunk_h3(body: list[str]) -> list[tuple[str, list[str]]]:
    """Split `body` into `(heading_after_###, body_lines)` chunks."""
    chunks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for raw in body:
        stripped = raw.lstrip()
        if stripped.startswith("### "):
            if current is not None:
                chunks.append(current)
            current = (stripped[4:].strip(), [])
            continue
        if current is not None:
            current[1].append(raw)
    if current is not None:
        chunks.append(current)
    return chunks


def _parse_activities_line(text: str) -> list[dict]:
    """Parse `Set-up yard (1), Form (0.25)` into
    [{'name': 'Set-up yard', 'factor': 1}, {'name': 'Form', 'factor': 0.25}]."""
    text = text.strip()
    if not text:
        return []
    parts = _split_top_commas(text)
    out: list[dict] = []
    for i, part in enumerate(parts, start=1):
        part = part.strip()
        if not part.endswith(")") or "(" not in part:
            raise ValueError(
                f"section 'Labor': activities entry {i}: expected '<name> (<factor>)', "
                f"got {part!r}"
            )
        name = part[: part.rindex("(")].strip()
        factor_text = part[part.rindex("(") + 1: -1].strip()
        factor = _parse_number("Labor", i, "activities factor", factor_text)
        out.append({"name": unescape_string_field(name), "factor": factor})
    return out


def _split_top_commas(s: str) -> list[str]:
    """Split on `,` not enclosed by `()`."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _consume_kv_bullets(body: list[str], target: dict, keys: dict, *,
                        section: str) -> None:
    """Populate `target[k]` for each `- k: <value>` bullet in `body` whose key is in
    `keys`. `keys` values are one of `number`, `num_or_formula`, `string`."""
    for raw in body:
        s = raw.lstrip()
        if not s.startswith("- "):
            continue
        rest = s[2:]
        if ":" not in rest:
            continue
        key, value = rest.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key not in keys:
            continue
        kind = keys[key]
        if kind == "string":
            # `-` on a string field means empty string (renderer emits `-` via _dash for
            # both absent and empty-string source values; absent isn't rendered at all,
            # so any `-` reaching parse came from an explicit empty string).
            target[key] = "" if value == "-" else _text_from_bullet(value)
            continue
        if value == "-":
            continue
        if kind == "number":
            target[key] = _parse_number(section, 0, key, value)
        elif kind == "num_or_formula":
            target[key] = _parse_num_or_formula(section, 0, key, value)


def _parse_table(body: list[str], *, expected_cols: tuple[str, ...],
                 section: str) -> list[list[str]]:
    """Extract a markdown pipe table from `body`.

    Cells are unwrapped via `[1:-1]` when padded with the ` | ` md_table format so
    intentional leading/trailing whitespace inside data survives the round-trip. Each
    cell is pipe-unescaped (`\\|` -> `|`) before being returned; JSON-unescape (for
    newlines etc.) is left to the caller so numeric cells aren't fed through
    `json.loads`."""
    header_seen = False
    rows: list[list[str]] = []
    for raw in body:
        line = raw.lstrip()
        if not line.startswith("|"):
            continue
        raw_cells = split_pipes(_strip_row_bars(line))
        cells = [_cell_content(c).replace("\\|", "|") for c in raw_cells]
        if not header_seen:
            if tuple(cells) == expected_cols:
                header_seen = True
                continue
            raise ValueError(
                f"section {section!r}: table header {cells!r} does not match expected "
                f"{list(expected_cols)}"
            )
        if all(c and set(c) <= {"-", ":"} for c in cells):        # separator row
            continue
        if len(cells) != len(expected_cols):
            raise ValueError(
                f"section {section!r} row {len(rows) + 1}: expected "
                f"{len(expected_cols)} columns, got {len(cells)}"
            )
        rows.append(cells)
    return rows


def _strip_row_bars(line: str) -> str:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return s


def _cell_content(cell: str) -> str:
    """Undo md_table's single-space padding around each cell. Falls back to strip()
    when the cell isn't space-padded (user-edited rows). Trailing/leading whitespace
    INSIDE the data survives — that matters for e.g. sheet names like `# 1 - MOB `."""
    if cell.startswith(" ") and cell.endswith(" "):
        return cell[1:-1]
    return cell.strip()


def _text_from_bullet(value: str) -> str:
    """Pipe-unescape then JSON-unescape a string extracted from a bullet body."""
    return unescape_string_field(value.replace("\\|", "|"))


def _parse_num_or_formula(section: str, row_index: int, field_name: str,
                          value: str, *, allow_dash: bool = True):
    v = value.strip()
    if allow_dash and v == "-":
        return None
    if v.startswith("="):
        return unescape_string_field(v)
    try:
        f = float(v)
    except ValueError:
        loc = f" row {row_index}" if row_index else ""
        raise ValueError(
            f"section {section!r}{loc}: {field_name!r} expected a number or formula, "
            f"got {v!r}"
        )
    if f.is_integer() and "." not in v and "e" not in v.lower():
        return int(f)
    return f


def _parse_number(section: str, row_index: int, field_name: str, value: str):
    v = value.strip()
    if v == "-":
        return None
    try:
        f = float(v)
    except ValueError:
        loc = f" row {row_index}" if row_index else ""
        raise ValueError(
            f"section {section!r}{loc}: {field_name!r} expected a number, got {v!r}"
        )
    if f.is_integer() and "." not in v and "e" not in v.lower():
        return int(f)
    return f
