"""Every estimating-core skill that renders an artifact carries the display contract."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "estimating-core" / "skills"

DISPLAY_CONTRACT = (
    "> **Display contract:** Show `render` output to the user **verbatim in a fenced "
    "code block** — never reformat it, add/remove columns, or substitute your own "
    "table; `parse` depends on the exact shape. If the `open_artifact_editor` tool "
    "(artifact-editor server) is available, ALSO call it — "
    "`open_artifact_editor(markdown=<rendered, verbatim>, title=\"<title>\", "
    "editable=<false for read-only plan renders>)` — and tell the user to edit in "
    "the inline panel and click **Save & send to chat**; their edits arrive as a "
    "chat message. In the terminal, the same tool instead opens the editor in the "
    "user's web browser and returns the saved block directly in the tool result — "
    "parse and push it when it returns (Save = the user's consent). If the wait "
    "expires, call `collect_artifact_edits` after the user says they've saved. If "
    "the tool is missing or errors, show the live page built by:\n"
    ">\n"
    "> ```python\n"
    "> from estimating_tools.artifacts_html import to_editable_html\n"
    '> page = to_editable_html(rendered, title="<title>")\n'
    "> ```\n"
    ">\n"
    "> Prefer the host's native artifact mechanism (present `page` as a live HTML "
    "artifact); if the host only renders files, write it to `<slug>.artifact.html` "
    "(named after the artifact so successive renders don't overwrite each other). For "
    "editable artifacts, point the user at the page's **Copy edited artifact** button; "
    "for read-only plan renders, pass `editable=False` (the page has no button). Run "
    "`parse` only on text the user provides — the Save message, the pasted export, or "
    "their edited block — never on your own restatement of it."
)

# render_letterhead is the docgen DOCX writer, not the artifact render/parse
# flow this contract governs — exclude it (first false positive: draft-an-rfi).
_RENDER_CALL = re.compile(r"\brender(?!_letterhead\()[a-z_]*\(")


def test_render_emitting_skills_carry_the_display_contract():
    missing, duplicated, stale = [], [], []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        # normalize CRLF so an autocrlf checkout (Windows) matches the LF constant
        text = skill_md.read_text(encoding="utf-8").replace("\r\n", "\n")
        renders = bool(_RENDER_CALL.search(text.replace(DISPLAY_CONTRACT, "")))
        n = text.count(DISPLAY_CONTRACT)
        if not renders:
            if n:
                stale.append(skill_md.parent.name)
            continue
        if n == 0:
            missing.append(skill_md.parent.name)
        elif n > 1:
            duplicated.append(skill_md.parent.name)
    assert not missing, f"render-emitting skills missing the display contract: {missing}"
    assert not duplicated, f"skills with duplicate display contracts: {duplicated}"
    assert not stale, f"skills carry the contract but no longer render artifacts: {stale}"
