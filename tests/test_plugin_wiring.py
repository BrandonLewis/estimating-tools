"""The artifact-editor MCP server is wired into the estimating-core plugin."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "estimating-core"


def test_mcp_json_declares_the_artifact_editor_stdio_server():
    cfg = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    # Flat plugin .mcp.json: server names at top level, no "mcpServers" wrapper.
    assert "mcpServers" not in cfg, "plugin .mcp.json must be flat, not wrapped"
    entry = cfg["artifact-editor"]
    assert entry["type"] == "stdio"
    joined = entry["command"] + " " + " ".join(entry.get("args", []))
    assert "${CLAUDE_PLUGIN_ROOT}" in joined
    # Self-locating launcher pair (launch + launch.cmd via PATHEXT); the
    # server script itself is reached through them, not named in .mcp.json.
    assert "scripts/launch" in joined


def test_the_launcher_pair_goes_through_the_runtime_resolver():
    """Bare `python3` here was the CONNECTION_CLOSED: the system interpreter has
    never had estimating_tools. Both launchers must reach the server through
    `plugin_runtime.py serve`, which execs the runtime's own interpreter."""
    for name in ("launch", "launch.cmd"):
        src = (PLUGIN / "scripts" / name).read_text(encoding="utf-8")
        assert "plugin_runtime.py" in src and "serve" in src, name
        assert "artifact_app_server.py" in src, name
        bare = [l for l in src.splitlines()
                if l.lstrip().startswith(("exec python", "python \"%~dp0artifact"))]
        assert not bare, f"{name} still starts the server on a bare interpreter: {bare}"


def test_the_server_script_no_longer_installs_anything_itself():
    """It runs UNDER the runtime by the time it is reached, so a second pip here
    would only race the SessionStart hook -- which is what it used to do.

    Asserted on the parsed tree, not on the text: the docstring still explains
    what this file stopped doing, and a substring check cannot tell an
    explanation from an import.
    """
    src = (PLUGIN / "scripts" / "artifact_app_server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "ensure_tools" not in imported, imported
    assert "estimating_tools.artifact_app.server" in imported


# ---------------------------------------------------------------------------
# the hook has to be able to START, which is not the resolver's problem
# ---------------------------------------------------------------------------

def test_both_hooks_fall_back_to_the_windows_py_launcher():
    """`python3 || python` is not enough on Windows. The official installer
    without "Add Python to PATH" leaves `py.exe` (System32) as the only way to
    reach an interpreter, and a hook that cannot start never builds the runtime
    -- after which every skill command, which now names an absolute shim path,
    fails. The resolver's candidate list cannot help: nothing consults it until
    the hook is already running. Once it does, `sys.executable` IS the launcher's
    interpreter and is already the last candidate."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    hooks = sorted(root.glob("plugins/*/hooks/hooks.json"))
    assert hooks, "no plugin hooks found"
    for h in hooks:
        command = (json.loads(h.read_text(encoding="utf-8"))
                   ["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        assert "py -3 " in command, f"{h.relative_to(root)} has no py-launcher fallback"
        # ordering matters: py -3 picks the newest install, which may be above
        # our ceiling, so it is the last resort rather than the first choice.
        assert command.index("python3 ") < command.index("py -3 ")
