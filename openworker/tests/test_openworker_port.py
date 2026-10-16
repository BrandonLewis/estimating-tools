"""Contract tests for the OpenWorker port.

OpenWorker is not a dependency of this repo, so the checks that matter are the
ones that would only fail *inside* OpenWorker: its skill frontmatter parser is
line-based rather than YAML, its persona manifest validator is strict, and its
MCP tool namespace is derived from the config key. Each rule below is
reimplemented from the named upstream source so a drift shows up here.

Upstream (github.com/andrewyng/openworker, commit db93d75):
  coworker/skills/base.py::_parse_skill
  coworker/personas/manifest.py::parse_manifest
  coworker/catalog.py::CATALOG
  coworker/mcp/tools.py::tool_name
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
PERSONAS = ROOT / "personas"
MCP = ROOT / "mcp" / "mcpServers.json"
PAYLOADS = ROOT / "automations" / "payloads"
PLUGIN_SKILLS = ROOT.parent / "plugins"

sys.path.insert(0, str(ROOT))
import port_skills  # noqa: E402

# coworker/catalog.py — the catalog is closed; a persona referencing anything
# else raises ManifestError at load and the whole install fails.
CATALOG = {"code_files", "files", "git", "search", "shell", "todo"}
VALID_FAMILIES = {"code", "knowledge"}
VALID_MODES = {"discuss", "plan", "interactive", "custom", "auto"}
VALID_REC_TIERS = {"core", "optional"}
PERSONA_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def skill_files() -> list[Path]:
    return sorted(SKILLS.glob("*/SKILL.md"))


def persona_files() -> list[Path]:
    return sorted(PERSONAS.glob("*.md"))


def parse_skill_like_openworker(text: str) -> dict:
    """Reimplementation of coworker/skills/base.py::_parse_skill.

    Deliberately line-based, not YAML: upstream splits each frontmatter line on
    the first ':' and ignores lines without one. A folded or multi-line value
    therefore silently loses everything after its first line.
    """
    name, description, allowed, body = None, "", [], text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in frontmatter.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key, value = key.strip().lower(), value.strip()
                if key == "name" and value:
                    name = value
                elif key == "description":
                    description = value
                elif key in ("allowed-tools", "allowed_tools"):
                    allowed = [t.strip() for t in value.split(",") if t.strip()]
    return {"name": name, "description": description,
            "allowed_tools": allowed, "body": body.strip()}


# -- skills --------------------------------------------------------------------
def test_skills_exist():
    assert len(skill_files()) >= 25, "the ported skill library looks truncated"


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_parses_with_openworker_loader(path: Path):
    parsed = parse_skill_like_openworker(path.read_text(encoding="utf-8"))
    assert parsed["name"], f"{path}: no `name:` — the loader would fall back to the dir name"
    assert parsed["description"], f"{path}: no `description:` — it would show blank in the catalog"
    assert parsed["body"], f"{path}: empty body — load_skill would return nothing"


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_dir_matches_frontmatter_name(path: Path):
    """install.py copies by directory name; the loader keys by frontmatter name.
    If they disagree the skill is discoverable under one name and installed under
    another, which makes `load_skill(<catalog name>)` fail to find its resources."""
    parsed = parse_skill_like_openworker(path.read_text(encoding="utf-8"))
    assert parsed["name"] == path.parent.name


def test_no_duplicate_skill_names():
    """SkillLoader stores skills in one flat dict — a collision silently drops one."""
    names = [parse_skill_like_openworker(p.read_text(encoding="utf-8"))["name"]
             for p in skill_files()]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate skill names: {sorted(dupes)}"


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
def test_no_claude_code_plugin_references(path: Path):
    text = path.read_text(encoding="utf-8")
    for token in ("${CLAUDE_PLUGIN_ROOT}", "<plugin-root>"):
        assert token not in text, f"{path}: {token} has no meaning under OpenWorker"


# Every MCP tool the ported skills may call. Sourced from port_skills.py rather
# than restated here: a second hand-maintained copy cannot detect that the first
# one is INCOMPLETE, which is the failure mode that actually bites (a name absent
# from both lists ships bare and silently fails to resolve at runtime).
# test_no_unlisted_tool_names_in_plugin_sources below is the guard for that.
MCP_TOOLS = list(port_skills.BIDMANAGER_TOOLS) + list(port_skills.ARTIFACT_EDITOR_TOOLS)


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
def test_mcp_tool_names_are_namespaced(path: Path):
    text = path.read_text(encoding="utf-8")
    bare = [t for t in MCP_TOOLS
            if re.search(rf"(?<![\w_]){re.escape(t)}(?![\w])", text)]
    assert not bare, (
        f"{path}: un-namespaced MCP tool name(s) {bare} — OpenWorker exposes these "
        f"as mcp__<server>__<tool>. Re-run `python openworker/port_skills.py`."
    )


# In-process helpers from the bundled `estimating_tools` wheel. They read like
# tool calls in the skill bodies but are plain Python, so namespacing them would
# be wrong. Verified against the wheel: each is a `def` in estimating_tools/.
LOCAL_HELPERS = {
    "calculate_takeoff",                  # estimating_tools/takeoff/core.py
    "convert_units",                      # estimating_tools/takeoff/core.py
    "check_dbe_requirements",             # estimating_tools/takeoff/core.py
    "diff_new_items",                     # estimating_tools/importers/push.py
    "plan_takeoff_push",                  # estimating_tools/takeoff/push.py
    "build_profile_dir",                  # estimating_tools/profiles/build.py
    "build_spread",                       # estimating_tools/spreads/level.py
    "build_item_spread",                  # estimating_tools/spreads/item_quotes.py
    "build_coverage",                     # estimating_tools/quotespace/coverage.py
    "build_assembly_library_from_excel",  # estimating_tools/assemblies/excel.py
    "build_cost_code_system_from_excel",  # estimating_tools/costcodes/excel.py
    "build_directory_from_excel",         # estimating_tools/directory/excel.py
    "build_rate_library_from_excel",      # estimating_tools/rates/excel.py
    "add_reinforcing_bars",               # estimating_tools/rebar/ifc.py
}

# Third-party API methods the skills mention in prose — not estimating_tools
# functions, not MCP tools; the port must never namespace them.
THIRD_PARTY_METHODS = {
    "get_text",                           # PyMuPDF Page method (pdf-extraction CAD-plotted-sheet note)
}

# Names that LOOK tool-shaped to _TOOL_ISH but are not callables at all —
# backticked YAML keys and field names. `open` has to stay a verb in the
# pattern for `open_artifact_editor`, so this is where its collateral lands.
NOT_CALLABLES = {
    "open_questions",                     # read-station-plans: a YAML key
}

# Tools on MCP servers this port does NOT configure (openworker/mcp/
# mcpServers.json has no entry, so port_skills.py cannot know the tool
# prefix — OpenWorker derives it from the config key the *user* chose).
# The skills reference these conditionally ("if the Gmail MCP is
# connected") and must ship them bare, not namespaced.
FOREIGN_MCP_TOOLS = {
    "create_draft",                       # Gmail MCP (solicit-quotes ITB drafts)
}

# A backticked snake_case identifier opening with a verb — how the skills write
# MCP tool names.
_TOOL_ISH = re.compile(
    r"`[^`\n]*?(?<![\w_])((?:list|get|create|update|delete|search|find|add|remove|assign|"
    r"clone|price|build|prepare|analyze|bulk|allocate|recalculate|save|instantiate|open)"
    r"_[a-z0-9_]+)(?![\w])"
)


def test_no_unlisted_tool_names_in_plugin_sources():
    """Catch names port_skills.py has never heard of.

    The namespacing pass only rewrites what BIDMANAGER_TOOLS lists, so a tool the
    list is missing ports through bare and dies at call time under OpenWorker.
    Scanning the *sources* for tool-shaped names is the only check that sees it.
    New entry here means: add it to BIDMANAGER_TOOLS, to LOCAL_HELPERS if it
    is in-process Python, to FOREIGN_MCP_TOOLS if it lives on an MCP server
    this port does not configure, or to NOT_CALLABLES if it is not a callable
    at all (a backticked YAML key the pattern cannot tell from a tool).
    """
    known = (set(MCP_TOOLS) | LOCAL_HELPERS | FOREIGN_MCP_TOOLS
             | THIRD_PARTY_METHODS | NOT_CALLABLES)
    unlisted: dict[str, set[str]] = {}
    for src in sorted(PLUGIN_SKILLS.glob("*/skills/*/SKILL.md")):
        for m in _TOOL_ISH.finditer(src.read_text(encoding="utf-8")):
            if m.group(1) not in known:
                unlisted.setdefault(m.group(1), set()).add(src.parent.name)
    assert not unlisted, (
        "tool-shaped names unknown to port_skills.py: "
        + "; ".join(f"{n} ({', '.join(sorted(s))})" for n, s in sorted(unlisted.items()))
    )


def test_port_is_up_to_date():
    """The committed skills must match what port_skills.py produces from the sources."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "port_skills.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT.parent,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wheel_is_bundled():
    """The skills' install fallback points at skills/_dist — it has to be there."""
    assert list((SKILLS / "_dist").glob("estimating_tools-*.whl"))


