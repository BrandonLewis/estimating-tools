from estimating_tools.assemblies.artifact import render, render_assembly
from estimating_tools.assemblies.model import Assembly, CanonicalAssemblyLibrary, Component


def _a(name="Manhole Base", assembly_type="structural", cost_code="03-3000",
       description="", components=()):
    return Assembly(name=name, assembly_type=assembly_type, cost_code=cost_code,
                    description=description, components=list(components))


def _c(component_type="labor", name="Carpenter", quantity=4.0, unit="HR",
       unit_cost=None, rate_ref="carpenter_base", trade="", description=""):
    return Component(component_type=component_type, name=name, quantity=quantity,
                     unit=unit, unit_cost=unit_cost, rate_ref=rate_ref, trade=trade,
                     description=description)


def test_render_empty_library_is_empty_string():
    assert render(CanonicalAssemblyLibrary(assemblies=[])) == ""


def test_render_single_assembly_single_component():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[_c()])])
    out = render(lib)
    assert out.startswith("## Manhole Base [structural] (cost_code: 03-3000)\n\n")
    assert "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |" in out
    assert "| --- | --- | --- | --- | --- | --- | --- | --- |" in out
    assert "| labor | Carpenter | 4 | HR | - | carpenter_base | - | - |" in out
    assert not out.endswith("\n")                                # matches md_table contract


def test_render_description_is_blockquote_after_heading():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(description="48in precast base",
                                                  components=[_c()])])
    out = render(lib)
    assert "\n\n> 48in precast base\n\n" in out                  # blockquote is its own paragraph


def test_render_omits_blockquote_when_description_empty():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(description="", components=[_c()])])
    out = render(lib)
    assert "> " not in out


def test_render_cost_code_dash_when_none():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(cost_code=None, components=[_c()])])
    assert "(cost_code: -)" in render(lib)


def test_render_assembly_type_empty_renders_bracket_pair():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(assembly_type="", components=[_c()])])
    assert "[]" in render(lib)


def test_render_component_optional_fields_use_dash_sentinel():
    comp = _c(unit_cost=175.0, unit="CY", rate_ref=None, trade="", description="4000 psi")
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[comp])])
    out = render(lib)
    assert "| labor | Carpenter | 4 | CY | 175.00 | - | - | 4000 psi |" in out


def test_render_multi_assembly_sections_separated_by_blank_line():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(name="Manhole Base", components=[_c()]),
        _a(name="Manhole Riser", components=[_c(quantity=3.0)]),
    ])
    out = render(lib)
    # Section boundary is exactly one blank line between sections' last content and next heading.
    assert "\n\n## Manhole Riser [" in out


def test_render_pipe_in_assembly_name_is_escaped_via_md_table_only_in_components():
    # Assembly headings render outside md_table — the `|` in a name would break the parse
    # regex if it appeared there. This test documents that we intentionally don't escape in
    # headings (real construction assembly names don't contain `|`); pipes in COMPONENT
    # cells ARE escaped by md_table and round-trip through Task 3's parse.
    comp = _c(description="left|right")
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[comp])])
    out = render(lib)
    assert "left\\|right" in out                                 # md_table escape survives


# =====================================================================================
# Parse-side tests
# =====================================================================================
import pytest

from estimating_tools.assemblies.artifact import (
    library_diagnostics, parse, parse_assembly_section,
)


# ---------- round-trip ----------

def test_parse_roundtrip_single_assembly():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[_c(), _c(
        component_type="material", name="Concrete", quantity=2.0, unit="CY",
        unit_cost=175.0, rate_ref=None, trade="", description="4000 psi",
    )])])
    assert parse(render(lib)) == lib


def test_parse_roundtrip_multi_assembly():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(name="Manhole Base", cost_code="03-3000", description="48in precast",
           components=[_c()]),
        _a(name="Manhole Riser", cost_code=None,
           components=[_c(component_type="material", name="Concrete", quantity=1.5,
                          unit="CY", unit_cost=175.0, rate_ref=None)]),
    ])
    assert parse(render(lib)) == lib


def test_parse_roundtrip_empty_library():
    lib = CanonicalAssemblyLibrary(assemblies=[])
    assert parse(render(lib)) == lib


def test_parse_roundtrip_assembly_with_zero_components():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[])])
    assert parse(render(lib)) == lib


