"""Convert canonical artifact renders into self-contained HTML pages.

`to_editable_html(render_output, *, title, editable=True)` parses the small markdown
grammar every artifact renderer emits (headings, `md_table` pipe tables, blockquotes,
bullet lists, single-line paragraphs, HTML comment lines) and emits one self-contained
HTML page: tables become grids (editable in place when `editable=True`), any table with
a quantity column and a unit-cost/price column gains a display-only live extension
column + grand total, and editable pages carry a "Copy edited artifact" button whose
output is the canonical markdown block — byte-identical to the input when nothing was
edited. Non-table lines are never re-serialized: the export splices re-serialized table
BODY rows into the original lines, so fidelity outside table bodies holds by
construction.

Pure stdlib; all CSS/JS inline (artifact sandboxes block external resources).
"""
from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6}) (.*)$")
_PIPE_SPLIT = re.compile(r"(?<!\\)\|")
_QTY_COLUMNS = {"quantity", "qty", "estimated_quantity"}
_COST_COLUMNS = {"unit_cost", "unit_price"}


@dataclass
class _Block:
    kind: str                                    # comment|heading|quote|bullets|para|table
    level: int = 0                               # heading level
    text: str = ""                               # comment/heading/quote/para content
    items: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    start: int = 0                               # table line range in the source [start, end)
    end: int = 0


def _split_row(line: str) -> list[str]:
    """Inverse of md_table's row format: '| a | b |' -> ['a', 'b'] (honors '\\|')."""
    s = line.strip()
    if len(s) < 2 or not (s.startswith("|") and s.endswith("|")):
        raise ValueError(f"not a table row: {line!r}")
    parts = _PIPE_SPLIT.split(s)
    return [p.removeprefix(" ").removesuffix(" ").replace("\\|", "|") for p in parts[1:-1]]


def _serialize_row(cells: list[str]) -> str:
    """md_table's row format (single-space padding, '|' escaped)."""
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(c == "---" for c in cells)


def _computed_columns(header: list[str]) -> tuple[int, int] | None:
    """(qty_index, cost_index) when the table has both, else None."""
    lower = [h.strip().lower() for h in header]
    qty = next((i for i, h in enumerate(lower) if h in _QTY_COLUMNS), None)
    cost = next((i for i, h in enumerate(lower) if h in _COST_COLUMNS), None)
    if qty is None or cost is None:
        return None
    return qty, cost


def _parse_blocks(md: str) -> list[_Block]:
    """Parse a canonical render into blocks.

    Table lines must be flush-left; indented table lines are parsed but re-serialize
    flush-left (out-of-grammar input has no fidelity guarantee).
    """
    lines = md.split("\n")
    blocks: list[_Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "":
            i += 1
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            blocks.append(_Block("comment", text=stripped[4:-3].strip()))
            i += 1
            continue
        m = _HEADING_RE.match(line)
        if m:
            blocks.append(_Block("heading", level=len(m.group(1)), text=m.group(2)))
            i += 1
            continue
        if line.startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].removeprefix(">").removeprefix(" ").rstrip())
                i += 1
            blocks.append(_Block("quote", text=" ".join(quote)))
            continue
        if line.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(lines[i][2:])
                i += 1
            blocks.append(_Block("bullets", items=items))
            continue
        if stripped.startswith("|"):
            start = i
            while i < len(lines) and lines[i].strip().startswith("|"):
                i += 1
            tbl = lines[start:i]
            if len(tbl) < 2 or not _is_separator(_split_row(tbl[1])):
                raise ValueError(
                    f"expected a separator row after the table header at line {start + 2}"
                )
            header = _split_row(tbl[0])
            if len(_split_row(tbl[1])) != len(header):
                raise ValueError(
                    f"separator width != header width at line {start + 2}"
                )
            rows = []
            for offset, raw in enumerate(tbl[2:], start=2):
                cells = _split_row(raw)
                if len(cells) != len(header):
                    raise ValueError(
                        f"table row width {len(cells)} != header width "
                        f"{len(header)} at line {start + offset + 1}: {raw!r}"
                    )
                rows.append(cells)
            blocks.append(_Block("table", header=header, rows=rows, start=start, end=i))
            continue
        blocks.append(_Block("para", text=line.rstrip()))
        i += 1
    return blocks


def _e(s: str) -> str:
    return _html.escape(s, quote=True)


def _block_html(b: _Block) -> str:
    if b.kind == "comment":
        return f'<p class="hint">{_e(b.text)}</p>'
    if b.kind == "heading":
        return f"<h{b.level}>{_e(b.text)}</h{b.level}>"
    if b.kind == "quote":
        return f"<blockquote>{_e(b.text)}</blockquote>"
    if b.kind == "bullets":
        return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in b.items) + "</ul>"
    return f"<p>{_e(b.text)}</p>"


