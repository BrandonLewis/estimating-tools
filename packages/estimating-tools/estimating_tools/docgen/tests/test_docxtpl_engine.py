"""Regression: frontmatter values must be XML-escaped before docxtpl render."""
import pytest

docx = pytest.importorskip("docx")
pytest.importorskip("docxtpl")

from estimating_tools.docgen.docxtpl_engine import render_letterhead


def _make_template(path, placeholders=("{{ project }}", "{{r body }}")):
    d = docx.Document()
    for placeholder in placeholders:
        d.add_paragraph(placeholder)
    d.save(str(path))
    return path


def test_ampersand_in_frontmatter_survives(tmp_path):
    # docxtpl does not escape plain {{ }} substitutions: a raw & becomes
    # invalid XML and the recovering parser drops the run — "Antelope Parkway
    # & 5th" rendered as "Antelope Parkway  5th" (R1 item 7).
    tpl = _make_template(tmp_path / "tpl.docx")
    out = tmp_path / "out.docx"
    render_letterhead(tpl, out, {"project": "Antelope Parkway & 5th"},
                      "Body text.")
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert "Antelope Parkway & 5th" in text


def test_nested_values_escaped(tmp_path):
    # Template substitutes the nested list/dict values too, so this covers
    # the list/dict recursion of _xml_escape_ctx, not just top-level strings.
    tpl = _make_template(
        tmp_path / "tpl.docx",
        ("{{ project }}", "{{ extra[0] }}", "{{ extra[1].k }}", "{{r body }}"),
    )
    out = tmp_path / "out.docx"
    render_letterhead(tpl, out,
                      {"project": "A<B>C", "extra": ["x & y", {"k": "p<q"}]},
                      "")
    text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
    assert "A<B>C" in text
    assert "x & y" in text
    assert "p<q" in text
