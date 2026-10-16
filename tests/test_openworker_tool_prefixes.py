"""Ported OpenWorker skills carry no BARE known MCP tool names (R12 item 4).

OpenWorker namespaces every MCP tool as ``mcp__<server>__<tool>``; a bare
name like ``list_bid_items`` would never resolve there. ``port_skills.py``
prefixes every name in its tool lists — this guard pins that invariant on
the committed port output: every listed tool name appears only prefixed.

(A skill mentioning a tool that is MISSING from the lists cannot be caught
here — keep the lists in ``openworker/port_skills.py`` current when a skill
starts calling a new BidSheet.ai tool.)
"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Load port_skills by path rather than sys.path surgery — a lingering
# `openworker/` on sys.path leaks into the session and can shadow later
# imports (order-dependent test failures).
_spec = importlib.util.spec_from_file_location(
    "openworker_port_skills", ROOT / "openworker" / "port_skills.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ARTIFACT_EDITOR = _mod.ARTIFACT_EDITOR
ARTIFACT_EDITOR_TOOLS = _mod.ARTIFACT_EDITOR_TOOLS
BIDMANAGER = _mod.BIDMANAGER
BIDMANAGER_TOOLS = _mod.BIDMANAGER_TOOLS

SERVERS = ((BIDMANAGER, BIDMANAGER_TOOLS), (ARTIFACT_EDITOR, ARTIFACT_EDITOR_TOOLS))


def test_ported_skills_have_no_bare_known_tool_names():
    skills = sorted((ROOT / "openworker" / "skills").glob("*/SKILL.md"))
    assert skills, "no ported skills found — run openworker/port_skills.py"

    bare: list[str] = []
    for skill_md in skills:
        text = skill_md.read_text(encoding="utf-8")
        for _server, tools in SERVERS:
            for tool in tools:
                # Same match rule as port_skills.namespace_tools: the
                # lookbehind on `_` skips already-prefixed occurrences
                # (mcp__<server>__<tool> puts a `_` right before the name).
                if re.search(rf"(?<![\w_]){re.escape(tool)}(?![\w])", text):
                    bare.append(f"{skill_md.parent.name}: {tool}")
    assert not bare, (
        "bare MCP tool names in ported skills (re-run "
        "`python openworker/port_skills.py`): " + ", ".join(bare)
    )


def test_feedback_tools_are_in_the_port_list():
    # The regression that motivated this guard: report-issue/triage-feedback
    # ported byte-identical because the feedback tools were missing.
    for tool in ("create_feedback_report", "list_feedback_reports",
                 "update_feedback_report"):
        assert tool in BIDMANAGER_TOOLS
