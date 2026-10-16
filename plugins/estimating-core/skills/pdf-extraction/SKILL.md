---
name: pdf-extraction
description: Extract text, tables, and data from PDF documents
---

> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` (the plugin root is this skill's directory's grandparent); it builds the shared runtime and prints one line saying what happened. Then retry.

# PDF Extraction Skill

Extract text, tables, and structured data from PDF documents — construction
plans, specifications, bid tabs, and reports. The judgment here is the
doc-type triage; the mechanics live in the module.

## 1. Identify the Document Type (do this first)

- **Text-based PDF** — Can copy/paste text from the PDF; extract directly.
- **Scanned PDF** — PDF is an image; requires OCR (pytesseract +
  pdf2image — slow, use only when the page truly has no text layer).
- **Mixed PDF** — Contains both text and scanned pages.
- **CAD-plotted plan sheet** - plotted from CAD, so the vector paths ARE
  the geometry, but the lettering is flattened to outlines (the NORM on
  signed agency bid sets). The tell: `get_text()` returns almost nothing
  (2 characters on a full 24x36 sheet) while the page is visibly dense.
  Do NOT OCR these - OCR discards exact vector data to guess at pixels.
  Route measurement/geometry questions to the `measure-plans` skill
  (**calc-bim plugin**): `bimforge.bim.plansheet.vectors.extract_sheet`
  is the geometry entry point, not `extract_text`.

## 2. Extract

The extractor lives in the plugin at `estimating_tools.pdf.extract_text` —
run `~/.estimating/bin/est-python -m estimating_tools.pdf.extract_text --help` for the full CLI
(page ranges like `"1-5,7,9-11"`, JSON or plain-text output, page breaks,
metadata). The 2-line API:

```python
from estimating_tools.pdf.extract_text import extract_text
result = extract_text("spec.pdf", pages="1-10")  # dict: per-page text + metadata
```

**Tables** are not this module's job — use `pdfplumber` directly
(`page.extract_tables()`, optionally into `pandas` for an Excel export).
For grid-layout PDFs read the section below before trusting extracted rows.

## Construction Use Cases

- **Bid tabulations** — extract the item table (Item #, Description,
  Quantity, Unit, Price), validate completeness/totals, export to Excel.
- **Specifications** — extract by page/section; identify CSI divisions,
  requirements, and submittal requirements.
- **Plan-sheet quantity support** — pull embedded tables, quantity callouts,
  and material specs; cross-reference with spec sections. (Geometry off the
  sheets themselves is the `measure-plans` skill, calc-bim plugin.)

See the `quantity-takeoff` skill for the full takeoff workflow that builds
on this skill.

## Grid-Layout Schedule PDFs (position beats order)

Two hard-won lessons from parsing printed schedule grids; both generalize to
any column-grid PDF:

- **Place cells by x-position against measured column centers, never by token
  order.** In a weekly crew schedule (a week of day columns), most crews work
  Mon-Fri, so a row's five entries belong to columns 2-6 — reading them left
  to right shifts every assignment a day earlier. Measure each date column's x
  center from the header row, then assign each cell to the nearest column. A
  trailing extra column outside the week (e.g. a planning/notes column) is
  dropped, not folded into Saturday.
- **When text overflows its column, rebuild cells from characters in
  content-stream order, not from `extract_words()`.** In a P6 print-layout
  PDF, a long activity name is not clipped to its column and runs underneath
  the adjacent duration/date cells; grouping those glyphs by position alone
  interleaves them (`Co3ncret1e3-Nov-26`). Each cell is one text run in the
  content stream, so a backward or wide jump in x ends the cell. Two more P6
  quirks: bold rows drawn by overprinting each glyph five times
  (`PPPPPhhhhhaaaaassssseeeee`) collapse under pdfplumber's
  `dedupe_chars`, and a date followed by `A` is an actual, not a plan.

## Error Handling

- **Empty or garbled text:** first check for the CAD-plotted tell above —
  a vector plan sheet is NOT an OCR case; route to `measure-plans`
  (calc-bim plugin). A genuinely scanned page → OCR. Also check for PDF
  security/permissions.
- **Missing tables:** adjust pdfplumber table settings; complex layouts may
  need the grid-layout techniques above or manual extraction.
- **Large PDFs:** process page by page; extract tables only from relevant
  pages. Validate extracted data against the source and preserve which
  page/PDF each datum came from.
