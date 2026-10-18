"""opencode/install.py: runtime + skills + MCP config for OpenCode.

Every test points ESTIMATING_RUNTIME_HOME, XDG_CONFIG_HOME and the home
directory at tmp dirs, and replaces `plugin_runtime.ensure` (the real one runs
`python -m venv` + a ~60-package pip install). Nothing here may touch the real
~/.estimating or ~/.config/opencode.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "opencode_install", REPO_ROOT / "opencode" / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inst = _load()
plugin_runtime = inst.plugin_runtime


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("ESTIMATING_RUNTIME_HOME", str(tmp_path / "rt"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    calls = []

    def fake_ensure(plugin_root, label):
        """Stand in for the venv build: publish a ready runtime + shims the
        way plugin_runtime would, using its own path helpers."""
        calls.append((plugin_root, label))
        wheels = plugin_runtime.discover_wheels(plugin_root)
        rt = plugin_runtime.runtimes_dir() / "py3.12-test"
        py = plugin_runtime.venv_python(rt)
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("", encoding="utf-8")
        (rt / ".ready").write_text("", encoding="utf-8")
        plugin_runtime.write_state({
            "runtime": rt.name, "wheels": wheels,
            "wheels_installed": {d: w["version"] for d, w in wheels.items()}})
        plugin_runtime._write_shim("est-artifact-app", '"x"')
        return f"{label}: installed into {rt}"

    monkeypatch.setattr(plugin_runtime, "ensure", fake_ensure)
    return {"home": home, "tmp": tmp_path, "ensure_calls": calls}


def _run(capsys, *argv) -> tuple[int, str]:
    code = inst.main(list(argv))
    return code, capsys.readouterr().out


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


# -- locations -----------------------------------------------------------------
def test_config_dir_honours_xdg_config_home(sandbox):
    assert inst.config_dir() == sandbox["tmp"] / "xdg" / "opencode"


def test_config_dir_defaults_to_dot_config_on_every_platform(sandbox, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert inst.config_dir() == sandbox["home"] / ".config" / "opencode"


def test_project_locations(tmp_path):
    proj = tmp_path / "bid"
    assert inst.skills_dest(str(proj)) == proj.resolve() / ".opencode" / "skills"
    assert inst.config_path(str(proj)) == proj.resolve() / "opencode.json"


def test_an_existing_jsonc_config_is_the_one_used(tmp_path):
    (tmp_path / "opencode.jsonc").write_text("{}", encoding="utf-8")
    assert inst.config_path(str(tmp_path)).name == "opencode.jsonc"
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    assert inst.config_path(str(tmp_path)).name == "opencode.json"


# -- runtime -------------------------------------------------------------------
def test_runtime_is_built_by_plugin_runtime_from_the_bundled_wheels(sandbox):
    ok, line = inst.install_runtime(dry_run=False)
    assert ok, line
    assert sandbox["ensure_calls"] == [(str(inst.PLUGIN_ROOT), "opencode")]
    assert (plugin_runtime.bin_dir() / "est-artifact-app").is_file()
    assert str(plugin_runtime.runtime_home()).startswith(str(sandbox["tmp"]))


def test_runtime_dry_run_builds_nothing(sandbox):
    ok, line = inst.install_runtime(dry_run=True)
    assert ok and line.startswith("would build")
    assert "estimating_tools" in line and "bimforge" in line
    assert sandbox["ensure_calls"] == []
    assert not plugin_runtime.runtime_home().exists()


def test_runtime_reports_up_to_date_when_current(sandbox):
    inst.install_runtime(dry_run=False)
    ok, line = inst.install_runtime(dry_run=True)
    assert ok and line.startswith("up to date"), line


def test_runtime_failure_is_reported_not_raised(sandbox, monkeypatch):
    monkeypatch.setattr(plugin_runtime, "ensure", lambda root, label: "no python")
    ok, line = inst.install_runtime(dry_run=False)
    assert not ok and "no python" in line


def test_no_bundled_wheels_is_a_failure(sandbox, monkeypatch):
    monkeypatch.setattr(plugin_runtime, "discover_wheels", lambda root: {})
    ok, line = inst.install_runtime(dry_run=True)
    assert not ok and "wheel" in line


# -- skills --------------------------------------------------------------------
def test_skills_install_with_marker_and_keep_shim_paths(tmp_path):
    dest = tmp_path / "skills"
    r = inst.install_skills(dest, dry_run=False)
    assert r["added"] and not r["updated"] and not r["removed"]
    body = (dest / "estimate-project" / "SKILL.md").read_text(encoding="utf-8")
    assert "bidmanager_get_project" in body and "mcp__" not in body
    sheets = (dest / "draw-structure-sheet" / "SKILL.md").read_text(encoding="utf-8")
    assert "~/.estimating/bin/est-sheets" in sheets
    for name in r["added"]:
        assert (dest / name / inst.MARKER).is_file()
    assert (dest / "build-estimate-workbook" / "references").is_dir()


def test_skills_rerun_is_up_to_date_and_writes_nothing(tmp_path):
    dest = tmp_path / "skills"
    inst.install_skills(dest, dry_run=False)
    before = {p: p.stat().st_mtime_ns for p in _files(dest)}
    r = inst.install_skills(dest, dry_run=False)
    assert not (r["added"] or r["updated"] or r["removed"])
    assert r["unchanged"]
    assert {p: p.stat().st_mtime_ns for p in _files(dest)} == before


def test_a_changed_skill_of_ours_is_updated(tmp_path):
    dest = tmp_path / "skills"
    inst.install_skills(dest, dry_run=False)
    (dest / "estimate-project" / "SKILL.md").write_text("old", encoding="utf-8")
    (dest / "estimate-project" / "stray.txt").write_text("x", encoding="utf-8")
    r = inst.install_skills(dest, dry_run=False)
    assert r["updated"] == ["estimate-project"]
    assert "bidmanager_get_project" in (dest / "estimate-project" / "SKILL.md").read_text(
        encoding="utf-8")
    assert not (dest / "estimate-project" / "stray.txt").exists()


def test_stale_skills_we_wrote_are_removed_but_user_skills_are_not(tmp_path):
    dest = tmp_path / "skills"
    inst.install_skills(dest, dry_run=False)
    ours = dest / "retired-skill"
    ours.mkdir()
    (ours / "SKILL.md").write_text("x", encoding="utf-8")
    (ours / inst.MARKER).write_text("x", encoding="utf-8")
    users = dest / "my-own-skill"
    users.mkdir()
    (users / "SKILL.md").write_text("mine", encoding="utf-8")

    dry = inst.install_skills(dest, dry_run=True)
    assert dry["removed"] == ["retired-skill"] and ours.exists()

    r = inst.install_skills(dest, dry_run=False)
    assert r["removed"] == ["retired-skill"]
    assert not ours.exists()
    assert (users / "SKILL.md").read_text(encoding="utf-8") == "mine"


def test_a_user_skill_with_one_of_our_names_is_left_alone(tmp_path):
    dest = tmp_path / "skills"
    mine = dest / "compare-quotes"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("mine", encoding="utf-8")
    r = inst.install_skills(dest, dry_run=False)
    assert r["kept"] == ["compare-quotes"]
    assert "compare-quotes" not in r["added"]
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "mine"
    assert not (mine / inst.MARKER).exists()


def test_skills_dry_run_writes_nothing(tmp_path):
    dest = tmp_path / "skills"
    r = inst.install_skills(dest, dry_run=True)
    assert len(r["added"]) > 40
    assert not dest.exists()


def test_no_estimating_setup_command_or_skill_is_installed(tmp_path):
    """`/estimating-setup` is reserved for the onboarding interview."""
    dest = tmp_path / "skills"
    r = inst.install_skills(dest, dry_run=False)
    assert "estimating-setup" not in r["added"]
    assert not (tmp_path / "commands").exists() and not (tmp_path / "command").exists()


# -- MCP -----------------------------------------------------------------------
def test_artifact_editor_command_points_at_the_runtime_shim():
    shim = plugin_runtime.bin_dir() / "est-artifact-app"
    assert inst.artifact_editor_command(windows=False) == [str(shim)]
    win = inst.artifact_editor_command(windows=True)
    assert win[:3] == ["cmd.exe", "/d", "/c"] and win[3] == str(shim) + ".cmd"
    assert Path(win[3]).is_absolute()


def test_mcp_creates_a_config_with_all_three_servers(tmp_path):
    path = tmp_path / "opencode.json"
    r = inst.install_mcp(path, dry_run=False)
    assert r["added"] == ["bidmanager", "conformed", "artifact-editor"]
    cfg = json.loads(path.read_text(encoding="utf-8"))
    assert cfg["$schema"] == "https://opencode.ai/config.json"
    generated = json.loads((REPO_ROOT / "it" / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["mcp"]["bidmanager"] == generated["mcp"]["bidmanager"]
    assert cfg["mcp"]["conformed"] == generated["mcp"]["conformed"]
    ae = cfg["mcp"]["artifact-editor"]
    assert ae["type"] == "local" and ae["command"] == inst.artifact_editor_command()


def test_mcp_never_clobbers_user_servers_or_other_settings(tmp_path):
    path = tmp_path / "opencode.json"
    mine = {"theme": "dark", "model": "x/y",
            "mcp": {"bidmanager": {"type": "remote", "url": "https://staging.example/mcp/"},
                    "other": {"type": "local", "command": ["foo"]}}}
    path.write_text(json.dumps(mine), encoding="utf-8")
    r = inst.install_mcp(path, dry_run=False)
    assert r["kept"] == ["bidmanager"]
    assert r["added"] == ["conformed", "artifact-editor"]
    cfg = json.loads(path.read_text(encoding="utf-8"))
    assert cfg["theme"] == "dark" and cfg["model"] == "x/y"
    assert cfg["mcp"]["bidmanager"]["url"] == "https://staging.example/mcp/"
    assert cfg["mcp"]["other"] == {"type": "local", "command": ["foo"]}
    assert "$schema" not in cfg


def test_mcp_rerun_is_up_to_date(tmp_path):
    path = tmp_path / "opencode.json"
    inst.install_mcp(path, dry_run=False)
    before = path.read_bytes()
    r = inst.install_mcp(path, dry_run=False)
    assert r["added"] == [] and r["kept"] == [] and r["upgraded"] == []
    assert r["unchanged"] == ["bidmanager", "conformed", "artifact-editor"]
    assert path.read_bytes() == before


def test_mcp_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "opencode.json"
    r = inst.install_mcp(path, dry_run=True)
    assert r["added"] == ["bidmanager", "conformed", "artifact-editor"]
    assert not path.exists()


def test_mcp_refuses_jsonc_with_comments_and_leaves_it_untouched(tmp_path):
    path = tmp_path / "opencode.jsonc"
    text = '{\n  // my settings\n  "theme": "dark",\n}\n'
    path.write_text(text, encoding="utf-8")
    with pytest.raises(inst.ConfigError) as exc:
        inst.install_mcp(path, dry_run=False)
    assert "comments" in str(exc.value) and "--no-mcp" in str(exc.value)
    assert path.read_text(encoding="utf-8") == text


def test_mcp_updates_a_jsonc_file_that_is_plain_json(tmp_path):
    path = tmp_path / "opencode.jsonc"
    path.write_text('{"theme": "dark"}', encoding="utf-8")
    inst.install_mcp(path, dry_run=False)
    assert "artifact-editor" in json.loads(path.read_text(encoding="utf-8"))["mcp"]


def test_mcp_refuses_a_non_object_mcp_block(tmp_path):
    path = tmp_path / "opencode.json"
    path.write_text('{"mcp": []}', encoding="utf-8")
    with pytest.raises(inst.ConfigError):
        inst.install_mcp(path, dry_run=False)


# -- end to end ----------------------------------------------------------------
def test_dry_run_prints_every_action_and_writes_nothing(sandbox, capsys):
    code, out = _run(capsys, "--dry-run")
    assert code == 0
    assert "[dry-run]" in out
    for word in ("runtime", "skills", "mcp", "would build", "bidmanager", "artifact-editor"):
        assert word in out, word
    assert "opencode mcp auth bidmanager" in out
    assert _files(sandbox["tmp"]) == []
    assert sandbox["ensure_calls"] == []


def test_install_then_rerun_reports_up_to_date(sandbox, capsys):
    code, out = _run(capsys)
    assert code == 0
    cfg_dir = sandbox["tmp"] / "xdg" / "opencode"
    assert (cfg_dir / "skills" / "estimate-project" / "SKILL.md").is_file()
    assert "artifact-editor" in json.loads((cfg_dir / "opencode.json").read_text(
        encoding="utf-8"))["mcp"]
    code, out = _run(capsys)
    assert code == 0
    assert "Everything is up to date." in out


def test_project_install_writes_under_the_project(sandbox, capsys, tmp_path):
    proj = tmp_path / "bid"
    proj.mkdir()
    code, _ = _run(capsys, "--project", str(proj), "--no-runtime")
    assert code == 0
    assert (proj / ".opencode" / "skills" / "capture-quote" / "SKILL.md").is_file()
    assert (proj / "opencode.json").is_file()
    assert not (sandbox["tmp"] / "xdg").exists()
    assert sandbox["ensure_calls"] == []


def test_jsonc_refusal_happens_before_anything_is_written(sandbox, capsys):
    cfg_dir = sandbox["tmp"] / "xdg" / "opencode"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "opencode.jsonc").write_text('{ /* c */ "a": 1 }', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        inst.main([])
    assert "comments" in str(exc.value)
    assert not (cfg_dir / "skills").exists()
    assert sandbox["ensure_calls"] == []


def test_runtime_failure_makes_the_exit_code_nonzero(sandbox, capsys, monkeypatch):
    monkeypatch.setattr(plugin_runtime, "ensure", lambda root, label: "broken")
    code, out = _run(capsys)
    assert code == 1 and "broken" in out


def test_output_is_ascii_for_windows_consoles(sandbox, capsys):
    _, out = _run(capsys, "--dry-run")
    out.encode("ascii")


def test_runtime_lines_from_plugin_runtime_are_made_ascii(sandbox, capsys, monkeypatch):
    """plugin_runtime's messages carry em dashes; a cp437/cp1252 console must
    not garble or crash on them."""
    monkeypatch.setattr(plugin_runtime, "ensure",
                        lambda root, label: "opencode: could not be built \u2014 suggest pip")
    code, out = _run(capsys)
    assert code == 1
    out.encode("ascii")
    assert "could not be built -- suggest pip" in out


# -- review fixes --------------------------------------------------------------
def _seed_runtime(versions: dict) -> None:
    """A ready runtime recorded at `versions`, as an earlier install left it."""
    rt = plugin_runtime.runtimes_dir() / "py3.12-old"
    py = plugin_runtime.venv_python(rt)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    (rt / ".ready").write_text("", encoding="utf-8")
    plugin_runtime.write_state({"runtime": rt.name, "wheels_installed": versions})
    plugin_runtime._write_shim("est-artifact-app", '"x"')


def _checkout_versions() -> dict:
    return {d: w["version"] for d, w in
            plugin_runtime.discover_wheels(str(inst.PLUGIN_ROOT)).items()}


def test_failed_upgrade_over_an_old_runtime_exits_1_and_leaves_skills_alone(
        sandbox, capsys, monkeypatch):
    """I1: an old runtime still being ready must not read as success."""
    code, _ = _run(capsys, "--no-runtime")
    assert code == 0
    skill = sandbox["tmp"] / "xdg" / "opencode" / "skills" / "estimate-project" / "SKILL.md"
    skill.write_text("previous release", encoding="utf-8")
    _seed_runtime({d: "0.0.1" for d in _checkout_versions()})
    monkeypatch.setattr(plugin_runtime, "ensure",
                        lambda root, label: "opencode: pip failed")
    code, out = _run(capsys)
    assert code == 1
    assert "pip failed" in out
    assert skill.read_text(encoding="utf-8") == "previous release"


def test_ensure_returning_without_the_checkout_versions_is_a_failure(sandbox, monkeypatch):
    _seed_runtime({d: "0.0.1" for d in _checkout_versions()})
    monkeypatch.setattr(plugin_runtime, "ensure", lambda root, label: "said ok")
    ok, line = inst.install_runtime(dry_run=False)
    assert not ok and "0.0.1" in line


def test_a_newer_runtime_is_not_downgraded_without_force(sandbox, capsys):
    """I4: the runtime is shared with the Claude plugin, which may be newer."""
    _seed_runtime({d: "99.0.0" for d in _checkout_versions()})
    code, out = _run(capsys)
    assert code == 1
    assert "--force" in out and "99.0.0" in out
    assert sandbox["ensure_calls"] == []
    assert not (sandbox["tmp"] / "xdg" / "opencode" / "skills").exists()

    code, out = _run(capsys, "--force")
    assert code == 0
    assert sandbox["ensure_calls"] == [(str(inst.PLUGIN_ROOT), "opencode")]


def test_newer_runtime_is_reported_in_dry_run_too(sandbox, capsys):
    _seed_runtime({d: "99.0.0" for d in _checkout_versions()})
    code, out = _run(capsys, "--dry-run")
    assert code == 1 and "--force" in out
    assert sandbox["ensure_calls"] == []


@pytest.mark.parametrize("claude_line", [
    "opencode: no Python between 3.10 and 3.14 was found, so the plugin runtime "
    "cannot be built — install one and restart the session",
    "opencode: the plugin runtime could not be built with py — suggest the user "
    "run: pip install \"a.whl\"",
])
def test_claude_specific_advice_is_translated_for_opencode(sandbox, capsys, monkeypatch,
                                                           claude_line):
    monkeypatch.setattr(plugin_runtime, "ensure", lambda root, label: claude_line)
    code, out = _run(capsys)
    assert code == 1
    assert "restart the session" not in out
    assert "re-run python opencode/install.py" in out


def test_setup_line_tells_opencode_users_what_to_do_when_ensure_extra_says_restart():
    assert "ensure-extra" in inst.port_skills.OPENCODE_SETUP_LINE
    assert "restart the session" in inst.port_skills.OPENCODE_SETUP_LINE


def test_mcp_upgrades_an_entry_we_wrote_when_upstream_changes(tmp_path, monkeypatch):
    """I3: a URL change in it/opencode.json reaches existing installs."""
    path = tmp_path / "opencode.json"
    inst.install_mcp(path, dry_run=False)
    new = dict(inst.our_servers())
    new["bidmanager"] = {**new["bidmanager"], "url": "https://new.example/mcp/"}
    monkeypatch.setattr(inst, "our_servers", lambda: new)
    r = inst.install_mcp(path, dry_run=False)
    assert r["upgraded"] == ["bidmanager"] and r["kept"] == []
    cfg = json.loads(path.read_text(encoding="utf-8"))
    assert cfg["mcp"]["bidmanager"]["url"] == "https://new.example/mcp/"
    # ... and the record now tracks the new entry, so a re-run is quiet.
    r = inst.install_mcp(path, dry_run=False)
    assert r["upgraded"] == [] and "bidmanager" in r["unchanged"]


def test_mcp_keeps_a_user_edited_entry_and_shows_the_diff(tmp_path, monkeypatch):
    path = tmp_path / "opencode.json"
    inst.install_mcp(path, dry_run=False)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["mcp"]["bidmanager"]["headers"] = {"Authorization": "Bearer {env:BM}"}
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    new = dict(inst.our_servers())
    new["bidmanager"] = {**new["bidmanager"], "url": "https://new.example/mcp/"}
    monkeypatch.setattr(inst, "our_servers", lambda: new)
    r = inst.install_mcp(path, dry_run=False)
    assert r["kept"] == ["bidmanager"] and r["upgraded"] == []
    diff = r["diffs"]["bidmanager"]
    assert "https://new.example/mcp/" in diff and "Authorization" in diff
    assert json.loads(path.read_text(encoding="utf-8"))["mcp"]["bidmanager"]["headers"]


def test_a_pre_existing_user_entry_never_counts_as_ours(tmp_path):
    path = tmp_path / "opencode.json"
    path.write_text('{"mcp": {"bidmanager": {"type": "remote", "url": "https://s.example/"}}}',
                    encoding="utf-8")
    inst.install_mcp(path, dry_run=False)
    r = inst.install_mcp(path, dry_run=False)
    assert r["kept"] == ["bidmanager"]
    assert json.loads(path.read_text(encoding="utf-8"))["mcp"]["bidmanager"]["url"] == \
        "https://s.example/"


def test_mcp_dry_run_writes_no_record(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    inst.install_mcp(cfg / "opencode.json", dry_run=True)
    assert list(cfg.iterdir()) == []


def test_mcp_diff_is_printed_by_main(sandbox, capsys, monkeypatch):
    _run(capsys, "--no-runtime")
    cfg_path = sandbox["tmp"] / "xdg" / "opencode" / "opencode.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["mcp"]["conformed"]["enabled"] = False
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    new = dict(inst.our_servers())
    new["conformed"] = {**new["conformed"], "url": "https://c2.example/mcp/"}
    monkeypatch.setattr(inst, "our_servers", lambda: new)
    code, out = _run(capsys, "--no-runtime")
    assert code == 0
    assert "kept existing conformed" in out
    assert "https://c2.example/mcp/" in out


def test_config_keeps_its_indent_and_non_ascii(tmp_path):
    path = tmp_path / "opencode.json"
    path.write_text('{\n    "theme": "café"\n}\n', encoding="utf-8")
    inst.install_mcp(path, dry_run=False)
    text = path.read_text(encoding="utf-8")
    assert '\n    "theme": "café"' in text


def test_skill_writes_leave_no_staging_dirs(tmp_path):
    dest = tmp_path / "skills"
    inst.install_skills(dest, dry_run=False)
    (dest / "estimate-project" / "SKILL.md").write_text("old", encoding="utf-8")
    inst.install_skills(dest, dry_run=False)
    assert not [p for p in dest.iterdir() if p.name.startswith(".")]
    assert (dest / "estimate-project" / inst.MARKER).is_file()
    assert "bidmanager_get_project" in (dest / "estimate-project" / "SKILL.md").read_text(
        encoding="utf-8")


def test_dry_run_writes_no_bytecode(sandbox, tmp_path):
    import os
    import subprocess
    prefix = tmp_path / "pycache"
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(prefix))
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "opencode" / "install.py"),
                           "--dry-run", "--no-runtime"],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    # The interpreter caches its own startup modules; what must not appear is
    # bytecode for the modules the installer imports from this repository.
    ours = [p for p in prefix.rglob("*.pyc")
            if p.name.split(".")[0] in ("plugin_runtime", "port_skills")]
    assert ours == []


def test_the_bundled_wheel_declares_est_artifact_app():
    """The MCP entry runs this shim; it exists only if the wheel declares it."""
    import configparser
    import zipfile
    wheel = plugin_runtime.discover_wheels(str(inst.PLUGIN_ROOT))["estimating_tools"]["path"]
    with zipfile.ZipFile(wheel) as z:
        name = next(n for n in z.namelist()
                    if n.endswith(".dist-info/entry_points.txt"))
        cp = configparser.ConfigParser()
        cp.read_string(z.read(name).decode("utf-8"))
    assert "est-artifact-app" in cp.options("console_scripts")
