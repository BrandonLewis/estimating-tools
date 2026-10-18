import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "manifest" / "generate.py"
PY = sys.executable


def run(*args, env=None):
    return subprocess.run([PY, str(GEN), *args], cwd=ROOT,
                          capture_output=True, text=True, env=env)


def generate(*args):
    """Run the generator and fail loudly if it did not succeed.

    Without this, a broken generator (bad YAML, missing dep, exception) exits
    nonzero but the test could still pass by reading stale committed output —
    defeating the purpose of a generator wiring test.
    """
    result = run(*args)
    assert result.returncode == 0, f"generate.py {args} failed (rc={result.returncode}):\n{result.stderr}"
    return result


def _import_generate():
    # Import the generator as a module so renderers can be exercised with a
    # patched environment without clobbering the committed output files.
    import importlib.util
    spec = importlib.util.spec_from_file_location("_gen_under_test", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_url_env_overrides_default_at_generation_time(monkeypatch):
    gen = _import_generate()
    server = {"id": "conformed", "url_env": "CONFORMED_MCP_URL",
              "url_default": "https://conformed.ai/mcp/"}
    monkeypatch.delenv("CONFORMED_MCP_URL", raising=False)
    assert gen._url(server) == "https://conformed.ai/mcp/"
    monkeypatch.setenv("CONFORMED_MCP_URL", "https://conformed.ai/mcp/")
    assert gen._url(server) == "https://conformed.ai/mcp/"


def test_url_env_absent_field_falls_back_to_default(monkeypatch):
    # A server without a url_env key must still resolve to its default.
    gen = _import_generate()
    assert gen._url({"url_default": "https://x/mcp/"}) == "https://x/mcp/"


def test_renderers_honour_url_env(monkeypatch):
    # Every renderer that emits a URL must reflect the override, not just Claude.
    gen = _import_generate()
    monkeypatch.setenv("BIDMANAGER_MCP_URL", "https://alt.example/mcp/")
    assert "https://alt.example/mcp/" in gen.render_claude()
    assert "https://alt.example/mcp/" in gen.render_cowork()
    assert "https://alt.example/mcp/" in gen.render_gemini()
    assert "https://alt.example/mcp/" in gen.render_cursor()
    assert "https://alt.example/mcp/" in gen.render_codex()
    assert "https://alt.example/mcp/" in gen.render_opencode()
    assert "https://alt.example/mcp/" in gen.render_managed()


def test_claude_mcp_json_is_oauth_primary_for_both_servers():
    generate("--client", "claude")
    cfg = json.loads((ROOT / "plugins/estimating-core/.mcp.json").read_text())
    # Standalone plugin .mcp.json is the FLAT shape: server names at the top level,
    # no "mcpServers" wrapper (matches every official plugin; claude-code#63694).
    servers = cfg
    assert "mcpServers" not in cfg, "plugin .mcp.json must be flat, not wrapped"
    # all three servers present (two http + the plugin-local stdio app server)
    assert set(servers) == {"bidmanager", "conformed", "artifact-editor"}
    for name, expected_url in (("bidmanager", "https://www.bidsheet.ai/mcp/"),
                               ("conformed", "https://conformed.ai/mcp/")):
        s = servers[name]
        assert s["type"] == "http"
        # Concrete URL — a plugin .mcp.json does NOT expand the bash "${VAR:-default}"
        # default syntax, so the URL must be literal (no "${" template) or it breaks.
        assert s["url"] == expected_url, s["url"]
        assert "${" not in s["url"], s["url"]
        # OAuth-primary: no Authorization header, no API key in the committed config
        assert "headers" not in s
    # no API-key material anywhere in the committed config
    assert "ApiKey" not in (ROOT / "plugins/estimating-core/.mcp.json").read_text()


def test_claude_mcp_json_includes_plugin_local_stdio_artifact_editor():
    generate("--client", "claude")
    cfg = json.loads((ROOT / "plugins/estimating-core/.mcp.json").read_text())
    entry = cfg["artifact-editor"]  # flat plugin .mcp.json (no "mcpServers" wrapper)
    assert entry["type"] == "stdio"
    assert "url" not in entry and "headers" not in entry
    # Self-locating launcher: the plugin-root path lives in command; an empty
    # args list is omitted entirely rather than emitted as [].
    assert "${CLAUDE_PLUGIN_ROOT}" in entry["command"]
    assert "args" not in entry


def test_remote_client_renders_skip_plugin_local_stdio_servers():
    # artifact-editor ships inside the claude plugin; remote clients can't launch it.
    for client, path in (("cowork", "it/cowork-connector.md"),
                         ("gemini", "it/gemini-settings.snippet.json"),
                         ("cursor", "it/cursor-mcp.json"),
                         ("codex", "it/codex-config.toml.snippet"),
                         ("opencode", "it/opencode.json"),
                         ("managed", "it/managed-mcp.json.tmpl")):
        generate("--client", client)
        assert "artifact-editor" not in (ROOT / path).read_text(), client


def test_cowork_doc_mentions_oauth_and_both_urls():
    generate("--client", "cowork")
    doc = (ROOT / "it/cowork-connector.md").read_text()
    assert "OAuth" in doc
    assert "https://www.bidsheet.ai/mcp/" in doc
    assert "https://conformed.ai/mcp/" in doc


def test_check_passes_when_committed_matches_then_fails_on_drift():
    for client in ("claude", "cowork", "gemini", "cursor", "codex", "opencode", "managed"):
        generate("--client", client)
    assert run("--check").returncode == 0
    mcp = ROOT / "plugins/estimating-core/.mcp.json"
    original = mcp.read_bytes()  # bytes: restore must not translate newlines on Windows
    try:
        mcp.write_bytes(original.replace(b"bidsheet.ai", b"drifted.example"))
        assert run("--check").returncode != 0
    finally:
        mcp.write_bytes(original)  # restore even if the assertion above fails


def test_managed_template_is_generated_and_drift_checked():
    generate("--client", "managed")
    path = ROOT / "it/managed-mcp.json.tmpl"
    servers = json.loads(path.read_text())["mcpServers"]
    remote = {name: value for name, value in json.loads(_import_generate().render_claude()).items()
              if value["type"] != "stdio"}
    assert servers == remote
    original = path.read_bytes()
    try:
        path.write_bytes(original.replace(b"conformed.ai", b"drifted.example"))
        assert run("--check").returncode != 0
    finally:
        path.write_bytes(original)


def test_gemini_settings_snippet_oauth_dynamic_discovery():
    generate("--client", "gemini")
    raw = (ROOT / "it/gemini-settings.snippet.json").read_text()
    servers = json.loads(raw)["mcpServers"]
    assert "bidmanager" in servers and "conformed" in servers
    for name, url in (("bidmanager", "https://www.bidsheet.ai/mcp/"),
                      ("conformed", "https://conformed.ai/mcp/")):
        s = servers[name]
        assert s["httpUrl"] == url
        assert s["oauth"]["authProviderType"] == "dynamic_discovery"
    # no secret/token material committed
    assert "Authorization" not in raw and "Bearer" not in raw and "secret" not in raw.lower()


def test_cursor_mcp_json_is_url_only_oauth():
    generate("--client", "cursor")
    raw = (ROOT / "it/cursor-mcp.json").read_text()
    servers = json.loads(raw)["mcpServers"]
    assert "bidmanager" in servers and "conformed" in servers
    for name, url in (("bidmanager", "https://www.bidsheet.ai/mcp/"),
                      ("conformed", "https://conformed.ai/mcp/")):
        assert servers[name]["url"] == url
        assert "headers" not in servers[name]   # interactive form is url-only
    assert "Authorization" not in raw and "secret" not in raw.lower()


def test_codex_config_snippet_bearer_token_env_var():
    # Assert against the TOML text (no tomllib — the repo supports Python 3.10, where it is absent).
    generate("--client", "codex")
    raw = (ROOT / "it/codex-config.toml.snippet").read_text()
    assert "[mcp_servers.bidmanager]" in raw and "[mcp_servers.conformed]" in raw
    assert 'url = "https://www.bidsheet.ai/mcp/"' in raw
    assert 'url = "https://conformed.ai/mcp/"' in raw
    assert 'bearer_token_env_var = "BIDMANAGER_BEARER"' in raw
    assert 'bearer_token_env_var = "CONFORMED_BEARER"' in raw
    # only the env var NAME, never a token value
    assert "secret" not in raw.lower()


def test_opencode_json_is_remote_oauth_primary():
    generate("--client", "opencode")
    raw = (ROOT / "it/opencode.json").read_text()
    cfg = json.loads(raw)
    assert cfg["$schema"] == "https://opencode.ai/config.json"
    servers = cfg["mcp"]
    assert set(servers) == {"bidmanager", "conformed"}
    for name, url in (("bidmanager", "https://www.bidsheet.ai/mcp/"),
                      ("conformed", "https://conformed.ai/mcp/")):
        s = servers[name]
        assert s == {"type": "remote", "url": url, "enabled": True}
    # OAuth-primary like Cursor: no header, no token material committed
    assert "Authorization" not in raw and "Bearer" not in raw and "secret" not in raw.lower()