def test_parse_roundtrip_pipe_in_component_description():
    comp = _c(description="left|right")
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[comp])])
    assert parse(render(lib)) == lib


# ---------- user edits ----------

def test_parse_user_renames_assembly_in_heading():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(name="Manhole Base", components=[_c()])])
    edited = render(lib).replace("## Manhole Base", "## Manhole Foundation")
    assert parse(edited).assemblies[0].name == "Manhole Foundation"


def test_parse_user_changes_cost_code_to_dash():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(cost_code="03-3000", components=[_c()])])
    edited = render(lib).replace("(cost_code: 03-3000)", "(cost_code: -)")
    assert parse(edited).assemblies[0].cost_code is None


def test_parse_user_adds_component_row():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[_c()])])
    text = render(lib)
    new_row = "| material | Rebar | 20 | LB | 1.25 | - | - | #4 |"
    edited = text + "\n" + new_row
    parsed = parse(edited)
    assert len(parsed.assemblies[0].components) == 2
    added = parsed.assemblies[0].components[1]
    assert added.component_type == "material"
    assert added.name == "Rebar"
    assert added.unit_cost == 1.25
    assert added.description == "#4"


def test_parse_user_removes_component_row():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[
        _c(),
        _c(component_type="material", name="Concrete", quantity=2.0, unit="CY",
           unit_cost=175.0, rate_ref=None),
    ])])
    text = render(lib)
    edited = "\n".join(ln for ln in text.splitlines() if "Concrete" not in ln)
    parsed = parse(edited)
    assert [c.name for c in parsed.assemblies[0].components] == ["Carpenter"]


def test_parse_user_deletes_whole_assembly_section():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(name="Manhole Base", components=[_c()]),
        _a(name="Manhole Riser", components=[_c(quantity=3.0)]),
    ])
    text = render(lib)
    # Drop everything from '## Manhole Riser' onwards.
    edited = text.split("\n\n## Manhole Riser")[0]
    parsed = parse(edited)
    assert [a.name for a in parsed.assemblies] == ["Manhole Base"]


def test_parse_user_reorders_assemblies_via_edit():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(name="A", components=[_c()]),
        _a(name="B", components=[_c()]),
    ])
    text = render(lib)
    parts = text.split("\n\n## B ")
    assert len(parts) == 2                                       # sanity
    edited = "## B " + parts[1] + "\n\n" + parts[0]
    parsed = parse(edited)
    assert [a.name for a in parsed.assemblies] == ["B", "A"]


def test_parse_tolerates_indented_table():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[_c()])])
    text = render(lib)
    indented = "\n".join("  " + ln if ln.startswith("|") else ln for ln in text.splitlines())
    assert parse(indented) == lib


# ---------- malformed ----------

def test_parse_raises_on_malformed_heading():
    text = "## Manhole Base structural cost_code: 03-3000\n\n"
    with pytest.raises(ValueError, match="section 1"):
        parse(text)


def test_parse_raises_on_component_row_before_first_heading():
    text = (
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | Carpenter | 4 | HR | - | carpenter_base | - | - |\n"
    )
    with pytest.raises(ValueError, match="before first"):
        parse(text)


def test_parse_raises_on_wrong_column_count():
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | Carpenter | 4 | HR |\n"
    )
    with pytest.raises(ValueError, match=r"row 1: expected 8 columns"):
        parse(text)


def test_parse_raises_on_unrecognized_component_type():
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| lab | Carpenter | 4 | HR | - | - | - | - |\n"
    )
    with pytest.raises(ValueError, match="unrecognized component_type 'lab'"):
        parse(text)


def test_parse_raises_on_blank_required_component_cell():
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | - | 4 | HR | - | - | - | - |\n"
    )
    with pytest.raises(ValueError, match="'component' is required"):
        parse(text)


def test_parse_raises_on_non_numeric_quantity():
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | Carpenter | TBD | HR | - | - | - | - |\n"
    )
    with pytest.raises(ValueError, match=r"'quantity' expected a number, got 'TBD'"):
        parse(text)


