"""Letterhead engine: render markdown frontmatter + body into a docxtpl template."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Mapping
from xml.sax.saxutils import escape as _sax_escape

from docxtpl import DocxTemplate, RichText


# V1 limitations:
# - bold: asterisk-only (`**bold**`); no underscore (`__bold__`), no escape (`\**`),
#   no nested or code-span detection.
# - italic: asterisk-only (`*italic*`); no underscore (`_italic_`).
# - Other markdown constructs (headings, lists, links) pass through as raw text.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def _markdown_body_to_richtexts(body_md: str) -> list[RichText]:
    """Split body markdown into paragraphs; emit one RichText per paragraph with bold/italic runs."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body_md.strip()) if p.strip()]
    out: list[RichText] = []
    for para in paragraphs:
        rt = RichText()
        tokens: list[tuple[str, bool, bool]] = []
        # Two-pass: bold first, then italic inside non-bold spans.
        pos = 0
        while pos < len(para):
            m = _BOLD_RE.search(para, pos)
            if not m:
                tokens.extend(_italic_tokens(para[pos:]))
                break
            if m.start() > pos:
                tokens.extend(_italic_tokens(para[pos:m.start()]))
            tokens.append((m.group(1), True, False))
            pos = m.end()
        for text, bold, italic in tokens:
            rt.add(text, bold=bold, italic=italic)
        out.append(rt)
    return out


def _italic_tokens(text: str) -> list[tuple[str, bool, bool]]:
    tokens: list[tuple[str, bool, bool]] = []
    pos = 0
    while pos < len(text):
        m = _ITALIC_RE.search(text, pos)
        if not m:
            tokens.append((text[pos:], False, False))
            break
        if m.start() > pos:
            tokens.append((text[pos:m.start()], False, False))
        tokens.append((m.group(1), False, True))
        pos = m.end()
    return tokens


def _xml_escape_ctx(value):
    """Recursively XML-escape string values in the docxtpl context (str/list/dict)."""
    if isinstance(value, str):
        return _sax_escape(value)  # & < >  ->  &amp; &lt; &gt;
    if isinstance(value, list):
        return [_xml_escape_ctx(v) for v in value]
    if isinstance(value, dict):
        return {k: _xml_escape_ctx(v) for k, v in value.items()}
    return value


def render_letterhead(
    template_path: Path,
    output_path: Path,
    frontmatter: Mapping[str, object],
    body_md: str,
) -> Path:
    """Render `template_path` into `output_path` with frontmatter + body markdown.

    The body is rendered into the `{{r body }}` placeholder as a docxtpl
    RichText with bold/italic spans. Empty `body_md` renders as an empty
    body placeholder (no error). The template must use the run-level
    `{{r body }}` syntax (NOT `{{ body }}`) and `{%tr for %}` / `{%tr endfor %}`
    must occupy their own dedicated table rows.
    """
    tpl = DocxTemplate(str(template_path))
    # docxtpl does not XML-escape plain ``{{ }}`` substitutions, so a raw
    # ``&``/``<``/``>`` in a frontmatter value becomes invalid XML and is
    # dropped by the recovering parser. Escape string values (recursively
    # through lists/dicts) before rendering; body goes through RichText,
    # which escapes on .add().
    ctx = _xml_escape_ctx(dict(frontmatter))
    body_paragraphs = _markdown_body_to_richtexts(body_md)
    # Join paragraphs with newlines; docxtpl will render the RichText sequence with breaks.
    body_rt = RichText()
    for i, rt in enumerate(body_paragraphs):
        if i > 0:
            body_rt.add("\a")  # docxtpl paragraph-break sentinel
        # Append children of each paragraph RT into the combined one.
        body_rt.xml += rt.xml
    ctx["body"] = body_rt
    tpl.render(ctx)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(output_path))
    return output_path
