import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
IT = ROOT / "it"


def _load(name):
    return json.loads((IT / name).read_text())


def test_managed_mcp_references_manifest_server_url():
    mcp = _load("managed-mcp.json.tmpl")
    manifest = yaml.safe_load((ROOT / "manifest/servers.manifest.yaml").read_text())
    expected = {s["id"]: {"type": s["transport"], "url": s["url_default"]}
                for s in manifest["servers"]
                if s["transport"] == "http" and "claude" in s.get("clients", ["claude"])}
    assert mcp["mcpServers"] == expected


def test_managed_settings_enables_our_plugins_and_marketplace():
    ms = _load("managed-settings.snippet.json")
    assert "extraKnownMarketplaces" in ms
    enabled = ms["enabledPlugins"]
    for name in ["estimating-core"]:
        assert any(k.startswith(name + "@") for k in enabled), name
    assert any("bidsheet.ai" in u for u in ms["allowedMcpServers"])


def test_profile_managed_settings_sets_estimating_profiles():
    ms = _load("profile-managed-settings.snippet.json")
    env = ms["env"]
    assert "ESTIMATING_PROFILES" in env
    # Ordered cascade: a path list joined by ':' (documented POSIX example).
    paths = [p for p in env["ESTIMATING_PROFILES"].split(":") if p]
    assert len(paths) >= 2  # ordered cascade of multiple profile dirs