def test_parse_raises_on_duplicate_assembly_name():
    text = render(CanonicalAssemblyLibrary(assemblies=[
        _a(name="Manhole Base", components=[_c()]),
        _a(name="Manhole Base", components=[_c()]),
    ]))
    with pytest.raises(ValueError, match="duplicate assembly name 'Manhole Base'"):
        parse(text)


def test_parse_raises_on_missing_table_header():
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| type | name | qty | unit | cost | ref | trade | desc |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | Carpenter | 4 | HR | - | - | - | - |\n"
    )
    with pytest.raises(ValueError, match="table header does not match"):
        parse(text)


# ---------- library_diagnostics ----------

def test_library_diagnostics_flags_empty_assemblies():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(name="Empty", components=[])])
    diags = library_diagnostics(lib)
    assert any("Empty" in d and "0 components" in d for d in diags)


def test_library_diagnostics_empty_when_healthy():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[_c()])])
    assert library_diagnostics(lib) == []


# ---------- review-fix tests ----------

def test_roundtrip_component_description_with_newline():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[
        _c(description="first line\nsecond line"),
    ])])
    assert parse(render(lib)) == lib


def test_roundtrip_assembly_description_with_newline():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(description="first line\nsecond line", components=[_c()]),
    ])
    assert parse(render(lib)) == lib


def test_roundtrip_component_description_with_literal_backslash_n():
    """A user's description that literally contains '\\' + 'n' (backslash + letter n),
    not a newline, must round-trip distinguishable from a real newline."""
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[
        _c(description=r"escaped: \n"),
    ])])
    assert parse(render(lib)) == lib


def test_roundtrip_component_name_with_pipe_and_backslash():
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[
        _c(name=r"weird|name\with\slashes"),
    ])])
    assert parse(render(lib)) == lib


def test_render_raises_on_illegal_char_in_assembly_type():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(assembly_type="wrong]bracket", components=[_c()]),
    ])
    with pytest.raises(ValueError, match="illegal heading character"):
        render(lib)


def test_render_raises_on_newline_in_assembly_name():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(name="multi\nline", components=[_c()]),
    ])
    with pytest.raises(ValueError, match="illegal heading character"):
        render(lib)


def test_parse_blank_unit_cost_is_treated_as_dash():
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | Carpenter | 4 | HR |  | - | - | - |\n"                    # empty unit_cost cell
    )
    parsed = parse(text)
    assert parsed.assemblies[0].components[0].unit_cost is None


def test_parse_blank_rate_ref_becomes_none_like_dash():
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | Carpenter | 4 | HR | - |  | - | - |\n"                    # empty rate_ref cell
    )
    parsed = parse(text)
    assert parsed.assemblies[0].components[0].rate_ref is None


def test_duplicate_assembly_name_error_includes_section_index():
    text = render(CanonicalAssemblyLibrary(assemblies=[
        _a(name="Manhole Base", components=[_c()]),
        _a(name="Manhole Base", components=[_c()]),
    ]))
    with pytest.raises(ValueError, match=r"section 2:.*duplicate assembly name 'Manhole Base'"):
        parse(text)


def test_roundtrip_non_ascii_component_name_renders_human_readable():
    """Fix A - non-ASCII characters must appear literally in the rendered artifact,
    not as \\uXXXX sequences (unreadable for the user in-conversation)."""
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[
        _c(name="Piñón Ñoño"),
    ])])
    out = render(lib)
    assert "Piñón Ñoño" in out                                    # not "\\u00f1"
    assert "\\u00" not in out
    assert parse(out) == lib


def test_parse_tolerates_unescaped_double_quote_in_cell():
    """Fix B - `4" PVC` (unescaped ") is a plausible user edit. Parse must NOT crash."""
    text = (
        "## Manhole Base [structural] (cost_code: 03-3000)\n\n"
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        '| material | 4" PVC pipe | 100 | LF | 5.50 | - | - | schedule 40 |\n'
    )
    parsed = parse(text)
    comp = parsed.assemblies[0].components[0]
    assert comp.name == '4" PVC pipe'
    assert comp.description == "schedule 40"


def test_roundtrip_cell_with_double_quote_and_backslash_n():
    """The two fixes must compose: a cell with BOTH a raw `"` and a newline must
    round-trip. Newline requires backslash-encoding; the double-quote is unescaped."""
    lib = CanonicalAssemblyLibrary(assemblies=[_a(components=[
        _c(description='4" PVC\nschedule 40'),
    ])])
    assert parse(render(lib)) == lib


