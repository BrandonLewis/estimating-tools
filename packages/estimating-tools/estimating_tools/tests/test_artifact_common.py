from estimating_tools.artifact_common import split_pipes, split_semicolons


def test_split_pipes_basic():
    assert split_pipes("a|b|c") == ["a", "b", "c"]


def test_split_pipes_preserves_escaped_pipe():
    # split_pipes keeps the "\|" escape sequence in the token; the caller unescapes.
    assert split_pipes(r"a\|b|c") == [r"a\|b", "c"]


def test_split_semicolons_basic():
    assert split_semicolons("a;b;c") == ["a", "b", "c"]


def test_split_semicolons_preserves_escaped_semicolon():
    assert split_semicolons(r"a\;b;c") == [r"a\;b", "c"]


# ---- escape_string_field / unescape_string_field tests (Phase 4) ----

from estimating_tools.artifact_common import escape_string_field, unescape_string_field


def test_escape_string_field_preserves_non_ascii():
    """No \\uXXXX escapes; the artifact stays human-readable."""
    out = escape_string_field("Piñón Ñoño")
    assert "Piñón Ñoño" in out
    assert "\\u00" not in out


def test_escape_string_field_escapes_newline_and_backslash():
    assert escape_string_field("a\nb") == "a\\nb"
    assert escape_string_field("a\\b") == "a\\\\b"


def test_unescape_string_field_short_circuits_without_backslash():
    """Plain user text (e.g. `4" PVC` inch-mark) passes through untouched."""
    assert unescape_string_field('4" PVC pipe') == '4" PVC pipe'
    assert unescape_string_field("no escapes here") == "no escapes here"


def test_escape_unescape_roundtrip():
    for original in ("simple", "with\nnewline", "with\\backslash", '4" quote',
                     "Piñón", "mixed\n\\|test"):
        assert unescape_string_field(escape_string_field(original)) == original
