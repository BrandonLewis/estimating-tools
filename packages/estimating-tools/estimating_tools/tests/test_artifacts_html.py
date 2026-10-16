"""Tests for artifacts_html: render-grammar parsing, serialization fidelity, HTML page."""
import json
import re

import pytest

from estimating_tools.artifacts_html import (
    _computed_columns,
    _parse_blocks,
    _serialize_row,
    _split_row,
)

MAPPING_MD = (
    "<!-- editable — set column to '-' to skip a field -->\n"
    "| Canonical field | Spreadsheet column | Sample values |\n"
    "| --- | --- | --- |\n"
    "| item_number* | Item | 1; 2; 3 |\n"
    "| unit_price | - |  |"
)

ASSEMBLY_MD = (
    "> Form + pour crew\n"
    "\n"
    "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "| labor | Foreman | 1 | hr | 95.00 | FORE | FORE | - |\n"
    "| material | Pipe 12\\| elbow | 5 | CY | 210.00 | - | - | - |"
)

PUSH_MD = (
    "# Push plan\n"
    "\n"
    "1 schedule, 2 templates, 2 items.\n"
    "\n"
    "## Schedules\n"
    "\n"
    "| name | display_order |\n"
    "| --- | --- |\n"
    "| Base Bid | 0 |\n"
    "\n"
    "Confirm to write to BidSheet.ai."
)

SPREAD_MD = (
    "| Item | Description | Unit | Qty | Ace* | Build |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
    "| 6 (Base Bid) | MULCH | SQYD | 8800 | **1.20** | 1.38 |\n"
    "\n"
    "Best-of-breed total: 78540.00\n"
    "\n"
    "Gaps:\n"
    "- BuildRight: item 21 — excluded (Outside scope)"
)

ALL_FIXTURES = [MAPPING_MD, ASSEMBLY_MD, PUSH_MD, SPREAD_MD]

HOSTILE_MD = (
    "| a | b |\n"
    "| --- | --- |\n"
    "| __PAYLOAD__ | <img src=x onerror=alert(1)> |\n"
    "| <!--<script> | __EDITABLE__ |"
)


def test_split_row_inverts_md_table_format():
    assert _split_row("| a | b |") == ["a", "b"]
    assert _split_row("| a |  |") == ["a", ""]
    assert _split_row("| Pipe 12\\| elbow | 5 |") == ["Pipe 12| elbow", "5"]
    assert _split_row("| MULCH  | x |") == ["MULCH ", "x"]   # trailing space preserved
    with pytest.raises(ValueError):
        _split_row("not a row")


def test_serialize_row_matches_md_table_format():
    assert _serialize_row(["a", "b"]) == "| a | b |"
    assert _serialize_row(["a", ""]) == "| a |  |"
    assert _serialize_row(["Pipe 12| elbow", "5"]) == "| Pipe 12\\| elbow | 5 |"
    assert _serialize_row(["MULCH ", "x"]) == "| MULCH  | x |"


def test_parse_blocks_kinds_and_order():
    kinds = [b.kind for b in _parse_blocks(PUSH_MD)]
    assert kinds == ["heading", "para", "heading", "table", "para"]
    kinds = [b.kind for b in _parse_blocks(MAPPING_MD)]
    assert kinds == ["comment", "table"]
    kinds = [b.kind for b in _parse_blocks(ASSEMBLY_MD)]
    assert kinds == ["quote", "table"]
    kinds = [b.kind for b in _parse_blocks(SPREAD_MD)]
    assert kinds == ["table", "para", "para", "bullets"]


def test_parse_blocks_table_content_and_range():
    table = [b for b in _parse_blocks(PUSH_MD) if b.kind == "table"][0]
    assert table.header == ["name", "display_order"]
    assert table.rows == [["Base Bid", "0"]]
    lines = PUSH_MD.split("\n")
    assert lines[table.start].startswith("| name")
    assert lines[table.end - 1].startswith("| Base Bid")


