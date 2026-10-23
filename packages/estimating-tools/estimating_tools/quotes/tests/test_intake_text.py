import json

import yaml

from estimating_tools.quotes.intake.inventory import (
    Inventory, inbox_dir_for, state_dir_for)
from estimating_tools.quotes.intake.scan import scan_inbox
from estimating_tools.quotes.intake.text import (
    DOCX_METADATA_MARKER, XLS_REASON, decide_route, image_paths, pages_dir,
    recover_text, text_path)
from estimating_tools.quotes.tests._intake import (
    QUOTE_TEXT, make_docx, make_pdf, make_png, make_xlsx, spec_on_disk)


def _setup(tmp_path):
    spec_path = spec_on_disk(tmp_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    state = state_dir_for(spec_path, spec)
    return inbox_dir_for(spec_path, spec), state, Inventory.load(state)


def _recover(inbox, state, inv):
    scan_inbox(inv, inbox, state)
    report = recover_text(inv, state)
    return report, list(inv)


def test_a_text_pdf_routes_text_and_writes_the_page_text(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "q.pdf", [QUOTE_TEXT])
    report, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.pages, doc.status) == ("text", 1, "new")
    assert report.summary() == "1 text, 0 vision, 0 unreadable"
    text = text_path(state, doc.sha256).read_text(encoding="utf-8")
    assert "Hartsook Creek Bridge" in text and "--- page 1 ---" in text


def test_a_scanned_pdf_routes_vision_and_renders_with_the_manifest_last(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "scan.pdf", [None, None])
    _, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.pages) == ("vision", 2)
    folder = pages_dir(state, doc.sha256)
    assert (folder / "p001.png").exists() and (folder / "p002.png").exists()
    assert json.loads((folder / "manifest.json").read_text()) == {"pages": 2}
    assert image_paths(doc, state) == [str(folder / "p001.png"), str(folder / "p002.png")]


def test_decide_route_uses_the_mean_of_the_first_three_pages():
    assert decide_route(["x" * 300, "", ""]) == "vision"
    assert decide_route(["x" * 600, "", "", ""]) == "text"
    assert decide_route([]) == "vision"


def test_a_docx_table_and_its_metadata_are_recovered(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_docx(inbox / "q.docx", ["ACME REBAR"], table=[["#4 rebar", "2.05"]], author="Pat")
    _, (doc,) = _recover(inbox, state, inv)
    assert doc.route == "text"
    text = text_path(state, doc.sha256).read_text(encoding="utf-8")
    assert "ACME REBAR" in text and "#4 rebar\t2.05" in text
    assert DOCX_METADATA_MARKER in text and "author=Pat" in text


def test_an_xlsx_becomes_tsv_per_sheet(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_xlsx(inbox / "q.xlsx", {"Quote": [["Item", "Price"], ["Haul", 16.5]]})
    _, (doc,) = _recover(inbox, state, inv)
    assert text_path(state, doc.sha256).read_text(encoding="utf-8") == "# Quote\nItem\tPrice\nHaul\t16.5"


def test_csv_and_md_are_read_as_is(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    (inbox / "a.csv").write_text("Item,Price\nHaul,16.5\n", encoding="utf-8")
    (inbox / "b.md").write_text("# Quote\nHaul 16.5\n", encoding="utf-8-sig")
    _, docs = _recover(inbox, state, inv)
    texts = {d.kind: text_path(state, d.sha256).read_text(encoding="utf-8") for d in docs}
    assert texts == {"csv": "Item,Price\nHaul,16.5\n", "md": "# Quote\nHaul 16.5\n"}
    assert all(d.route == "text" for d in docs)


def test_an_empty_document_is_an_error(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    (inbox / "blank.txt").write_text("  \n", encoding="utf-8")
    _, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.status, doc.reason) == ("unreadable", "error", "no text in the document")


def test_an_image_routes_vision_with_itself_as_the_page(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    png = make_png(inbox / "q.png", "hello")
    _, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.pages) == ("vision", 1)
    assert image_paths(doc, state) == [str(png)]
    assert not (state / "pages").exists()


def test_an_xls_is_unreadable_with_the_reason(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    (inbox / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0")
    report, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.status, doc.reason) == ("unreadable", "error", XLS_REASON)
    assert report.unreadable == 1


def test_a_corrupt_pdf_is_an_error_with_the_exception_text(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    (inbox / "bad.pdf").write_bytes(b"%PDF-1.4 garbage")
    _, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.status) == ("unreadable", "error")
    assert doc.reason.split(":")[0].endswith(("Error", "Exception"))


def test_recover_text_is_idempotent(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "q.pdf", [QUOTE_TEXT])
    make_pdf(inbox / "s.pdf", [None])
    _recover(inbox, state, inv)
    files = {p: p.stat().st_mtime_ns for p in state.rglob("*") if p.is_file()}
    report = recover_text(inv, state)
    assert report.summary() == "0 text, 0 vision, 0 unreadable"
    assert {p: p.stat().st_mtime_ns for p in state.rglob("*") if p.is_file()} == files


def test_a_vision_document_without_a_manifest_has_no_image_paths(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_pdf(inbox / "scan.pdf", [None])
    _, (doc,) = _recover(inbox, state, inv)
    (pages_dir(state, doc.sha256) / "manifest.json").unlink()
    assert image_paths(doc, state) is None


def test_an_xlsx_with_no_values_is_an_error(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_xlsx(inbox / "e.xlsx", {"Quote": []})
    _, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.status, doc.reason) == ("unreadable", "error", "no text in the document")


def test_an_xlsx_of_uncached_formulas_names_the_cause(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_xlsx(inbox / "f.xlsx", {"Quote": [["=1+1"]]})
    _, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.status) == ("unreadable", "error")
    assert doc.reason == "no cached values in the workbook (open and save it in Excel)"


def test_a_docx_with_only_metadata_is_an_error(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_docx(inbox / "m.docx", paragraphs=[], author="Pat")
    _, (doc,) = _recover(inbox, state, inv)
    assert (doc.route, doc.status, doc.reason) == ("unreadable", "error", "no text in the document")


def test_text_cells_do_not_hide_uncached_formula_prices(tmp_path):
    inbox, state, inv = _setup(tmp_path)
    make_xlsx(inbox / "partial.xlsx", {"Quote": [["Dirt Movers", "Price"], ["Hauling", "=16.5"]]})
    report, (doc,) = _recover(inbox, state, inv)
    assert doc.route == "unreadable" and doc.status == "error"
    assert "cached" in doc.reason
    assert report.text == 0 and report.unreadable == 1
    assert not text_path(state, doc.sha256).exists()


def test_a_formula_with_a_saved_value_remains_readable(tmp_path):
    import zipfile

    inbox, state, inv = _setup(tmp_path)
    path = make_xlsx(inbox / "cached.xlsx", {"Quote": [["Dirt Movers", "=16.5"]]})
    with zipfile.ZipFile(path) as book:
        members = {name: book.read(name) for name in book.namelist()}
    xml = members["xl/worksheets/sheet1.xml"]
    assert b"<f>16.5</f><v></v>" in xml
    members["xl/worksheets/sheet1.xml"] = xml.replace(
        b"<f>16.5</f><v></v>", b"<f>16.5</f><v>16.5</v>")
    with zipfile.ZipFile(path, "w") as book:
        for name, data in members.items():
            book.writestr(name, data)
    report, (doc,) = _recover(inbox, state, inv)
    assert doc.route == "text" and report.text == 1
    assert "16.5" in text_path(state, doc.sha256).read_text()
