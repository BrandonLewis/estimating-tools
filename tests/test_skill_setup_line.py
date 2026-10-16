"""Every estimating-core skill that uses estimating_tools carries the install fallback."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "estimating-core" / "skills"

SETUP_LINE = (
    "> **Setup:** the `est-*` tools are **not on `PATH`** — every command below names its "
    "shim under `~/.estimating/bin/`, which this plugin's SessionStart hook creates. "
    "If a shim is missing, run `python <plugin-root>/scripts/ensure_tools.py` "
    "(the plugin root is this skill's directory's grandparent); it builds the shared "
    "runtime and prints one line saying what happened. Then retry."
)

_TRIGGER = re.compile(
    r"estimating_tools|\b(est-import|est-estimate|est-takeoff|est-gantt|est-scaffold|"
    r"est-intake|est-sheets|est-rebar|est-hist|est-quotespace|est-bim|est-letterhead|dir-sync|asm-import|dir-import|rate-import|costcode-import|profile-init|m2m-token)\b"
)


def test_skills_referencing_the_package_carry_the_setup_line():
    missing, duplicated, stale = [], [], []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        uses_package = bool(_TRIGGER.search(text.replace(SETUP_LINE, "")))
        n = text.count(SETUP_LINE)
        if not uses_package:
            if n:
                stale.append(skill_md.parent.name)
            continue
        if n == 0:
            missing.append(skill_md.parent.name)
        elif n > 1:
            duplicated.append(skill_md.parent.name)
    assert not missing, f"skills missing the canonical setup line: {missing}"
    assert not duplicated, f"skills with duplicate setup lines: {duplicated}"
    assert not stale, f"skills carry the setup line but no longer reference the package: {stale}"
