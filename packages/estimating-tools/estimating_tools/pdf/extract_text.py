#!/usr/bin/env python3
"""
PDF Text Extraction Utility
Extracts text from PDF documents with support for page ranges.

CLI:  python -m estimating_tools.pdf.extract_text --file spec.pdf \
          --pages "1-5,7,9-11" [--output json|text] [--page-breaks] [--no-metadata]
      (--pages defaults to "all"; text output prints the combined text,
      json includes per-page text, char counts, and PDF metadata)
API:  extract_text(file_path, pages="1-10") -> dict with per-page text,
      full_text, and metadata; parse_page_range("1-5,7", total_pages) -> page numbers.

TEXT ONLY. For tables, use pdfplumber directly (page.extract_tables(),
optionally into pandas for Excel). A CAD-plotted plan sheet whose text layer
is near-empty while the page is visibly dense has flattened (vector-outline)
lettering — that is a geometry problem, not an OCR problem: route it to
bimforge's plan-sheet vector extraction (calc-bim measure-plans skill),
never pytesseract.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber is not installed. Install with: pip install pdfplumber")
    sys.exit(1)


def parse_page_range(range_str, total_pages):
    """
    Parse page range string like '1-5,7,9-11' into list of page numbers

    Args:
        range_str: String like '1-5,7,9-11' or 'all'
        total_pages: Total number of pages in document

    Returns:
        List of page numbers (0-indexed)
    """
    if range_str.lower() == 'all':
        return list(range(total_pages))

    pages = []
    for part in range_str.split(','):
        if '-' in part:
            start, end = part.split('-')
            start = int(start) - 1  # Convert to 0-indexed
            end = int(end)
            pages.extend(range(start, end))
        else:
            pages.append(int(part) - 1)  # Convert to 0-indexed

    return sorted(set(pages))


def extract_text(file_path, pages='all', include_metadata=True):
    """
    Extract text from PDF file

    Args:
        file_path: Path to PDF file
        pages: Page range to extract ('all', '1-5', '1-5,7,9-11')
        include_metadata: Include PDF metadata in output

    Returns:
        Dictionary with extracted text and metadata
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)

            # Parse page range
            if isinstance(pages, str):
                page_numbers = parse_page_range(pages, total_pages)
            else:
                page_numbers = list(range(total_pages))

            # Extract text
            extracted_pages = []
            for page_num in page_numbers:
                if 0 <= page_num < total_pages:
                    page = pdf.pages[page_num]
                    text = page.extract_text()

                    extracted_pages.append({
                        'page': page_num + 1,  # 1-indexed for display
                        'text': text or '',
                        'char_count': len(text) if text else 0
                    })

            # Combine all text
            full_text = '\n'.join(p['text'] for p in extracted_pages)

            result = {
                'success': True,
                'file': str(file_path),
                'total_pages': total_pages,
                'extracted_pages': len(extracted_pages),
                'total_chars': len(full_text),
                'pages': extracted_pages,
                'full_text': full_text
            }

            # Add metadata if requested
            if include_metadata and pdf.metadata:
                result['metadata'] = {
                    k: str(v) for k, v in pdf.metadata.items()
                }

            return result

    except FileNotFoundError:
        return {'success': False, 'error': f'File not found: {file_path}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def main():
    parser = argparse.ArgumentParser(description='Extract text from PDF files')
    parser.add_argument('--file', required=True, help='Path to PDF file')
    parser.add_argument('--pages', default='all', help='Pages to extract (e.g., "1-5", "1-5,7,9-11", or "all")')
    parser.add_argument('--output', choices=['json', 'text'], default='json', help='Output format')
    parser.add_argument('--no-metadata', action='store_true', help='Exclude PDF metadata')
    parser.add_argument('--page-breaks', action='store_true', help='Include page break markers in text output')

    args = parser.parse_args()

    result = extract_text(
        file_path=args.file,
        pages=args.pages,
        include_metadata=not args.no_metadata
    )

    if not result['success']:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.output == 'json':
        print(json.dumps(result, indent=2, default=str))
    else:
        # Plain text output
        if args.page_breaks:
            for page in result['pages']:
                print(f"\n{'='*60}")
                print(f"Page {page['page']}")
                print(f"{'='*60}\n")
                print(page['text'])
        else:
            print(result['full_text'])


if __name__ == '__main__':
    main()
