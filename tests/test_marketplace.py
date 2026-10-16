import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_marketplace_lists_known_plugins_with_resolvable_sources():
    mp = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    names = {p["name"] for p in mp["plugins"]}
    assert {"estimating-core", "calc-bim"} <= names
    for p in mp["plugins"]:
        src = p["source"]
        # The Claude plugin schema requires a relative-path source to start with "./";
        # a bare "plugins/foo" is rejected at `/plugin marketplace add` time (Invalid input).
        assert isinstance(src, str) and src.startswith("./"), f"{p['name']}: source must start with './' (got {src!r})"
        assert (ROOT / src / ".claude-plugin" / "plugin.json").is_file(), p["name"]


def test_no_monolith_manifest_remains():
    assert not (ROOT / ".claude-plugin" / "plugin.json").exists()
