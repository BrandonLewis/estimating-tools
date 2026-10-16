from estimating_tools.docgen import report_engine


def test_render_markdown_produces_docx(tmp_path):
    out = tmp_path / "report.docx"
    rs = report_engine.ReportStyle("Test Report")
    report_engine.render_markdown(
        "# Heading\n\nA paragraph with **bold**.\n", rs
    )
    rs.save(out)
    assert out.exists() and out.stat().st_size > 0
