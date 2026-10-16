"""Pure render primitives for live artifacts: number formatting + a pipe-safe markdown
table builder. Shared by the spread / award renderers. Stdlib only — no IO/MCP."""
from __future__ import annotations


def format_money(value) -> str:
    return f"{value:.2f}" if value is not None else ""


def format_qty(value) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _cell(value) -> str:
    return str(value).replace("|", "\\|")


def md_table(headers, rows) -> str:
    """A GitHub-flavored markdown pipe table. `|` in any header/cell is escaped (`\\|`).
    Returns the header + separator + body rows joined by "\\n", with NO trailing newline
    (callers compose surrounding structure)."""
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return "\n".join(lines)