# =====================================================================================
# Single-assembly artifact tests (Phase 2b)
# =====================================================================================

from estimating_tools.assemblies.artifact import (
    parse_single, parse_single_with_meta, render_single,
)


# ---------- render_single (== render_assembly alias) ----------

def test_render_single_is_render_assembly():
    """`render_single` is an alias — same output as `render_assembly`."""
    from estimating_tools.assemblies.artifact import render_assembly
    a = _a(components=[_c()])
    assert render_single(a) == render_assembly(a)


def test_render_single_emits_body_only_no_heading():
    a = _a(components=[_c()])
    out = render_single(a)
    assert not out.startswith("##")                               # no library heading
    assert "| component_type | component |" in out                # body has the table


# ---------- parse_single (heading required) ----------

def test_parse_single_roundtrip_via_library_section():
    """Copy a section out of a library render; parse_single recovers the Assembly."""
    a = _a(name="Manhole Base", assembly_type="structural", cost_code="03-3000",
           description="48in precast", components=[_c(), _c(component_type="material",
           name="Concrete", quantity=2.0, unit="CY", unit_cost=175.0, rate_ref=None)])
    lib = CanonicalAssemblyLibrary(assemblies=[a])
    section_text = render(lib)                                    # includes the `##` heading
    assert parse_single(section_text) == a


def test_parse_single_raises_when_no_heading():
    a = _a(components=[_c()])
    body_only = render_single(a)                                  # no `##` heading
    with pytest.raises(ValueError, match="exactly one"):
        parse_single(body_only)


def test_parse_single_raises_when_multiple_headings():
    lib = CanonicalAssemblyLibrary(assemblies=[
        _a(name="Manhole Base", components=[_c()]),
        _a(name="Manhole Riser", components=[_c()]),
    ])
    text = render(lib)                                            # two `##` headings
    with pytest.raises(ValueError, match="exactly one"):
        parse_single(text)


# ---------- parse_single_with_meta (headless — meta out of band) ----------

def test_parse_single_with_meta_roundtrip():
    a = _a(name="Manhole Base", assembly_type="structural", cost_code="03-3000",
           description="48in precast", components=[_c()])
    body = render_single(a)
    parsed = parse_single_with_meta(body, name=a.name,
                                    assembly_type=a.assembly_type,
                                    cost_code=a.cost_code)
    assert parsed == a


def test_parse_single_with_meta_roundtrip_empty_components():
    a = _a(name="Empty", assembly_type="structural", cost_code=None,
           description="", components=[])
    body = render_single(a)
    parsed = parse_single_with_meta(body, name="Empty",
                                    assembly_type="structural", cost_code=None)
    assert parsed == a


def test_parse_single_with_meta_ignores_stray_heading():
    """If the text has a `##` heading (e.g. user pasted from a library render),
    parse_single_with_meta ignores it — the caller's meta wins."""
    a_with_heading = _a(name="Manhole Base", assembly_type="structural",
                        cost_code="03-3000", components=[_c()])
    lib_text = render(CanonicalAssemblyLibrary(assemblies=[a_with_heading]))
    # caller wants meta="Different Name" even though heading says "Manhole Base"
    parsed = parse_single_with_meta(lib_text, name="Different Name",
                                    assembly_type="mechanical", cost_code="02-2000")
    assert parsed.name == "Different Name"
    assert parsed.assembly_type == "mechanical"
    assert parsed.cost_code == "02-2000"
    # But the components come from the parsed table
    assert len(parsed.components) == 1
    assert parsed.components[0].name == "Carpenter"


def test_parse_single_with_meta_none_cost_code():
    a = _a(name="No Code", assembly_type="mep", cost_code=None,
           description="", components=[_c()])
    body = render_single(a)
    parsed = parse_single_with_meta(body, name="No Code",
                                    assembly_type="mep", cost_code=None)
    assert parsed.cost_code is None


def test_parse_single_with_meta_malformed_body_raises_locator():
    body = (
        "| component_type | component | quantity | unit | unit_cost | rate_ref | trade | description |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| labor | - | 4 | HR | - | - | - | - |\n"                # blank required 'component'
    )
    with pytest.raises(ValueError, match="'component' is required"):
        parse_single_with_meta(body, name="X", assembly_type="y")


