import pytest

from estimating_tools.costcodes.strategies import resolve_parents


def _rows(pairs, code_col="code", parent_col="parent_code"):
    return [{code_col: c, parent_col: p} for c, p in pairs]


# --- flat / explicit_column ------------------------------------------------


def test_flat_makes_every_code_a_root():
    rows = _rows([("A", ""), ("B", "A")])
    m = {"code": "code", "parent_code": "parent_code"}
    assert resolve_parents("flat", rows, m) == {"A": "", "B": ""}


def test_explicit_column_reads_parent_column():
    rows = _rows([("A", ""), ("B", "A"), ("C", "B")])
    m = {"code": "code", "parent_code": "parent_code"}
    assert resolve_parents("explicit_column", rows, m) == {"A": "", "B": "A", "C": "B"}


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="unknown parent strategy"):
        resolve_parents("nope", [], {"code": "code"})


# --- segment_truncate ------------------------------------------------------


def test_segment_truncate_masterformat_prefix_nesting():
    rows = _rows([("03", ""), ("03 30 00", ""), ("03 30 00.13", "")])
    m = {"code": "code"}
    got = resolve_parents("segment_truncate", rows, m)
    assert got == {"03": "", "03 30 00": "03", "03 30 00.13": "03 30 00"}


def test_segment_truncate_missing_intermediate_falls_to_nearest_existing():
    rows = _rows([("03", ""), ("03 30 00.13", "")])
    m = {"code": "code"}
    got = resolve_parents("segment_truncate", rows, m)
    assert got == {"03": "", "03 30 00.13": "03"}


def test_segment_truncate_dash_delimiter_procore():
    rows = _rows([("01", ""), ("01-100", ""), ("01-100-10", "")])
    m = {"code": "code"}
    got = resolve_parents("segment_truncate", rows, m, delimiters=("-",))
    assert got == {"01": "", "01-100": "01", "01-100-10": "01-100"}


# --- numeric_stub ----------------------------------------------------------


def test_numeric_stub_hierarchy():
    rows = _rows([("02-000", ""), ("02-100", ""), ("02-110", ""), ("02-111", "")])
    m = {"code": "code"}
    got = resolve_parents("numeric_stub", rows, m)
    assert got == {
        "02-000": "",
        "02-100": "02-000",
        "02-110": "02-100",
        "02-111": "02-110",
    }


def test_numeric_stub_skips_absent_parent():
    rows = _rows([("02-000", ""), ("02-110", "")])
    m = {"code": "code"}
    got = resolve_parents("numeric_stub", rows, m)
    assert got == {"02-000": "", "02-110": ""}


# --- indentation -----------------------------------------------------------


def test_indentation_builds_tree_from_indent_column():
    rows = [
        {"code": "A", "indent": 0},
        {"code": "B", "indent": 1},
        {"code": "C", "indent": 2},
        {"code": "D", "indent": 1},
    ]
    m = {"code": "code", "indent": "indent"}
    got = resolve_parents("indentation", rows, m)
    assert got == {"A": "", "B": "A", "C": "B", "D": "A"}