# -- personas ------------------------------------------------------------------
def test_persona_files_exist():
    assert persona_files(), "no persona manifests to install"


def test_persona_dir_contains_only_manifests():
    """install_from_dir globs *.md and raises ManifestError on the first file that
    is not a valid manifest — one stray README would fail the whole install."""
    for path in PERSONAS.glob("*"):
        assert path.suffix == ".md", f"{path} would be globbed or ignored unexpectedly"


@pytest.mark.parametrize("path", persona_files(), ids=lambda p: p.stem)
def test_persona_manifest_validates(path: Path):
    yaml = pytest.importorskip("yaml")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), "manifest must open with a YAML frontmatter block"
    end = text.find("\n---", 3)
    assert end != -1, "unterminated frontmatter block"
    meta = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4:].lstrip("\n")

    assert isinstance(meta, dict), "frontmatter must be a mapping"
    assert body.strip(), "a persona's body IS its system prompt; it cannot be empty"

    pid = str(meta.get("id") or "").strip()
    assert PERSONA_ID_RE.match(pid), f"invalid persona id {pid!r} (it becomes a directory name)"
    assert meta.get("family") in VALID_FAMILIES, f"family must be one of {sorted(VALID_FAMILIES)}"

    mode = str(meta.get("default_permission_mode", "interactive")).strip().lower()
    assert mode in VALID_MODES, f"default_permission_mode must be one of {sorted(VALID_MODES)}"

    tools = meta.get("tools") or []
    unknown = [t for t in tools if t not in CATALOG]
    assert not unknown, f"unknown capabilities {unknown}; the catalog is closed: {sorted(CATALOG)}"

    for item in meta.get("recommends") or []:
        assert isinstance(item, dict), "each `recommends` item must be a mapping"
        assert "connector" in item or "mcp" in item, "needs a `connector:` or `mcp:` key"
        tier = str(item.get("tier", "optional")).strip().lower()
        assert tier in VALID_REC_TIERS, f"tier must be one of {sorted(VALID_REC_TIERS)}"


