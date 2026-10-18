"""The OpenCode port: `port_skills.ported_skills(port_skills.port_body_opencode)`,
the library `opencode/install.py` installs from (there is no CLI target).

OpenCode loads the same SKILL.md folders but names an MCP tool
`<server>_<tool>` (sanitize(server) + "_" + sanitize(tool), where sanitize
keeps [A-Za-z0-9_-]), not OpenWorker's `mcp__<server>__<tool>`, and has no
`load_skill` resources_path. Copying the OpenWorker port unchanged ships
workflows that name tools OpenCode never registers (PR #358 review).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "openworker"))
import port_skills  # noqa: E402

# OpenCode's skill-name rule (docs: name must match the directory and this).
OPENCODE_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@pytest.fixture(scope="module")
def ported(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("opencode-skills")
    for name, src, text, _stats, refs in port_skills.ported_skills(
            port_skills.port_body_opencode):
        (out / name).mkdir()
        (out / name / "SKILL.md").write_text(text, encoding="utf-8")
        for ref in refs:
            dest = out / name / ref.relative_to(src.parent)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(ref.read_bytes())
    return out


def _skills(out: Path) -> list[Path]:
    return sorted(out.glob("*/SKILL.md"))


def test_every_plugin_skill_is_written(ported: Path):
    sources = sorted(REPO_ROOT.glob(port_skills.SRC_GLOB))
    assert len(_skills(ported)) == len(sources) > 0


def test_tool_names_use_opencodes_server_underscore_tool_form(ported: Path):
    text = (ported / "estimate-project" / "SKILL.md").read_text(encoding="utf-8")
    assert "bidmanager_get_project" in text
    for path in _skills(ported):
        body = path.read_text(encoding="utf-8")
        assert "mcp__" not in body, f"{path.parent.name}: OpenWorker namespace leaked"
        for tool in port_skills.BIDMANAGER_TOOLS:
            for m in re.finditer(rf"(?<![\w-]){re.escape(tool)}(?![\w])", body):
                prefix = body[max(0, m.start() - len("bidmanager_")):m.start()]
                assert prefix == "bidmanager_", f"{path.parent.name}: bare {tool}"


def test_artifact_editor_tools_keep_the_hyphenated_server_name(ported: Path):
    bodies = "".join(p.read_text(encoding="utf-8") for p in _skills(ported))
    assert "artifact-editor_open_artifact_editor" in bodies


def test_names_match_opencodes_rule_and_directory(ported: Path):
    for path in _skills(ported):
        name = port_skills.frontmatter_name(path.read_text(encoding="utf-8"))
        assert name == path.parent.name
        assert OPENCODE_NAME.match(name), name


def test_setup_line_needs_no_openworker_resources_path(ported: Path):
    for path in _skills(ported):
        body = path.read_text(encoding="utf-8")
        assert "<resources_path>" not in body and "load_skill" not in body, path.parent.name
        assert "${CLAUDE_PLUGIN_ROOT}" not in body, path.parent.name
        assert "<plugin-root>" not in body and "ensure_tools.py" not in body, path.parent.name
    setup = (ported / "capture-quote" / "SKILL.md").read_text(encoding="utf-8")
    assert port_skills.OPENCODE_SETUP_LINE in setup
    assert "opencode/install.py" in port_skills.OPENCODE_SETUP_LINE
    # No venv, no "start OpenCode from this shell": the installer owns the runtime.
    assert "venv" not in port_skills.OPENCODE_SETUP_LINE
    assert "pip install" not in port_skills.OPENCODE_SETUP_LINE


def test_shim_paths_are_kept_like_claude_code(ported: Path):
    """opencode/install.py builds the shared ~/.estimating runtime, so every
    `~/.estimating/bin/<tool>` a source skill names must survive the port
    verbatim -- stripping them (the OpenWorker rule) would send the agent to a
    bare `est-bim` that is not on PATH."""
    checked = 0
    for name, src, *_ in port_skills.ported_skills(port_skills.port_body_opencode):
        source = src.read_text(encoding="utf-8")
        body = (ported / name / "SKILL.md").read_text(encoding="utf-8")
        for m in re.finditer(r"~/\.estimating/bin/[\w-]+", source):
            assert m.group(0) in body, f"{name}: {m.group(0)} stripped"
            checked += 1
    assert checked > 50, "the walk found almost no shim paths -- it is broken"
    bimsheet = (ported / "draw-structure-sheet" / "SKILL.md").read_text(encoding="utf-8")
    assert "~/.estimating/bin/est-sheets" in bimsheet
    assert "~/.estimating/bin/est-python" in "".join(
        p.read_text(encoding="utf-8") for p in _skills(ported))


def test_no_openworker_display_note(ported: Path):
    bodies = "".join(p.read_text(encoding="utf-8") for p in _skills(ported))
    assert "On OpenWorker" not in bodies


def test_references_ride_along(ported: Path):
    assert (ported / "build-estimate-workbook" / "references").is_dir()


def test_there_is_no_opencode_cli_target(capsys):
    """One supported path: opencode/install.py writes the ownership marker a
    re-run needs; a CLI write to --out would bypass it."""
    for argv in (["--target", "opencode"], ["--out", "x"]):
        with pytest.raises(SystemExit):
            port_skills.main(argv)
    capsys.readouterr()


@pytest.mark.parametrize("token", ["${CLAUDE_PLUGIN_ROOT}", "<plugin-root>"])
def test_a_plugin_root_outside_the_setup_line_fails_the_port(token):
    body = f"---\nname: x\n---\n\nRun `python {token}/scripts/thing.py`.\n"
    with pytest.raises(ValueError, match="OpenCode"):
        port_skills.port_body_opencode(body)
    # The setup line itself names the plugin root and is rewritten, not refused.
    ok = ("---\nname: x\n---\n\n"
          "> **Setup:** run `python <plugin-root>/scripts/ensure_tools.py`.\n")
    assert "<plugin-root>" not in port_skills.port_body_opencode(ok)[0]
