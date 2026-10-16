"""Every skill referenced by a shipped SKILL.md exists, and cross-plugin
references name the target's plugin (issue #88 EP-8: five estimating-core
skills routed readers to calc-bim skills without ever saying calc-bim,
which reads as 'the capability does not exist' on a machine that only has
estimating-core installed)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"

# `name` skill / `name` skill's / skill `name` — the phrasing every shipped
# SKILL.md uses when it means "another skill" (bare backticked kebab-case is
# too ambiguous: CLI subcommands, automations, and concepts all use it).
_REF = re.compile(r"`([a-z][a-z0-9-]{2,})`(?:'s)?\s+skill\b|\bskill\s+`([a-z][a-z0-9-]{2,})`")

# Words that follow "skill" in prose without naming one.
_NOISE = {"the", "this", "that", "a", "an"}


def _skill_homes() -> dict:
    homes = {}
    for skill_dir in PLUGINS.glob("*/skills/*"):
        if (skill_dir / "SKILL.md").is_file():
            homes[skill_dir.name] = skill_dir.parent.parent.name
    return homes


def test_skill_references_resolve_and_cross_plugin_refs_name_the_plugin():
    homes = _skill_homes()
    assert homes, "no skills found — wrong ROOT?"
    dangling, unnamed = [], []
    for skill_md in sorted(PLUGINS.glob("*/skills/*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        this_plugin = skill_md.parent.parent.parent.name
        rel = skill_md.relative_to(ROOT)
        for match in _REF.finditer(text):
            name = match.group(1) or match.group(2)
            if name in _NOISE:
                continue
            if name not in homes:
                dangling.append(f"{rel}: `{name}`")
                continue
            target_plugin = homes[name]
            if target_plugin != this_plugin and target_plugin not in text:
                unnamed.append(f"{rel}: `{name}` lives in {target_plugin}")
    assert not dangling, (
        "SKILL.md references skills that do not exist in any plugin:\n  "
        + "\n  ".join(dangling))
    assert not unnamed, (
        "cross-plugin skill references must name the target plugin somewhere "
        "in the referencing file:\n  " + "\n  ".join(unnamed))