def _table_html(b: _Block, t_idx: int, editable: bool) -> str:
    comp = _computed_columns(b.header)
    ed = ' contenteditable="true"' if editable else ""
    head = "".join(f"<th>{_e(h)}</th>" for h in b.header)
    if comp:
        head += '<th class="ext">extension <span>display only</span></th>'
    if editable:
        head += '<th class="ctl"></th>'
    body_rows = []
    for r in b.rows:
        tds = "".join(f"<td{ed}>{_e(c)}</td>" for c in r)
        if comp:
            tds += '<td class="ext"></td>'
        if editable:
            tds += '<td class="ctl"><button class="del" title="delete row">×</button></td>'
        body_rows.append(f"<tr>{tds}</tr>")
    foot = ""
    if comp:
        ctl_td = '<td class="ctl"></td>' if editable else ""
        foot = (
            f'<tfoot><tr><td colspan="{len(b.header)}">Total (display only)</td>'
            f'<td class="ext total"></td>{ctl_td}</tr></tfoot>'
        )
    add = f'<button class="add" data-t="{t_idx}">+ row</button>' if editable else ""
    return (
        f'<table data-t="{t_idx}"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody>{foot}</table>{add}"
    )


def build_payload(render_output: str, *, editable: bool = True) -> dict:
    """Grid payload shared by `to_editable_html` and the MCP App server.

    {"lines": <source lines>, "tables": <ranges/width/computed per table>,
     "body": <escaped HTML fragment for the page body>}. Raises ValueError on
    out-of-grammar input (same contract as to_editable_html).
    """
    blocks = _parse_blocks(render_output)
    parts: list[str] = []
    tables: list[dict] = []
    for b in blocks:
        if b.kind == "table":
            parts.append(_table_html(b, len(tables), editable))
            comp = _computed_columns(b.header)
            tables.append(
                {
                    "t": len(tables),
                    "start": b.start,
                    "end": b.end,
                    "width": len(b.header),
                    "computed": list(comp) if comp else None,
                }
            )
        else:
            parts.append(_block_html(b))
    return {
        "lines": render_output.split("\n"),
        "tables": tables,
        "body": "".join(parts),
    }


def to_editable_html(
    render_output: str, *, title: str, editable: bool = True, browser_save: bool = False
) -> str:
    """One self-contained HTML page for a canonical artifact render.

    Raises ValueError if the render uses a construct outside the known grammar
    (malformed/width-inconsistent tables) — fail loudly, never drop content.
    With ``browser_save`` the page adds a Save button that POSTs the exported
    block to the relative URL ``save`` (the loopback session server's route).
    """
    p = build_payload(render_output, editable=editable)
    payload = json.dumps(
        {"lines": p["lines"], "tables": p["tables"]}, ensure_ascii=False
    ).replace("<", "\\u003c")
    toolbar = (
        '<button id="save">Save &amp; send to Claude</button>'
        '<button id="copy">Copy edited artifact</button>'
        if editable and browser_save
        else '<button id="copy">Copy edited artifact</button>'
        if editable
        else ""
    )
    savejs = _SAVE_BRIDGE if editable and browser_save else ""
    subs = {
        "__TITLE__": _e(title),
        "__TOOLBAR__": toolbar,
        "__BODY__": p["body"],
        "__PAYLOAD__": payload,
        "__SAVEJS__": savejs,
    }
    return re.sub(
        r"__(?:TITLE|TOOLBAR|BODY|PAYLOAD|SAVEJS)__", lambda m: subs[m.group(0)], _PAGE
    )


