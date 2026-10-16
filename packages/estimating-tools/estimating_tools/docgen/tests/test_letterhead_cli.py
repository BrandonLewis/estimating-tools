"""est-letterhead CLI: markdown-with-frontmatter draft -> letterhead docx."""
import pytest

docx = pytest.importorskip("docx")
pytest.importorskip("docxtpl")

from estimating_tools.docgen import letterhead_cli


def _make_template(path, placeholders=("{{ company_name }}", "{{ project }}",
                                       "{{r body }}")):
    d = docx.Document()
    for placeholder in placeholders:
        d.add_paragraph(placeholder)
    d.save(str(path))
    return path


DRAFT = """---
project: Antelope Parkway
subject: Deck quantity
company_name: Draft-Level Constructors
---
First paragraph of the letter.

Second paragraph with **bold** text.
"""


def _docx_text(path):
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def test_renders_draft_with_explicit_template(tmp_path):
    tpl = _make_template(tmp_path / "tpl.docx")
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT, encoding="utf-8")
    out = tmp_path / "out.docx"
    assert letterhead_cli.main([str(draft), "-o", str(out),
                                "--template", str(tpl)]) == 0
    assert out.is_file()
    text = _docx_text(out)
    assert "Antelope Parkway" in text
    assert "First paragraph of the letter." in text
    assert "bold" in text


def test_default_output_path_beside_draft(tmp_path):
    tpl = _make_template(tmp_path / "tpl.docx")
    draft = tmp_path / "letter.md"
    draft.write_text(DRAFT, encoding="utf-8")
    assert letterhead_cli.main([str(draft), "--template", str(tpl)]) == 0
    assert (tmp_path / "letter.docx").is_file()


def test_profile_template_used_and_frontmatter_merged(tmp_path, monkeypatch):
    # Active profile supplies the template AND letterhead frontmatter; a
    # non-colliding profile key (address) merges through, and on a COLLIDING
    # key (company_name in both) the draft's value wins — pinning the merge
    # DIRECTION, not just its existence.
    profile_dir = tmp_path / "org-profile"
    profile_dir.mkdir()
    _make_template(profile_dir / "tpl.docx",
                   placeholders=("{{ company_name }}", "{{ address }}",
                                 "{{ project }}", "{{r body }}"))
    (profile_dir / "profile.yaml").write_text(
        "name: Test Org\n"
        "letterhead:\n"
        "  template: tpl.docx\n"
        "  company_name: Profile-Level Builders\n"
        "  address: 1 Sample Plant Rd\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ESTIMATING_PROFILES", str(profile_dir))
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT, encoding="utf-8")
    out = tmp_path / "out.docx"
    assert letterhead_cli.main([str(draft), "-o", str(out)]) == 0
    text = _docx_text(out)
    assert "1 Sample Plant Rd" in text            # profile key merged under
    assert "Draft-Level Constructors" in text     # draft wins the collision
    assert "Profile-Level Builders" not in text
    assert "Antelope Parkway" in text


def test_no_profile_and_no_template_exits_one(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT, encoding="utf-8")
    assert letterhead_cli.main([str(draft)]) == 1
    err = capsys.readouterr().err
    # the message must name both ways out
    assert "--template" in err
    assert "letterhead.template" in err


def test_missing_template_file_exits_one(tmp_path, capsys):
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT, encoding="utf-8")
    assert letterhead_cli.main([str(draft), "--template",
                                str(tmp_path / "nope.docx")]) == 1
    assert "error" in capsys.readouterr().err


def test_missing_draft_exits_one(tmp_path, capsys):
    assert letterhead_cli.main([str(tmp_path / "nope.md")]) == 1
    assert "error" in capsys.readouterr().err


def test_crlf_draft_body_has_no_stray_carriage_return(tmp_path):
    # Copilot PR-135: a Windows-authored draft (CRLF) used to leave a
    # leading \r on the body after the fence strip.
    fm, body = letterhead_cli.split_frontmatter(
        DRAFT.replace("\n", "\r\n"))
    assert fm["project"] == "Antelope Parkway"
    assert body.startswith("First paragraph")


def test_invalid_yaml_frontmatter_exits_one(tmp_path, capsys):
    tpl = _make_template(tmp_path / "tpl.docx")
    draft = tmp_path / "bad.md"
    draft.write_text("---\nproject: [unclosed\n---\nbody\n", encoding="utf-8")
    assert letterhead_cli.main([str(draft), "--template", str(tpl)]) == 1
    assert "error" in capsys.readouterr().err.lower()
