import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMPL = ROOT / "templates" / "calculator-plugin"


def test_template_is_a_valid_installable_plugin(tmp_path):
    dest = tmp_path / "calc-mine"
    shutil.copytree(TMPL, dest)
    manifest = json.loads((dest / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] and manifest["description"]
    assert manifest["author"]["name"]
    skills = list((dest / "skills").glob("*/SKILL.md"))
    assert skills, "template must ship at least one example skill"
    for sk in skills:
        head = sk.read_text(encoding="utf-8").splitlines()
        assert head[0] == "---" and any(l.startswith("name:") for l in head[:6])
