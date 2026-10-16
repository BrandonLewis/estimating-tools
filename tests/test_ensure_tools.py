"""The SessionStart hooks: thin, labelled, and incapable of failing a session.

Spec: docs/superpowers/specs/2026-09-27-plugin-runtime-design.md

All the resolution logic moved into `plugin_runtime`, which has its own suite
(tests/test_plugin_runtime.py). What is left to hold is the contract at the hook
boundary: every exit is 0, exactly one line reaches stdout, the two hooks carry
their own label, and the vendored copy each plugin imports is the real module.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGINS = ("calc-bim", "estimating-core")
SOURCE = REPO / "scripts" / "plugin_runtime.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(params=PLUGINS)
def hook(request):
    """One plugin's ensure_tools module, imported from its own scripts/ dir."""
    plugin = request.param
    scripts = REPO / "plugins" / plugin / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        # The hook does `import plugin_runtime` inside main(), resolving it from
        # its own directory. Pre-loading THAT copy under that name is what lets
        # these tests patch the function the hook will actually call.
        runtime = _load("plugin_runtime", scripts / "plugin_runtime.py")
        mod = _load(f"{plugin}_ensure_tools", scripts / "ensure_tools.py")
    finally:
        sys.path.remove(str(scripts))
    mod.PLUGIN_NAME = plugin
    mod.RUNTIME = runtime
    return mod


# ---- the vendored module is the real one -------------------------------------

@pytest.mark.parametrize("plugin", PLUGINS)
def test_the_vendored_runtime_is_byte_identical_to_the_source(plugin):
    """Each plugin ships as its own subtree, so it cannot import a sibling's
    file or the repo root's -- neither exists on an installed machine. The copy
    is generated; `scripts/vendor_runtime.py --check` is the CI gate."""
    vendored = REPO / "plugins" / plugin / "scripts" / "plugin_runtime.py"
    assert vendored.read_bytes() == SOURCE.read_bytes(), (
        f"{plugin}'s vendored plugin_runtime.py is stale — "
        "run: python scripts/vendor_runtime.py")


@pytest.mark.parametrize("plugin", PLUGINS)
def test_the_hook_sits_beside_the_module_it_imports(plugin):
    scripts = REPO / "plugins" / plugin / "scripts"
    assert (scripts / "ensure_tools.py").is_file()
    assert (scripts / "plugin_runtime.py").is_file()


# ---- the hook's own contract -------------------------------------------------

def test_the_hook_carries_its_own_label(hook):
    assert hook.LABEL == hook.PLUGIN_NAME


def test_the_hook_delegates_and_prints_exactly_one_line(hook, capsys, monkeypatch):
    seen = {}

    def fake_ensure(plugin_root, label):
        seen["root"], seen["label"] = plugin_root, label
        return f"{label}: all good"

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/some/plugin/root")
    monkeypatch.setattr(hook.RUNTIME, "ensure", fake_ensure)
    assert hook.main() == 0
    out = capsys.readouterr()
    assert out.out.splitlines() == [f"{hook.LABEL}: all good"]
    assert seen == {"root": "/some/plugin/root", "label": hook.LABEL}


def test_without_the_host_variable_the_hook_finds_its_own_plugin_root(
        hook, monkeypatch, capsys):
    """CLAUDE_PLUGIN_ROOT is expanded by the host in hooks.json, but the hook is
    also run by hand from a skill's Setup line."""
    seen = {}
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(hook.RUNTIME, "ensure",
                        lambda root, label: seen.setdefault("root", root) or "x: y")
    hook.main()
    capsys.readouterr()
    assert Path(seen["root"]) == REPO / "plugins" / hook.PLUGIN_NAME


def test_a_raising_resolver_still_exits_zero(hook, capsys, monkeypatch):
    """`ensure` promises not to raise, but a SessionStart hook that dies takes
    the session's start with it, so the promise is belted as well as braced."""
    def boom(plugin_root, label):
        raise OSError("read-only file system")

    monkeypatch.setattr(hook.RUNTIME, "ensure", boom)
    assert hook.main() == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert hook.LABEL in out and "read-only file system" in out


# ---- end to end, as the host runs it ----------------------------------------

@pytest.mark.parametrize("plugin", PLUGINS)
def test_running_the_hook_as_the_host_does_exits_zero(plugin, tmp_path):
    """No wheels anywhere: the worst realistic case still exits 0 with one
    actionable line, and touches no network."""
    empty = tmp_path / "plugin-root"
    empty.mkdir()
    out = subprocess.run(
        [sys.executable, str(REPO / "plugins" / plugin / "scripts" / "ensure_tools.py")],
        capture_output=True, text=True, timeout=300,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "CLAUDE_PLUGIN_ROOT": str(empty),
             "ESTIMATING_RUNTIME_HOME": str(tmp_path / "rt")})
    assert out.returncode == 0, out.stderr
    assert len(out.stdout.strip().splitlines()) == 1, out.stdout
    assert out.stdout.startswith(f"{plugin}: ")
    assert "reinstall" in out.stdout


@pytest.mark.parametrize("plugin", PLUGINS)
def test_the_hook_reports_the_real_bundled_wheels_of_both_plugins(plugin, tmp_path):
    """Run against the repo's own plugin tree with no runtime present: it must
    name BOTH wheels, because the runtime is the union across installed plugins
    and this is what proves calc-bim's hook sees estimating-core's wheel."""
    scripts = REPO / "plugins" / plugin / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        pr = _load(f"{plugin}_pr_probe", scripts / "plugin_runtime.py")
    finally:
        sys.path.remove(str(scripts))
    wheels = pr.discover_wheels(str(REPO / "plugins" / plugin))
    assert sorted(wheels) == ["bimforge", "estimating_tools"]
    # Never a non-plugin dist/, whatever its version.
    assert ".claude-plugin" not in wheels["bimforge"]["path"]
