"""ITB document rendering — one markdown Invitation To Bid per vendor.

Deterministic given its inputs (no MCP, no network): scope text comes from
the briefing pack, the item list from a work-package export the skill
writes, letterhead from the active org profile's ``letterhead.md`` (empty
string = agnostic fallback, the scaffold-project convention)."""
from __future__ import annotations

import re


def vendor_slug(name: str) -> str:
    """Filename-safe slug: lowercase, alnum runs joined by single dashes.
    Never empty — a name with no ASCII alnum falls back to "vendor" so the
    output filename can't degrade to a hidden ``.md``."""
    return "-".join(re.findall(r"[a-z0-9]+", name.casefold())) or "vendor"


def md_cell(value) -> str:
    """Markdown table cell: stringify and escape ``|`` so a value can't
    break its row."""
    return str(value).replace("|", "\\|")


def _qty(q) -> str:
    if q is None:
        return ""
    try:
        return "%g" % float(q)
    except (ValueError, TypeError):
        return str(q)


def render_itb(*, project_name: str, package_name: str, vendor_name: str,
               contacts: list[str], items: list[dict], scope: str = "",
               letterhead: str = "", respond_by: str = "",
               notes: str = "") -> str:
    lines: list[str] = []
    if letterhead.strip():
        lines += [letterhead.strip(), ""]
    lines += [f"# Invitation to Bid — {package_name}", "",
              f"**Project:** {project_name}",
              f"**To:** {vendor_name}" + (f" ({', '.join(contacts)})" if contacts else "")]
    if respond_by:
        lines.append(f"**Respond by:** {respond_by}")
    lines.append("")
    if scope.strip():
        lines += ["## Scope", "", scope.strip(), ""]
    lines += ["## Bid Items", "",
              "| Schedule | Item | Description | Quantity | Unit |",
              "|---|---|---|---|---|"]
    for it in items:
        lines.append(
            f"| {md_cell(it.get('schedule', ''))} | {md_cell(it.get('item_number', ''))} "
            f"| {md_cell(it.get('description', ''))} | {md_cell(_qty(it.get('quantity')))} "
            f"| {md_cell(it.get('unit', ''))} |")
    lines += ["",
              "## Quoting Instructions", "",
              "- Quote each item at a unit price; note any items excluded.",
              "- State inclusions/exclusions, and acknowledge all addenda.",
              "- Quotes conditioned on award of the full package: say so explicitly."]
    if notes.strip():
        lines += ["", notes.strip()]
    return "\n".join(lines) + "\n"