def test_parse_rejects_malformed_tables():
    with pytest.raises(ValueError, match="separator"):
        _parse_blocks("| a | b |\n| 1 | 2 |")  # second line is not a separator
    with pytest.raises(ValueError, match="width"):
        _parse_blocks("| a | b |\n| --- | --- |\n| only-one |")
    with pytest.raises(ValueError, match="separator"):
        _parse_blocks("| a | b |")  # lone header line
    with pytest.raises(ValueError, match="separator"):
        # a dash-placeholder row is NOT a separator (md_table emits exactly '---')
        _parse_blocks("| a | b |\n| - | - |\n| 1 | 2 |")


def test_dash_placeholder_body_row_is_data_not_separator():
    table = [
        b
        for b in _parse_blocks("| a | b |\n| --- | --- |\n| - | - |\n| 1 | 2 |")
        if b.kind == "table"
    ][0]
    assert table.rows == [["-", "-"], ["1", "2"]]


def test_table_body_reserialization_is_byte_identical():
    """The export invariant: re-serializing parsed body rows reproduces the original
    body lines exactly (header/separator lines are reused verbatim by the exporter)."""
    for md in ALL_FIXTURES:
        lines = md.split("\n")
        for b in _parse_blocks(md):
            if b.kind != "table":
                continue
            regenerated = [_serialize_row(r) for r in b.rows]
            assert regenerated == lines[b.start + 2 : b.end]


def test_computed_columns_detection():
    assembly_table = [b for b in _parse_blocks(ASSEMBLY_MD) if b.kind == "table"][0]
    assert _computed_columns(assembly_table.header) == (2, 4)  # quantity, unit_cost
    mapping_table = [b for b in _parse_blocks(MAPPING_MD) if b.kind == "table"][0]
    assert _computed_columns(mapping_table.header) is None
    spread_table = [b for b in _parse_blocks(SPREAD_MD) if b.kind == "table"][0]
    assert _computed_columns(spread_table.header) is None  # Qty but no unit_cost/price


from estimating_tools.artifacts_html import to_editable_html


def _payload(html_page: str) -> dict:
    m = re.search(
        r'<script type="application/json" id="doc">(.*?)</script>', html_page, re.S
    )
    assert m, "payload script tag missing"
    return json.loads(m.group(1))


def test_page_is_self_contained_and_escaped():
    page = to_editable_html(ASSEMBLY_MD, title="Assembly <review> & edit")
    assert page.startswith("<!doctype html>")
    assert "Assembly &lt;review&gt; &amp; edit" in page
    assert "Pipe 12| elbow" in page  # cell text present (innerText form, HTML-escaped source)
    assert not re.search(r'\bsrc=|href=|@import|http://|https://', page)


def test_editable_mode_affordances():
    page = to_editable_html(ASSEMBLY_MD, title="t")
    assert "Copy edited artifact" in page
    assert 'contenteditable="true"' in page
    assert 'class="add"' in page
    readonly = to_editable_html(ASSEMBLY_MD, title="t", editable=False)
    assert "Copy edited artifact" not in readonly
    assert 'contenteditable="true"' not in readonly
    assert 'class="add"' not in readonly


def test_extension_column_only_when_qty_and_cost_present():
    page = to_editable_html(ASSEMBLY_MD, title="t")
    assert "display only" in page
    page = to_editable_html(MAPPING_MD, title="t")
    assert "display only" not in page


def test_payload_carries_lines_and_table_ranges():
    page = to_editable_html(PUSH_MD, title="t")
    doc = _payload(page)
    assert doc["lines"] == PUSH_MD.split("\n")
    assert len(doc["tables"]) == 1
    t = doc["tables"][0]
    assert (t["t"], t["width"], t["computed"]) == (0, 2, None)
    assert PUSH_MD.split("\n")[t["start"]].startswith("| name")


