"""The read-back report, in Markdown: what changed, what needs the estimator, what was ignored."""
from __future__ import annotations


#: Every package sheet is titled "Sub <package>" (`package_frames`).
_PACKAGE_SHEET_PREFIX = "Sub "


def render_report(result, *, workbook: str, spec: str) -> str:
    f = result.findings
    writes = getattr(result, "quote_writes", None) or []
    out = [f"# Read-back: {workbook} → {spec}", ""]
    counts = (f"changes: {len(f.changes)} · need a rate: {len(f.needs_rate)} · "
              f"formula cells typed over: {len(f.overwrites)} · untagged rows: {len(f.untagged)} · "
              f"problems: {len(f.problems)}")
    out += [counts, ""]
    if not (f.changes or f.needs_rate or f.overwrites or f.untagged or f.notices or f.problems
            or writes or f.quote_edits):
        out += ["No changes: the workbook matches the spec.", ""]
        return "\n".join(out)

    def section(title, lines, why=None):
        if not lines:
            return
        out.extend([f"## {title}", ""])
        if why:
            out.extend([why, ""])
        out.extend(f"- {line}" for line in lines)
        out.append("")

    section("Problems — nothing is written until these are fixed", f.problems,
            "Fix them in the workbook, save, and read it back again.")
    section("Changes", f.changes)
    # Work packages: the selections read back, the quote files the CLI
    # writes, and the package sheets' own problems (also listed above).
    section("Packages",
            [c for c in f.changes if c.startswith("packages · ")]
            + [f"quote files to write: {w.file_name} ({w.reason})" for w in writes]
            + [f"quote edits written: {e}" for e in f.quote_edits]
            + [p for p in f.problems if p.startswith(_PACKAGE_SHEET_PREFIX)])
    section("Needs you: resources with no rate",
            [f"{name} — used in {', '.join(where)}" for name, where in f.needs_rate.items()],
            "Applied as typed, but nothing prices them: give each a rate on the Rates sheet "
            "(above the marker row) and read back again. Until then check 2 shows ✗.")
    section("Formula cells typed over — ignored, the rebuild restores them", f.overwrites)
    section("Untagged rows — not read (never guessed)", f.untagged,
            "These rows carry no kind tag, so they were pasted from outside the workbook. "
            "Copy a row of the right kind (crew, cost line) inside a task block and type "
            "the values into it instead.")
    section("Notices", f.notices)
    return "\n".join(out)
