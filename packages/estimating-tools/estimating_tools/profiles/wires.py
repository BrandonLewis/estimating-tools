"""Project a resolved Profile onto consumer-shaped values.

These helpers return plain values (dicts / paths) so consumer modules
(lighting, docgen) never import the profile system — the agnostic core stays
unaware of profiles.
"""
from __future__ import annotations

from pathlib import Path

from estimating_tools.profiles.model import Profile

_ARGOT_KEYS = ("compliance_label", "spec_note")


def to_calc_meta(profile: Profile) -> dict:
    """The agency-argot subset of a lighting calc-sheet `meta` dict.

    Returns only the keys present in the profile's `argot` section. The caller
    merges this into the full meta it passes to `write_calc_sheet`; an empty
    profile yields `{}`, so the calc sheet renders its agnostic defaults.
    """
    argot = profile.section("argot")
    return {key: argot[key] for key in _ARGOT_KEYS if key in argot}


def to_letterhead(profile: Profile) -> tuple[Path, dict]:
    """Resolve a profile's letterhead into (template_path, frontmatter).

    `template_path` is the absolute path the loader resolved; `frontmatter` is
    every other `letterhead` field (company_name, address, logo, ...), ready to
    pass to `docgen.docxtpl_engine.render_letterhead`. Raises ValueError if the
    profile has no letterhead.template, FileNotFoundError if the file is absent.
    """
    letterhead = profile.section("letterhead")
    template = letterhead.get("template")
    if not template:
        raise ValueError("profile has no letterhead.template")
    template_path = Path(template)
    if not template_path.is_file():
        raise FileNotFoundError(f"letterhead template not found: {template_path}")
    frontmatter = {key: value for key, value in letterhead.items() if key != "template"}
    return template_path, frontmatter


def cad_style_pack() -> str | None:
    """The active profile's ``cad_style_pack`` spec, or None.

    Registered as bimforge's ``bimforge.style_packs`` entry point (see
    pyproject), so bimforge resolves an org's CAD styling through the profile
    cascade without importing this package. None when ESTIMATING_PROFILES is
    unset or no profile carries the key; bimforge treats a raise the same way.
    """
    from estimating_tools.profiles.loader import load

    value = load().data.get("cad_style_pack")
    return value if isinstance(value, str) and value else None
