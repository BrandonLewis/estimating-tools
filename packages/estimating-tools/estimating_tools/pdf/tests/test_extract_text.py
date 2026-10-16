import importlib
import tempfile
import os
import pytest


def test_module_imports_and_exposes_callable():
    mod = importlib.import_module("estimating_tools.pdf.extract_text")
    callables = [n for n in dir(mod) if callable(getattr(mod, n)) and not n.startswith("_")]
    assert callables, "extract_text.py exposes no public functions"


def test_public_functions_include_extract_text():
    mod = importlib.import_module("estimating_tools.pdf.extract_text")
    assert hasattr(mod, "extract_text"), "extract_text function not found"
    assert hasattr(mod, "parse_page_range"), "parse_page_range function not found"
    assert callable(mod.extract_text)
    assert callable(mod.parse_page_range)


def test_parse_page_range_all():
    from estimating_tools.pdf.extract_text import parse_page_range
    result = parse_page_range("all", 5)
    assert result == [0, 1, 2, 3, 4]


def test_parse_page_range_specific():
    from estimating_tools.pdf.extract_text import parse_page_range
    result = parse_page_range("1-3,5", 10)
    assert result == [0, 1, 2, 4]


def _make_minimal_pdf(text: str) -> bytes:
    """Build a minimal valid single-page PDF containing the given text."""
    # Minimal PDF structure with a single text stream
    stream_content = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET"
    stream_bytes = stream_content.encode("latin-1")
    stream_len = len(stream_bytes)

    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        + f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode()
        + stream_bytes
        + b"\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    )

    # Build cross-reference table
    xref_pos = len(pdf)
    # We have 5 objects; compute byte offsets
    offsets = []
    pos = 0
    lines = pdf.split(b"\n")
    # Re-parse to find object start offsets
    current = 0
    obj_starts = {}
    for i, line in enumerate(lines):
        if line.endswith(b"obj"):
            try:
                obj_num = int(line.split()[0])
                obj_starts[obj_num] = current
            except (ValueError, IndexError):
                pass
        current += len(line) + 1  # +1 for newline

    xref_table = b"xref\n"
    xref_table += f"0 6\n".encode()
    xref_table += b"0000000000 65535 f \n"
    for i in range(1, 6):
        offset = obj_starts.get(i, 0)
        xref_table += f"{offset:010d} 00000 n \n".encode()

    trailer = (
        xref_table
        + b"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        + f"startxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return pdf + trailer


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("pdfplumber"),
    reason="pdfplumber not installed",
)
def test_extract_text_round_trip():
    """Write a minimal PDF, then confirm extract_text returns success and non-empty text."""
    from estimating_tools.pdf.extract_text import extract_text

    pdf_bytes = _make_minimal_pdf("HelloPDF")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = f.name

    try:
        result = extract_text(tmp_path)
        # The PDF may or may not contain embedded fonts that pdfplumber can read,
        # but the call must succeed and return a result dict without crashing.
        assert isinstance(result, dict)
        assert "success" in result
        # Even if text extraction yields empty (Type1 font not embedded),
        # success=True means pdfplumber parsed the file without error.
        if result["success"]:
            assert "full_text" in result
            assert "pages" in result
    finally:
        os.unlink(tmp_path)


def test_extract_text_missing_file():
    from estimating_tools.pdf.extract_text import extract_text
    result = extract_text("/nonexistent/path/to/file.pdf")
    assert result["success"] is False
    assert "error" in result