@pytest.mark.parametrize("path", persona_files(), ids=lambda p: p.stem)
def test_persona_skill_references_exist(path: Path):
    """`skills:` is advisory upstream (parsed, shown at consent, not enforced), but a
    name that matches nothing installed is a documentation bug either way."""
    yaml = pytest.importorskip("yaml")
    text = path.read_text(encoding="utf-8")
    meta = yaml.safe_load(text[3:text.find("\n---", 3)]) or {}
    installed = {p.parent.name for p in skill_files()}
    missing = [s for s in (meta.get("skills") or []) if s not in installed]
    assert not missing, f"{path.stem} lists skills that are not in openworker/skills: {missing}"


@pytest.mark.parametrize("path", persona_files(), ids=lambda p: p.stem)
def test_persona_mcp_references_are_configured(path: Path):
    yaml = pytest.importorskip("yaml")
    text = path.read_text(encoding="utf-8")
    meta = yaml.safe_load(text[3:text.find("\n---", 3)]) or {}
    configured = set(json.loads(MCP.read_text(encoding="utf-8"))["mcpServers"])
    for item in meta.get("recommends") or []:
        ref = item.get("mcp")
        if ref and item.get("tier") == "core":
            assert ref in configured, (
                f"{path.stem} recommends MCP server {ref!r} as core, but install.py "
                f"does not configure it (configured: {sorted(configured)})"
            )


# -- mcp -----------------------------------------------------------------------
def test_mcp_config_shape():
    cfg = json.loads(MCP.read_text(encoding="utf-8"))
    servers = cfg["mcpServers"]
    assert "bidmanager" in servers, (
        "the ported skills call mcp__bidmanager__* — the config key must be `bidmanager`"
    )
    for name, spec in servers.items():
        assert not name.startswith("_")
        if spec.get("url"):
            assert spec.get("type") in {"http", "https", "sse",
                                        "streamable-http", "streamable_http"}
            assert spec["url"].startswith("https://"), f"{name}: refuse plaintext MCP transport"
        else:
            assert spec.get("command"), f"{name}: a stdio server needs a command"
        # OpenWorker sanitizes names to [A-Za-z0-9_-]; anything else would be
        # rewritten and the skills' hardcoded prefixes would stop matching.
        assert re.fullmatch(r"[A-Za-z0-9_-]+", name), f"{name} would be rewritten by tool_name()"


def test_artifact_editor_is_not_configured():
    """It is an MCP App: its list_tools returns [] unless the host declares
    io.modelcontextprotocol/ui, and OpenWorker's MCP client is tools-only. Shipping
    it would spawn a stdio process that contributes nothing."""
    servers = json.loads(MCP.read_text(encoding="utf-8"))["mcpServers"]
    assert "artifact-editor" not in servers


# -- automations ---------------------------------------------------------------
@pytest.mark.parametrize("path", sorted(PAYLOADS.glob("*.json")), ids=lambda p: p.stem)
def test_automation_payload_shape(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d.get("title", "").strip(), "title is required"
    assert d.get("instructions", "").strip(), "instructions are required"
    assert d.get("cron") or d.get("fire_at"), "need a cron or a fire_at"
    if d.get("cron"):
        assert len(d["cron"].split()) == 5, f"cron must have 5 fields: {d['cron']!r}"
    # grant_entries drops anything that is not a target-bound write, fail-closed.
    for perm in d.get("permissions") or []:
        assert perm.get("access") in {"read", "write"}
        if perm["access"] == "write":
            assert perm.get("tool") and perm.get("target"), "a write grant needs tool + exact target"
