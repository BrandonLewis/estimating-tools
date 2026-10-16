"""Build the briefing-pack skeleton: scope, risks, structure list, and one
prompt file per structure with machine-readable frontmatter.

Pure file layout: stdlib + pyyaml. Never overwrites an existing file — the
project-briefing skill fills the prose and re-runs must not clobber it. The
frontmatter is the rollup + pricing contract downstream agents consume:
structure_id -> TakeoffRow.structure_id and create_structure's structure id
on the estimate item; count = how many of the structure the bid pays;
bid_items = the (schedule, item_number) rollup items its quantities pay into."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_SECTIONS = ("## Scope\n\n_(fill in)_\n\n## Geometry & layout\n\n_(fill in)_\n\n"
             "## Materials\n\n_(fill in)_\n\n## Quantities & pay items\n\n_(fill in)_\n\n"
             "## Risks\n\n_(fill in)_\n\n## Sources\n\n_(cite plan sheets / spec sections)_\n")

_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def _validate_structures(structures: list) -> None:
    """Ids become filenames and downstream keys — enforce kebab-case, no dupes."""
    seen = set()
    for s in structures:
        sid = s.get("id")
        if not isinstance(sid, str) or not _ID_RE.fullmatch(sid):
            raise ValueError(
                f"invalid structure id {sid!r} — expected kebab-case "
                "(lowercase letters, digits, hyphens), e.g. 'headwall-type-1'")
        if sid in seen:
            raise ValueError(f"duplicate structure id {sid!r}")
        seen.add(sid)


def _write_once(path: Path, text: str, created: list) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    created.append(path)


def _write_always(path: Path, text: str, created: list) -> None:
    """Regenerate a mechanical file; no-op when content is unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")
    created.append(path)


def build_briefing_pack(manifest, structures: list, base: Path) -> list:
    """Create Briefing/ under `base` (the bid working dir) for the given
    structures ([{id, name, count?, cost_codes?, bid_items?}]). Returns the
    paths created."""
    _validate_structures(structures)
    base = Path(base)
    created: list = []

    _write_once(base / "Briefing" / "scope.md",
                f"# Scope summary — {manifest.name}\n\n_(fill in: what is being bid, "
                "delivery method, owner/agency, key dates)_\n", created)
    _write_once(base / "Briefing" / "risks.md",
                f"# Risk notes — {manifest.name}\n\n_(fill in: access, utilities, "
                "water control, schedule, escalation, DBE, unusual spec sections)_\n", created)
    _write_always(base / "Briefing" / "structures.yaml",
                yaml.safe_dump({"structures": structures}, sort_keys=False,
                               allow_unicode=True), created)

    for s in structures:
        fm = {
            "structure_id": s["id"],
            "project": manifest.name,
            "organization_id": manifest.organization_id,
            "bm_project_id": manifest.bm_project_id,
            "count": s.get("count", 1),
            "bid_items": s.get("bid_items", []),
            "cost_codes": s.get("cost_codes", []),
        }
        text = ("---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
                + "---\n\n# Briefing — " + s.get("name", s["id"]) + "\n\n" + _SECTIONS)
        _write_once(base / "Briefing" / "prompts" / f"{s['id']}.md", text, created)

    return created