_SAVE_BRIDGE = """document.addEventListener("click", e => {
  if (e.target.id !== "save") return;
  const btn = e.target, md = exportMarkdown();
  btn.disabled = true; btn.textContent = "Saving…";
  fetch("save", {method: "POST",
                 headers: {"Content-Type": "text/markdown; charset=utf-8"},
                 body: md})
    .then(r => { if (!r.ok) throw new Error(r.status); })
    .then(() => { btn.disabled = false;
                  btn.textContent = "Saved ✓ — back to the terminal"; })
    .catch(() => { btn.disabled = false; copyOut(btn, md); });
});
"""


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
body{font:14px/1.45 system-ui,"Segoe UI",sans-serif;margin:0;color:#1c2422;background:#fff}
main{max-width:1100px;margin:0 auto;padding:0 20px 60px}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #e2e6e4;padding:10px 20px;display:flex;gap:12px;align-items:center;z-index:2}
header h1{font-size:17px;margin:0;flex:1}
h2{font-size:15px;margin:18px 0 6px}
h3,h4,h5,h6{font-size:14px;margin:14px 0 4px}
table{border-collapse:collapse;margin:10px 0;width:100%}
th,td{border:1px solid #d8dedb;padding:4px 8px;text-align:left;font-variant-numeric:tabular-nums;font-size:13px}
th{background:#eef1ef;font-size:12px}
td[contenteditable]:focus{outline:2px solid #0e6e63;background:#f4faf9}
.ext{background:#f7f4ec;color:#6b5d33;font-style:italic}
th.ext span{display:block;font-size:9px;font-weight:400;text-transform:uppercase;letter-spacing:.05em}
td.ctl,th.ctl{border:none;background:none;width:26px;padding:0;text-align:center}
.del{border:none;background:none;color:#b04a3a;cursor:pointer;font-size:14px}
.add{margin:0 0 14px;border:1px dashed #9aa5a1;background:none;border-radius:4px;padding:2px 10px;cursor:pointer;color:#55605c;font-size:12px}
#copy{background:#0e6e63;color:#fff;border:none;border-radius:6px;padding:8px 14px;cursor:pointer;font-weight:600}
#save{background:#0e6e63;color:#fff;border:none;border-radius:6px;padding:8px 14px;cursor:pointer;font-weight:600}
#save+#copy{background:none;color:#0e6e63;border:1px solid #0e6e63;border-radius:6px;padding:8px 14px;cursor:pointer;font-weight:600}
#out{display:none;width:100%;height:150px;margin:10px 0;font:12px/1.4 Consolas,monospace}
blockquote{border-left:3px solid #0e6e63;margin:8px 0;padding:4px 10px;background:#f2f5f4}
.hint{color:#55605c;font-size:12px;font-style:italic}
tfoot td{font-weight:600}
ul{margin:6px 0;padding-left:22px}
</style>
</head>
<body>
<header><h1>__TITLE__</h1>__TOOLBAR__</header>
<main>
<textarea id="out" readonly></textarea>
__BODY__
</main>
<script type="application/json" id="doc">__PAYLOAD__</script>
<script>
const DOC = JSON.parse(document.getElementById("doc").textContent);
/* GRID-CORE begin — byte-identical across surfaces (test-enforced) */
function dataCells(tr) {
  return [...tr.querySelectorAll("td")].filter(
    td => !td.classList.contains("ext") && !td.classList.contains("ctl"));
}
function cellText(td) { return td.innerText.replace(/\\n/g, " ").trim(); }
function serializeRow(cells) {
  return "| " + cells.map(c => c.replace(/\\|/g, "\\\\|")).join(" | ") + " |";
}
function exportMarkdown() {
  const lines = DOC.lines.slice();
  [...DOC.tables].sort((a, b) => b.start - a.start).forEach(t => {
    const body = [...document.querySelectorAll(
      'table[data-t="' + t.t + '"] tbody tr')].map(
      tr => serializeRow(dataCells(tr).map(cellText)));
    lines.splice(t.start + 2, t.end - t.start - 2, ...body);
  });
  return lines.join("\\n");
}
function money(x) { return isFinite(x) ? x.toFixed(2) : ""; }
function recompute() {
  DOC.tables.forEach(t => {
    if (!t.computed) return;
    let total = 0;
    document.querySelectorAll('table[data-t="' + t.t + '"] tbody tr').forEach(tr => {
      const cells = dataCells(tr);
      const ext = tr.querySelector("td.ext");
      const v = parseFloat(cellText(cells[t.computed[0]]).replace(/,/g, "")) *
                parseFloat(cellText(cells[t.computed[1]]).replace(/,/g, ""));
      if (isFinite(v)) { ext.textContent = money(v); total += v; }
      else ext.textContent = "";
    });
    const tot = document.querySelector('table[data-t="' + t.t + '"] tfoot .total');
    if (tot) tot.textContent = money(total);
  });
}
function copyOut(btn, md) {
  const out = document.getElementById("out");
  out.value = md; out.style.display = "block";
  const done = () => { btn.textContent = "Copied ✓ — paste into the chat"; };
  const fallback = () => {
    btn.textContent = "Copy the block below, then paste into the chat";
    out.select();
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(md).then(done, fallback);
  } else { fallback(); }
}
document.addEventListener("input", recompute);
document.addEventListener("focusin", e => {
  /* select the cell's contents on focus: typing replaces the value (so the
     add-row "-" placeholder never concatenates), tabbing through loses nothing */
  const td = e.target;
  if (!td.isContentEditable || td.tagName !== "TD") return;
  const sel = window.getSelection(), r = document.createRange();
  r.selectNodeContents(td); sel.removeAllRanges(); sel.addRange(r);
});
document.addEventListener("click", e => {
  if (e.target.classList.contains("del")) {
    e.target.closest("tr").remove(); recompute(); return;
  }
  if (e.target.classList.contains("add")) {
    const t = DOC.tables.find(x => String(x.t) === e.target.dataset.t);
    const tr = document.createElement("tr");
    for (let i = 0; i < t.width; i++) {
      const td = document.createElement("td");
      td.contentEditable = "true"; td.textContent = "-"; tr.appendChild(td);
    }
    if (t.computed) {
      const td = document.createElement("td"); td.className = "ext"; tr.appendChild(td);
    }
    const ctl = document.createElement("td"); ctl.className = "ctl";
    ctl.innerHTML = '<button class="del" title="delete row">×</button>';
    tr.appendChild(ctl);
    document.querySelector('table[data-t="' + t.t + '"] tbody').appendChild(tr);
    recompute(); return;
  }
  if (e.target.id === "copy") { copyOut(e.target, exportMarkdown()); }
});
/* GRID-CORE end */
__SAVEJS__
recompute();
</script>
</body>
</html>
"""
