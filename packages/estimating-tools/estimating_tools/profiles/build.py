"""Scaffold a new org profile directory — the create side of the profile system.

build_profile_dir is pure: it turns ProfileInputs into a {filename: content} map (a
schema-valid profile.yaml plus its asset files tree.yaml + letterhead.md), validated
against the existing profile.schema.json. The CLI/skill writes the map to disk."""
from __future__ import annotations

import json
from dataclasses import dataclass

import jsonschema
import yaml

from estimating_tools.profiles.loader import SCHEMA_PATH

_TREE_FILE = "tree.yaml"
_LETTERHEAD_FILE = "letterhead.md"

# A YAML list materialize_tree (est-scaffold) consumes; nest with `Name:` + children.
_DEFAULT_TREE = """\
# Project folder conventions — a YAML list. Nest with `Name:` and indented children.
- Bid Data
- Correspondence:
    - Owner
    - Subcontractors
- Estimates
- Plans and Specs
- Quotes
- Submittals
"""

_DEFAULT_LETTERHEAD = """\
# Company Letterhead

<!-- Starter letterhead template — edit freely. docgen renders documents from this. -->
<!-- The company name and address also live in profile.yaml under `letterhead`. -->
"""


@dataclass
class ProfileInputs:
    """The onboarding answers for a new org profile. `kind` is fixed to "org"."""

    name: str
    company_name: str = ""
    address: str = ""
    logo: str | None = None
    tree: str = ""
    letterhead: str = ""
    compliance_label: str = ""
    spec_note: str = ""
    naming: dict | None = None
    house_rules: list[dict] | None = None
    #: `estimating.format` — the org's estimate workbook format pack (a
    #: directory holding format.yaml; relative paths resolve against the
    #: profile directory). Without it every est-estimate verb falls to the
    #: bundled demo pack, which declares no capabilities and prices nothing
    #: real, so a profile that names no pack is a profile that does not yet
    #: produce the org's workbook.
    estimating_format: str = ""


def build_profile_dir(inputs: ProfileInputs) -> dict[str, str]:
    """Pure: ProfileInputs -> a {filename: content} map for a schema-valid org profile
    directory. Raises ValueError on a blank name or a schema violation. No file IO/MCP."""
    if not inputs.name or not str(inputs.name).strip():
        raise ValueError("name is required (a non-blank profile name)")

    letterhead = {"template": _LETTERHEAD_FILE}
    if str(inputs.company_name).strip():
        letterhead["company_name"] = str(inputs.company_name).strip()
    if str(inputs.address).strip():
        letterhead["address"] = str(inputs.address).strip()
    if inputs.logo and str(inputs.logo).strip():
        letterhead["logo"] = str(inputs.logo).strip()

    sections: dict = {
        "kind": "org",
        "name": str(inputs.name).strip(),
        "letterhead": letterhead,
        "folder_conventions": {"tree": _TREE_FILE},
    }
    argot = {}
    if str(inputs.compliance_label).strip():
        argot["compliance_label"] = str(inputs.compliance_label).strip()
    if str(inputs.spec_note).strip():
        argot["spec_note"] = str(inputs.spec_note).strip()
    if argot:
        sections["argot"] = argot
    if inputs.naming:
        sections["naming"] = inputs.naming
    if inputs.house_rules:
        sections["house_rules"] = inputs.house_rules
    if str(inputs.estimating_format).strip():
        sections["estimating"] = {"format": str(inputs.estimating_format).strip()}

    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(sections, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"profile invalid: {exc.message}") from exc

    tree = inputs.tree if str(inputs.tree).strip() else _DEFAULT_TREE
    letterhead_md = inputs.letterhead if str(inputs.letterhead).strip() else _DEFAULT_LETTERHEAD
    return {
        "profile.yaml": yaml.safe_dump(sections, sort_keys=False),
        _TREE_FILE: tree,
        _LETTERHEAD_FILE: letterhead_md,
    }
