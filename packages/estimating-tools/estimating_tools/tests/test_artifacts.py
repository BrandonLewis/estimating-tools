from estimating_tools.artifacts import format_money, format_qty, md_table


def test_format_money():
    assert format_money(None) == ""
    assert format_money(125) == "125.00"
    assert format_money(0) == "0.00"
    assert format_money(2.5) == "2.50"


def test_format_qty():
    assert format_qty(None) == ""
    assert format_qty(1000.0) == "1000"
    assert format_qty(2.5) == "2.5"
    assert format_qty(0) == "0"


def test_md_table_structure_no_trailing_newline():
    out = md_table(["A", "B"], [["1", "2"]])
    assert out == "| A | B |\n| --- | --- |\n| 1 | 2 |"
    assert not out.endswith("\n")


def test_md_table_empty_rows_is_header_plus_separator():
    assert md_table(["A", "B"], []) == "| A | B |\n| --- | --- |"


def test_md_table_escapes_pipes_in_headers_and_cells():
    out = md_table(["A|x", "B"], [["a|b", "c"]])
    assert "A\\|x" in out and "a\\|b" in out
    assert "| --- | --- |" in out          # separator unaffected


def test_md_table_stringifies_non_str_cells():
    # cells may arrive already-stringified, but md_table must not crash on a stray non-str
    assert md_table(["A"], [[1]]) == "| A |\n| --- |\n| 1 |"