# =====================================================================================
# ComponentDiff / diff_components tests (Phase 2b)
# =====================================================================================

from estimating_tools.assemblies.artifact import ComponentDiff, diff_components


def test_diff_no_change_empty_diff():
    a = [_c(), _c(component_type="material", name="Concrete", quantity=2.0, unit="CY")]
    b = [_c(), _c(component_type="material", name="Concrete", quantity=2.0, unit="CY")]
    d = diff_components(a, b)
    assert d.to_create == ()
    assert d.to_update == ()
    assert d.to_delete == ()


def test_diff_all_create_when_original_empty():
    edited = [_c(), _c(component_type="material", name="Concrete", quantity=2.0)]
    d = diff_components([], edited)
    assert set((c.component_type, c.name) for c in d.to_create) == {
        ("labor", "Carpenter"), ("material", "Concrete"),
    }
    assert d.to_update == ()
    assert d.to_delete == ()


def test_diff_all_delete_when_edited_empty():
    original = [_c(), _c(component_type="material", name="Concrete", quantity=2.0)]
    d = diff_components(original, [])
    assert set((c.component_type, c.name) for c in d.to_delete) == {
        ("labor", "Carpenter"), ("material", "Concrete"),
    }
    assert d.to_create == ()
    assert d.to_update == ()


def test_diff_update_when_same_key_different_fields():
    original = [_c(quantity=4.0)]                                 # labor Carpenter, 4 HR
    edited = [_c(quantity=6.0)]                                   # labor Carpenter, 6 HR
    d = diff_components(original, edited)
    assert d.to_create == ()
    assert d.to_delete == ()
    assert len(d.to_update) == 1
    orig, new = d.to_update[0]
    assert orig.quantity == 4.0
    assert new.quantity == 6.0


def test_diff_mix_create_update_delete_unchanged():
    original = [
        _c(name="Carpenter", quantity=4.0),                       # will update (quantity)
        _c(component_type="material", name="Concrete", quantity=2.0),  # will delete
        _c(component_type="equipment", name="Excavator", quantity=1.0),  # unchanged
    ]
    edited = [
        _c(name="Carpenter", quantity=6.0),                       # updated
        _c(component_type="equipment", name="Excavator", quantity=1.0),  # unchanged
        _c(component_type="material", name="Rebar", quantity=20.0, unit="LB"),  # created
    ]
    d = diff_components(original, edited)
    assert [(c.component_type, c.name) for c in d.to_create] == [("material", "Rebar")]
    assert [(c.component_type, c.name) for c in d.to_delete] == [("material", "Concrete")]
    assert len(d.to_update) == 1
    orig, new = d.to_update[0]
    assert (orig.component_type, orig.name) == ("labor", "Carpenter")
    assert new.quantity == 6.0


def test_diff_key_is_component_type_plus_name():
    """Two components with the same name but different component_type do NOT collide."""
    original = [_c(component_type="labor", name="Foo", quantity=1.0)]
    edited = [_c(component_type="material", name="Foo", quantity=1.0)]
    d = diff_components(original, edited)
    assert len(d.to_delete) == 1                                  # labor Foo removed
    assert len(d.to_create) == 1                                  # material Foo added
    assert d.to_update == ()


def test_diff_reorder_alone_is_not_a_change():
    original = [
        _c(name="Carpenter"),
        _c(component_type="material", name="Concrete", quantity=2.0),
    ]
    edited = [
        _c(component_type="material", name="Concrete", quantity=2.0),  # swapped
        _c(name="Carpenter"),
    ]
    d = diff_components(original, edited)
    assert d.to_create == ()
    assert d.to_update == ()
    assert d.to_delete == ()


def test_diff_duplicate_in_edited_last_wins():
    """Documented behavior: if `edited` has two components with the same
    (component_type, name), the LAST occurrence wins."""
    original = [_c(quantity=4.0)]
    edited = [_c(quantity=6.0), _c(quantity=8.0)]                 # two "Carpenter" entries
    d = diff_components(original, edited)
    assert d.to_create == ()
    assert d.to_delete == ()
    assert len(d.to_update) == 1
    _, new = d.to_update[0]
    assert new.quantity == 8.0                                    # last wins