def test_payload_computed_and_script_safety():
    page = to_editable_html(ASSEMBLY_MD, title="t")
    doc = _payload(page)
    assert doc["tables"][0]["computed"] == [2, 4]
    m = re.search(
        r'<script type="application/json" id="doc">(.*?)</script>', page, re.S
    )
    assert "<" not in m.group(1)  # no raw '<' in the JSON block — tag close impossible


def test_all_fixture_cells_present_in_page():
    for md in ALL_FIXTURES:
        page = to_editable_html(md, title="t")
        for b in _parse_blocks(md):
            if b.kind == "table":
                for row in b.rows:
                    for cell in row:
                        if cell:
                            assert _html_escape(cell) in page


def test_hostile_content_cannot_break_out_of_the_page():
    page = to_editable_html(HOSTILE_MD, title="__BODY__ <script>")
    assert "<img src=x" not in page                       # body path escaped
    assert page.count("<script>") == 1                    # only the app script opens raw
    doc = _payload(page)
    assert doc["lines"] == HOSTILE_MD.split("\n")         # payload survives byte-exact


def _html_escape(s: str) -> str:
    import html

    return html.escape(s, quote=True)


def _real_render_outputs():
    """Real render outputs from the two cheapest-to-construct renderers."""
    from estimating_tools.assemblies.artifact import render_single
    from estimating_tools.assemblies.model import Assembly, Component
    from estimating_tools.importers.mapping_artifact import propose_mapping, render

    pm = propose_mapping(
        ["item_number", "description", "unit_price"],
        ["item_number", "description"],
        ["Item", "Description", "Price"],
        [{"Item": "1", "Description": "LEAD PLAN", "Price": "6000"}],
    )
    assembly = Assembly(
        name="Headwall Form & Pour",
        assembly_type="CREW",
        cost_code="510092",
        description="Form + pour crew",
        components=[
            Component(
                component_type="labor", name="Foreman", quantity=1.0, unit="hr",
                unit_cost=95.0, rate_ref="FORE", trade="FORE", description="",
            ),
            Component(
                component_type="material", name="3600psi concrete", quantity=5.0,
                unit="CY", unit_cost=210.0, rate_ref=None, trade="", description="",
            ),
        ],
    )
    return [render(pm), render_single(assembly)]


def test_real_renderers_fit_the_grammar_and_roundtrip():
    for md in _real_render_outputs():
        blocks = _parse_blocks(md)                       # must not raise
        assert any(b.kind == "table" for b in blocks)
        lines = md.split("\n")
        for b in blocks:
            if b.kind == "table":
                assert [_serialize_row(r) for r in b.rows] == lines[b.start + 2 : b.end]
        page = to_editable_html(md, title="t")           # must not raise
        assert '<script type="application/json" id="doc">' in page


def test_build_payload_shape_and_body_reuse():
    from estimating_tools.artifacts_html import build_payload, to_editable_html

    # hostile markdown goes through the same seam the MCP App server uses
    for md in ALL_FIXTURES + [HOSTILE_MD]:
        p = build_payload(md, editable=True)
        assert set(p) == {"lines", "tables", "body"}
        assert p["lines"] == md.split("\n")
        # the embedded page is built from the same payload: body appears verbatim,
        # and the embedded JSON carries exactly the same lines/tables
        page = to_editable_html(md, title="t")
        assert p["body"] in page
        embedded = _payload(page)
        assert embedded["lines"] == p["lines"]
        assert embedded["tables"] == p["tables"]


def test_build_payload_editable_flag_controls_affordances():
    from estimating_tools.artifacts_html import build_payload

    ed = build_payload(ASSEMBLY_MD, editable=True)["body"]
    ro = build_payload(ASSEMBLY_MD, editable=False)["body"]
    assert 'contenteditable="true"' in ed
    assert 'contenteditable="true"' not in ro
    assert 'class="add"' in ed and 'class="add"' not in ro
