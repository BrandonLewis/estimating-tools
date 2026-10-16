"""The plugins' shared runtime: path, interpreter choice, atomicity, shims.

Spec: docs/superpowers/specs/2026-09-27-plugin-runtime-design.md

These tests build real venvs (no pip installs, so they stay fast) because the
whole point of the module is behaviour against a real filesystem: an atomic
directory swap and an atomic shim rewrite are not observable in a mock.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import plugin_runtime as pr  # noqa: E402

WINDOWS = os.name == "nt"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Relocate the runtime root so tests never touch the real one."""
    monkeypatch.setenv(pr.HOME_ENV, str(tmp_path / "rt"))
    return tmp_path / "rt"


# ---- the path is a constant, not a discovery ---------------------------------

def test_the_override_wins(home):
    assert pr.runtime_home() == home
    assert pr.bin_dir() == home / "bin"
    assert pr.state_file() == home / "state.json"


def test_the_default_is_one_string_on_every_platform(monkeypatch):
    """Skill text hardcodes this path, so nothing in the environment may move
    it -- not XDG_DATA_HOME, not LOCALAPPDATA. A variable in the equation is the
    four-way disagreement this module exists to remove, in miniature."""
    monkeypatch.delenv(pr.HOME_ENV, raising=False)
    expected = Path.home() / ".estimating"
    assert pr.runtime_home() == expected
    for var in ("XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(Path("/somewhere") / "else"))
        assert pr.runtime_home() == expected, f"{var} moved the root"


def test_the_path_skills_name_is_literally_what_the_module_computes(monkeypatch):
    """The one string that appears in 27 SKILL.md files."""
    monkeypatch.delenv(pr.HOME_ENV, raising=False)
    assert pr.bin_dir() == Path(os.path.expanduser("~/.estimating/bin"))


def test_the_path_does_not_depend_on_the_cwd(home, tmp_path, monkeypatch):
    """Constraint 1: a skill cannot name the plugin dir, so the root must not
    move when the shell does."""
    first = pr.runtime_home()
    sub = tmp_path / "somewhere" / "else"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert pr.runtime_home() == first


# ---- interpreter choice ------------------------------------------------------

def test_runtime_name_keys_on_python_minor_and_version():
    assert pr.runtime_name((3, 12), "0.1.81") == "py3.12-0.1.81"


def _fake_python(tmp_path, name, major, minor):
    """A stub interpreter that reports a version and nothing else."""
    exe = tmp_path / name
    exe.write_text(textwrap.dedent(f'''\
        #!/bin/sh
        # ignores the -c program and prints a fixed version
        echo "{major} {minor}"
        '''), encoding="utf-8")
    os.chmod(exe, 0o755)
    return exe


@pytest.mark.skipif(WINDOWS, reason="sh stub")
def test_version_of_reads_the_interpreter(tmp_path):
    assert pr._version_of(str(_fake_python(tmp_path, "p", 3, 11))) == (3, 11)


@pytest.mark.skipif(WINDOWS, reason="sh stub")
def test_version_of_tolerates_a_thing_that_is_not_an_interpreter(tmp_path):
    junk = tmp_path / "junk"
    junk.write_text("not executable", encoding="utf-8")
    assert pr._version_of(str(junk)) is None
    assert pr._version_of(str(tmp_path / "does-not-exist")) is None


def test_the_ceiling_is_exclusive_and_the_floor_inclusive():
    """ifcopenshell is >=3.10,<3.15, so "newest available" is the wrong rule:
    a 3.15 interpreter builds a venv whose install then fails."""
    assert pr.PY_MIN == (3, 10)
    assert pr.PY_MAX_EXCLUSIVE == (3, 15)
    assert pr.PY_MIN <= (3, 10) < pr.PY_MAX_EXCLUSIVE
    assert pr.PY_MIN <= (3, 14) < pr.PY_MAX_EXCLUSIVE
    assert not (3, 15) < pr.PY_MAX_EXCLUSIVE
    assert not pr.PY_MIN <= (3, 9)


@pytest.mark.skipif(WINDOWS, reason="sh stub")
def test_find_python_rejects_out_of_range_and_takes_the_first_in_range(
        tmp_path, monkeypatch):
    too_new = _fake_python(tmp_path, "python3.14", 3, 15)   # over the ceiling
    ok = _fake_python(tmp_path, "python3.12", 3, 12)
    too_old = _fake_python(tmp_path, "python3.10", 3, 9)    # under the floor
    monkeypatch.setattr(pr, "candidate_pythons",
                        lambda: [str(too_new), str(too_old), str(ok)])
    assert pr.find_python() == (str(ok), (3, 12))


@pytest.mark.skipif(WINDOWS, reason="sh stub")
def test_find_python_returns_none_when_nothing_qualifies(tmp_path, monkeypatch):
    bad = _fake_python(tmp_path, "python3.9", 3, 9)
    monkeypatch.setattr(pr, "candidate_pythons", lambda: [str(bad)])
    assert pr.find_python() is None


def test_candidates_prefer_explicit_minors_over_bare_names():
    """So the choice does not silently depend on what `python3` points at."""
    names = [Path(c).name for c in pr.candidate_pythons()]
    explicit = [i for i, n in enumerate(names) if n.startswith("python3.")]
    bare = [i for i, n in enumerate(names) if n in ("python3", "python")]
    if explicit and bare:
        assert min(explicit) < min(bare)


# ---- state ------------------------------------------------------------------

def test_state_round_trips(home):
    pr.write_state({"version": "0.1.81", "extras": ["solids"]})
    assert pr.read_state()["version"] == "0.1.81"


def test_a_corrupt_state_file_means_rebuild_not_crash(home):
    pr.state_file().parent.mkdir(parents=True, exist_ok=True)
    pr.state_file().write_text("{not json at all", encoding="utf-8")
    assert pr.read_state() == {}


@pytest.mark.parametrize("payload", ["[]", '"a string"', "5", "null", "[1, 2]"])
def test_valid_json_that_is_not_a_mapping_also_means_rebuild(home, payload):
    """A truncated file was handled; valid JSON of the wrong shape was not. `[]`
    parses, is returned, and then meets `.get("runtime")` in every caller -- an
    AttributeError out of SessionStart, which is the one thing read_state's
    contract promises never to do."""
    pr.state_file().parent.mkdir(parents=True, exist_ok=True)
    pr.state_file().write_text(payload, encoding="utf-8")
    assert pr.read_state() == {}
    pr.read_state().get("runtime")      # what every caller does next


def test_state_write_leaves_no_temp_behind(home):
    pr.write_state({"a": 1})
    assert [p.name for p in home.iterdir() if p.name.endswith(".tmp")] == []


# ---- building a runtime (real venvs) ----------------------------------------

def test_build_runtime_makes_a_usable_venv(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    assert rt is not None and pr.venv_python(rt).is_file()
    assert rt == pr.runtimes_dir() / "py-test"


def test_build_runtime_is_idempotent(home):
    first = pr.build_runtime(sys.executable, "py-test", [])
    marker = first / "MARKER"
    marker.write_text("x", encoding="utf-8")
    second = pr.build_runtime(sys.executable, "py-test", [])
    assert second == first
    assert marker.exists(), "an existing runtime must be reused, not rebuilt"


def test_the_runtime_is_built_where_it_will_live(home):
    """pip bakes the build-time absolute path into every console script's
    shebang, so a runtime that was built elsewhere and renamed yields
    `exec: .../.tmp-XXXX/v/bin/python: not found` the first time a tool runs.
    Nothing may sit between the build directory and the final one."""
    rt = pr.build_runtime(sys.executable, "py-test", [])
    assert rt == pr.runtimes_dir() / "py-test"
    assert [p.name for p in pr.runtimes_dir().iterdir()] == ["py-test"]


def test_readiness_is_the_marker_not_the_interpreter(home):
    """`python -m venv` succeeds long before `pip install` does."""
    half = pr.runtimes_dir() / "py-half"
    (half / "bin").mkdir(parents=True)
    (half / "Scripts").mkdir()
    pr.venv_python(half).write_text("", encoding="utf-8")
    assert not pr.is_ready(half), "a venv with no wheels in it looked ready"
    assert pr.current_runtime() is None
    pr._mark_ready(half)
    assert pr.is_ready(half)


def test_build_runtime_leaves_no_temp_directory(home):
    pr.build_runtime(sys.executable, "py-test", [])
    assert [p.name for p in pr.runtimes_dir().iterdir()
            if p.name.startswith(".tmp-")] == []


def test_an_abandoned_build_is_cleared_rather_than_wedging_forever(
        home, monkeypatch):
    """A crashed or killed run leaves a directory with no `.ready`. Left alone it
    would block the name forever and wedge every future session."""
    stale = pr.runtimes_dir() / "py-test"
    (stale / "bin").mkdir(parents=True)
    (stale / "junk").write_text("x", encoding="utf-8")
    monkeypatch.setattr(pr, "_age", lambda p: pr.ABANDONED_AFTER + 1)
    rt = pr.build_runtime(sys.executable, "py-test", [])
    assert rt is not None and pr.is_ready(rt)
    assert rt == stale
    assert not (rt / "junk").exists(), "the abandoned build was reused, not cleared"


def test_a_live_concurrent_build_is_waited_for_not_duplicated(home, monkeypatch):
    """Both plugins' SessionStart hooks can run at once. Waiting costs seconds;
    duplicating a 58-package install costs minutes."""
    live = pr.runtimes_dir() / "py-test"
    (live / "bin").mkdir(parents=True)          # young, unready: a live build

    # The "winner" finishes on the second poll.
    polls = []

    def ready(runtime):
        if runtime == live:
            polls.append(1)
            return len(polls) > 1
        return pr_is_ready(runtime)

    pr_is_ready = pr.is_ready
    monkeypatch.setattr(pr, "is_ready", ready)
    monkeypatch.setattr(pr.time, "sleep", lambda s: None)
    monkeypatch.setattr(pr.subprocess, "run",
                        lambda *a, **k: pytest.fail("built a second copy"))
    target, must_build = pr._claim("py-test")
    assert target == live and must_build is False


def test_a_build_that_never_finishes_gets_a_copy_of_its_own(home, monkeypatch):
    """The winner died mid-install. The loser must not wait forever, and must not
    fight for the name."""
    live = pr.runtimes_dir() / "py-test"
    (live / "bin").mkdir(parents=True)
    monkeypatch.setattr(pr, "CLAIM_WAIT", 0.0)
    target, must_build = pr._claim("py-test")
    assert must_build is True
    assert target != live
    assert target.name.startswith("py-test-")


def test_a_failed_install_leaves_nothing_claimable_behind(home, monkeypatch):
    """A failed build must not leave a directory that blocks the name."""
    monkeypatch.setattr(pr, "_pip", lambda *a: False)
    assert pr.build_runtime(sys.executable, "py-test", ["nonexistent-xyz"]) is None
    assert not (pr.runtimes_dir() / "py-test").exists()


def test_build_runtime_reports_failure_rather_than_raising(home):
    assert pr.build_runtime("/nonexistent/python", "py-test", []) is None


# ---- shims ------------------------------------------------------------------

def _stub_console_script(rt: Path, name: str, dist: str = "bimforge") -> Path:
    """A console script AND the wheel metadata that declares it.

    Both halves matter: `console_scripts()` reads `entry_points.txt` rather than
    listing `bin/`, so that a runtime's `bin/` full of DEPENDENCY scripts
    (jsonschema, mcp, uvicorn, ttx, f2py...) does not get shimmed.
    """
    target = pr.venv_bin(rt) / (name + ".exe" if WINDOWS else name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("#!/bin/sh\necho ran\n", encoding="utf-8")
    if not WINDOWS:
        os.chmod(target, 0o755)
    _declare_script(rt, dist, name)
    return target


def _declare_script(rt: Path, dist: str, name: str) -> None:
    site = (rt / "Lib" / "site-packages" if WINDOWS
            else rt / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}"
                 / "site-packages")
    info = site / f"{dist}-0.1.81.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    ep = info / "entry_points.txt"
    lines = ep.read_text(encoding="utf-8").splitlines() if ep.is_file() else [
        "[console_scripts]"]
    lines.append(f"{name} = {dist}.cli:main")
    ep.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_shims_point_at_the_runtime_and_are_executable(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    _stub_console_script(rt, "est-bim")
    assert pr.write_shims(rt, ["est-bim"]) == ["est-bim"]
    shim = pr.bin_dir() / "est-bim"
    assert shim.is_file(), "the extensionless shim is what skill text names"
    assert str(pr.venv_bin(rt)) in shim.read_text(encoding="utf-8")
    if WINDOWS:
        # cmd.exe and PowerShell need the .cmd; Git Bash needs the other.
        assert (pr.bin_dir() / "est-bim.cmd").is_file()
    else:
        assert os.access(shim, os.X_OK)


def test_a_script_the_runtime_lacks_gets_no_shim(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    assert pr.write_shims(rt, ["est-not-a-thing"]) == []
    assert not (pr.bin_dir() / "est-not-a-thing").exists()


def test_a_version_roll_retargets_the_shim_without_moving_its_path(home):
    """Skill text names bin/<script>; only the target may change."""
    old = pr.build_runtime(sys.executable, "py3.12-0.1.80", [])
    _stub_console_script(old, "est-bim")
    pr.write_shims(old, ["est-bim"])
    shim = pr.bin_dir() / "est-bim"
    before = shim.read_text(encoding="utf-8")

    new = pr.build_runtime(sys.executable, "py3.12-0.1.81", [])
    _stub_console_script(new, "est-bim")
    pr.write_shims(new, ["est-bim"])
    after = shim.read_text(encoding="utf-8")

    assert before != after
    assert "py3.12-0.1.81" in after and "py3.12-0.1.80" not in after


def test_shim_write_leaves_no_temp_behind(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    _stub_console_script(rt, "est-bim")
    pr.write_shims(rt, ["est-bim"])
    assert [p.name for p in pr.bin_dir().iterdir() if p.name.endswith(".tmp")] == []


@pytest.mark.skipif(WINDOWS, reason="POSIX shim execution")
def test_the_shim_actually_runs_its_target(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    _stub_console_script(rt, "est-bim")
    pr.write_shims(rt, ["est-bim"])
    import subprocess
    out = subprocess.run([str(pr.bin_dir() / "est-bim")], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0 and out.stdout.strip() == "ran"


# ---- pruning ----------------------------------------------------------------

def _fake_ready(name) -> Path:
    """A runtime that looks complete, without running venv or pip."""
    rt = pr.runtimes_dir() / name
    pr.venv_bin(rt).mkdir(parents=True, exist_ok=True)
    pr.venv_python(rt).write_text("", encoding="utf-8")
    pr._mark_ready(rt)
    return rt


def test_prune_removes_the_unkept_and_spares_the_kept(home):
    for n in ("py3.12-0.1.79", "py3.12-0.1.80", "py3.12-0.1.81"):
        _fake_ready(n)
    removed = pr.prune(["py3.12-0.1.81", "py3.12-0.1.80"])
    assert removed == ["py3.12-0.1.79"]
    assert (pr.runtimes_dir() / "py3.12-0.1.81").is_dir()


def test_prune_never_touches_a_live_build(home):
    """An unready directory that is young belongs to a session building right
    now -- quite possibly the other plugin's hook. Deleting it breaks it."""
    live = pr.runtimes_dir() / "py3.12-0.1.81"
    (live / "bin").mkdir(parents=True)
    assert pr.prune([]) == []
    assert live.is_dir()


def test_prune_collects_an_abandoned_build(home, monkeypatch):
    (pr.runtimes_dir() / "py3.12-0.1.80").mkdir(parents=True)
    monkeypatch.setattr(pr, "_age", lambda p: pr.ABANDONED_AFTER + 1)
    assert pr.prune([]) == ["py3.12-0.1.80"]


def test_prune_on_a_missing_directory_is_not_an_error(home):
    assert pr.prune([]) == []


# ---- discovering every installed plugin's wheels -----------------------------

def _plugin(root: Path, name: str, wheels: dict, *, version=None) -> Path:
    """A plugin tree in either observed layout, with fake wheels in dist/."""
    d = root / name / version if version else root / name
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (d / "dist").mkdir()
    for dist, ver in wheels.items():
        (d / "dist" / f"{dist}-{ver}-py3-none-any.whl").write_text("", encoding="utf-8")
    return d


def test_wheel_info_parses_and_rejects_non_wheels():
    assert pr.wheel_info("bimforge-0.1.81-py3-none-any.whl") == ("bimforge", "0.1.81")
    assert pr.wheel_info("estimating_tools-0.1.81-py3-none-any.whl") == (
        "estimating_tools", "0.1.81")
    assert pr.wheel_info("README.md") is None


def test_versions_compare_numerically_not_lexically():
    assert pr.version_key("0.1.81") > pr.version_key("0.1.9")
    assert pr.version_key("nonsense") == (0,)


def test_a_plugin_finds_its_siblings_wheels_in_the_repo_layout(tmp_path):
    """The union is what makes ONE runtime serve both plugins: calc-bim's hook
    must see estimating-core's wheel even though it bundles only bimforge."""
    plugins = tmp_path / "plugins"
    own = _plugin(plugins, "calc-bim", {"bimforge": "0.1.81"})
    _plugin(plugins, "estimating-core",
            {"bimforge": "0.1.81", "estimating_tools": "0.1.81"})
    found = pr.discover_wheels(str(own))
    assert sorted(found) == ["bimforge", "estimating_tools"]


def test_a_plugin_finds_its_siblings_wheels_in_the_marketplace_layout(tmp_path):
    """~/.claude/plugins/cache/<market>/<plugin>/<version>/dist/ -- one level
    deeper than the repo, and every cached version present at once."""
    market = tmp_path / "estimating-platform"
    own = _plugin(market, "calc-bim", {"bimforge": "0.1.79"}, version="0.1.79")
    _plugin(market, "calc-bim", {"bimforge": "0.1.81"}, version="0.1.81")
    _plugin(market, "estimating-core", {"estimating_tools": "0.1.80"},
            version="0.1.80")
    found = pr.discover_wheels(str(own))
    # Cache skew resolves upward: the hook runs from 0.1.79 and still builds the
    # runtime the 0.1.81 cache entry needs.
    assert found["bimforge"]["version"] == "0.1.81"
    assert found["estimating_tools"]["version"] == "0.1.80"
    assert pr.platform_version(found) == "0.1.81"


def test_a_dist_directory_that_is_not_a_plugins_is_ignored(tmp_path):
    """A `dist/` under packages/ (a stray build, or historically the PyPI
    name-reservation stub whose import raised) is not a plugin's. It must be
    structurally unreachable, not merely outranked on version."""
    repo = tmp_path / "repo"
    own = _plugin(repo / "plugins", "calc-bim", {"bimforge": "0.1.81"})
    stub = repo / "packages" / "bimforge" / "dist"
    stub.mkdir(parents=True)
    (stub / "bimforge-9.9.9-py3-none-any.whl").write_text("", encoding="utf-8")
    found = pr.discover_wheels(str(own))
    assert found["bimforge"]["version"] == "0.1.81", \
        "a non-plugin dist/ was treated as a plugin's"


def test_an_unknown_distribution_in_a_plugins_dist_is_ignored(tmp_path):
    own = _plugin(tmp_path / "plugins", "calc-bim",
                  {"bimforge": "0.1.81", "something_else": "2.0"})
    assert sorted(pr.discover_wheels(str(own))) == ["bimforge"]


def test_no_wheels_anywhere_is_an_empty_dict_not_an_error(tmp_path):
    (tmp_path / "empty").mkdir()
    assert pr.discover_wheels(str(tmp_path / "empty")) == {}


# ---- what gets installed ----------------------------------------------------

def test_base_install_omits_the_heavy_extras(tmp_path):
    """bimforge[all] pulls build123d and the OCP kernel. Base is bim+draw; the
    spec makes solids and terrain on-demand, per capability."""
    own = _plugin(tmp_path / "plugins", "calc-bim",
                  {"bimforge": "0.1.81", "estimating_tools": "0.1.81"})
    specs = pr.install_specs(pr.discover_wheels(str(own)))
    assert any(s.endswith("[bim,draw]") for s in specs)
    assert any(s.endswith("[plugin-core]") for s in specs)
    assert not any("solids" in s or "terrain" in s or "[all]" in s for s in specs)


def test_both_wheels_go_in_one_invocation(tmp_path):
    """estimating_tools declares bimforge unconditionally and bimforge is on no
    registry, so a separate invocation for the estimating wheel cannot resolve."""
    own = _plugin(tmp_path / "plugins", "calc-bim",
                  {"bimforge": "0.1.81", "estimating_tools": "0.1.81"})
    specs = pr.install_specs(pr.discover_wheels(str(own)))
    assert len(specs) == 2
    assert sum("bimforge-" in s for s in specs) == 1


def test_install_specs_can_be_narrowed_to_the_wheel_that_changed(tmp_path):
    own = _plugin(tmp_path / "plugins", "calc-bim",
                  {"bimforge": "0.1.81", "estimating_tools": "0.1.81"})
    specs = pr.install_specs(pr.discover_wheels(str(own)), ["estimating_tools"])
    assert len(specs) == 1 and "estimating_tools-" in specs[0]


# ---- shims are discovered, not listed ----------------------------------------

def test_console_scripts_come_from_our_wheels_metadata_only(home):
    """An observed run that scraped bin/ produced shims for jsonschema, mcp,
    uvicorn, ttx and f2py -- names we do not own, in a directory the user may one
    day put on PATH."""
    rt = pr.build_runtime(sys.executable, "py-test", [])
    _stub_console_script(rt, "est-bim")
    _stub_console_script(rt, "est-sheets")
    _stub_console_script(rt, "est-estimate", dist="estimating_tools")
    # A dependency's script, declared by a dist that is not ours.
    _stub_console_script(rt, "uvicorn", dist="uvicorn")
    found = pr.console_scripts(rt)
    assert set(found) == {"est-bim", "est-sheets", "est-estimate"}
    assert "uvicorn" not in found


def test_write_shims_without_a_list_shims_what_the_wheels_declare(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    _stub_console_script(rt, "est-bim")
    _stub_console_script(rt, "est-hist", dist="estimating_tools")
    assert set(pr.write_shims(rt)) == {"est-bim", "est-hist"}
    assert (pr.bin_dir() / "est-hist").is_file()


def test_refreshing_bin_drops_a_shim_whose_script_is_gone(home):
    """A script removed from a wheel must not leave a shim pointing at nothing."""
    rt = pr.build_runtime(sys.executable, "py-test", [])
    _stub_console_script(rt, "est-bim")
    state = {"runtime": rt.name}
    pr._refresh_bin(rt, state)
    (pr.bin_dir() / "est-retired").write_text("#!/bin/sh\n", encoding="utf-8")
    pr._refresh_bin(rt, state)
    assert (pr.bin_dir() / "est-bim").is_file()
    assert not (pr.bin_dir() / "est-retired").exists()
    assert (pr.bin_dir() / "ensure-extra").is_file(), "pruned our own shim"


def test_the_ensure_extra_shim_targets_the_vendored_module(home):
    """bin/ must survive a marketplace update moving the plugin cache, so the
    shim execs the copy under the runtime root, never the plugin's copy."""
    rt = pr.build_runtime(sys.executable, "py-test", [])
    pr.vendor_self()
    pr.write_extra_shim(rt)
    body = (pr.bin_dir() / "ensure-extra").read_text(encoding="utf-8")
    assert str(pr.vendored_self()) in body
    assert "ensure-extra" in body
    assert pr.vendored_self().is_file()
    exec_line = [l for l in body.splitlines() if l.startswith("exec")][0]
    assert "plugins" not in exec_line.replace(str(pr.runtime_home()), ""), \
        f"the shim reaches back into a plugin directory: {exec_line}"


@pytest.mark.skipif(WINDOWS, reason="POSIX shim execution")
def test_the_ensure_extra_shim_actually_runs(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    pr.vendor_self()
    pr.write_extra_shim(rt)
    import subprocess
    out = subprocess.run([str(pr.bin_dir() / "ensure-extra"), "not-an-extra"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 2
    assert "unknown extra" in out.stderr


# ---- the hook body ----------------------------------------------------------

def _installed(rt: Path, *names):
    """Pretend the wheels installed console scripts, without running pip."""
    for n in names:
        _stub_console_script(rt, n)


def test_ensure_with_no_wheels_says_so_and_does_not_raise(home, tmp_path):
    (tmp_path / "bare").mkdir()
    line = pr.ensure(str(tmp_path / "bare"), "calc-bim")
    assert line.startswith("calc-bim:")
    assert "reinstall" in line


def test_ensure_is_a_no_op_the_second_time(home, tmp_path, monkeypatch):
    """The common case must be a stat and a JSON read -- no pip, and not even an
    interpreter probe."""
    own = _plugin(tmp_path / "plugins", "calc-bim", {"bimforge": "0.1.81"})
    rt = pr.build_runtime(sys.executable, pr.runtime_name(
        sys.version_info[:2], "0.1.81"), [])
    _installed(rt, "est-bim")
    pr.write_state({"runtime": rt.name, "wheels_installed": {"bimforge": "0.1.81"}})

    calls = []
    monkeypatch.setattr(pr, "_pip", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(pr, "find_python",
                        lambda: pytest.fail("probed an interpreter on a warm start"))
    line = pr.ensure(str(own), "calc-bim")
    assert "ready" in line and "bimforge 0.1.81" in line
    assert calls == []
    assert (pr.bin_dir() / "est-bim").is_file()


def test_a_warm_start_refreshes_the_recorded_wheel_path(home, tmp_path):
    """A marketplace update moves the wheel without changing its version, and
    ensure-extra installs from the recorded path."""
    own = _plugin(tmp_path / "a" / "plugins", "calc-bim", {"bimforge": "0.1.81"})
    rt = pr.build_runtime(sys.executable, pr.runtime_name(
        sys.version_info[:2], "0.1.81"), [])
    pr.write_state({"runtime": rt.name, "wheels_installed": {"bimforge": "0.1.81"},
                    "wheels": {"bimforge": {"version": "0.1.81",
                                            "path": "/gone/bimforge-0.1.81.whl"}}})
    pr.ensure(str(own), "calc-bim")
    assert Path(pr.read_state()["wheels"]["bimforge"]["path"]).is_file()


def test_a_second_plugin_at_the_same_version_installs_into_the_same_runtime(
        home, tmp_path, monkeypatch):
    """calc-bim built the runtime; estimating-core then arrives at the same
    version. Rebuilding 58 packages to add one wheel would be absurd."""
    plugins = tmp_path / "plugins"
    own = _plugin(plugins, "estimating-core", {"estimating_tools": "0.1.81"})
    _plugin(plugins, "calc-bim", {"bimforge": "0.1.81"})
    name = pr.runtime_name(sys.version_info[:2], "0.1.81")
    rt = pr.build_runtime(sys.executable, name, [])
    pr.write_state({"runtime": name, "wheels_installed": {"bimforge": "0.1.81"}})

    installed = []
    monkeypatch.setattr(pr, "_pip", lambda py, args: installed.append(args) or True)
    monkeypatch.setattr(pr, "find_python", lambda: (sys.executable,
                                                    sys.version_info[:2]))
    monkeypatch.setattr(pr, "build_runtime",
                        lambda *a: pytest.fail("rebuilt instead of installing"))
    line = pr.ensure(str(own), "estimating-core")
    assert "installed into" in line
    assert len(installed) == 1
    assert [s for s in installed[0] if "estimating_tools-" in s]
    assert not [s for s in installed[0] if "bimforge-" in s], \
        "reinstalled a wheel that was already at the wanted version"
    assert pr.read_state()["wheels_installed"] == {"bimforge": "0.1.81",
                                                   "estimating_tools": "0.1.81"}
    assert pr.read_state()["runtime"] == name


def test_a_version_roll_builds_a_new_runtime_and_keeps_one_previous(
        home, tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    own = _plugin(plugins, "calc-bim", {"bimforge": "0.1.82"})
    for old in ("py3.12-0.1.79", "py3.12-0.1.80"):
        _fake_ready(old)
    pr.write_state({"runtime": "py3.12-0.1.80", "previous": "py3.12-0.1.79",
                    "wheels_installed": {"bimforge": "0.1.80"}})
    monkeypatch.setattr(pr, "find_python", lambda: (sys.executable, (3, 12)))
    monkeypatch.setattr(pr, "_pip", lambda *a: True)
    line = pr.ensure(str(own), "calc-bim")
    assert "installed into" in line
    state = pr.read_state()
    assert state["runtime"] == "py3.12-0.1.82"
    assert state["previous"] == "py3.12-0.1.80"
    assert sorted(p.name for p in pr.runtimes_dir().iterdir()) == [
        "py3.12-0.1.80", "py3.12-0.1.82"], "the oldest runtime was not pruned"


def test_ensure_with_no_usable_interpreter_says_so_and_exits_clean(
        home, tmp_path, monkeypatch):
    own = _plugin(tmp_path / "plugins", "calc-bim", {"bimforge": "0.1.81"})
    monkeypatch.setattr(pr, "find_python", lambda: None)
    line = pr.ensure(str(own), "calc-bim")
    assert "no Python between 3.10 and 3.14" in line


def test_a_failed_build_suggests_the_manual_command(home, tmp_path, monkeypatch):
    own = _plugin(tmp_path / "plugins", "calc-bim",
                  {"bimforge": "0.1.81", "estimating_tools": "0.1.81"})
    monkeypatch.setattr(pr, "find_python", lambda: (sys.executable, (3, 12)))
    monkeypatch.setattr(pr, "build_runtime", lambda *a: None)
    line = pr.ensure(str(own), "estimating-core")
    assert "could not be built" in line
    # Both wheels, because the estimating one alone is unsatisfiable.
    assert "bimforge-" in line and "estimating_tools-" in line


def test_a_version_roll_forgets_the_old_runtimes_extras(home, tmp_path, monkeypatch):
    """Extras are installed INTO a runtime, so a new runtime has none of them."""
    own = _plugin(tmp_path / "plugins", "calc-bim", {"bimforge": "0.1.82"})
    pr.write_state({"runtime": "py3.12-0.1.81", "extras": {"bimforge": ["solids"]},
                    "wheels_installed": {"bimforge": "0.1.81"}})
    monkeypatch.setattr(pr, "find_python", lambda: (sys.executable, (3, 12)))
    monkeypatch.setattr(pr, "_pip", lambda *a: True)
    pr.ensure(str(own), "calc-bim")
    assert pr.read_state()["extras"] == {}


# ---- extras on demand -------------------------------------------------------

def _ready_runtime(home_dir, wheel_path="/w/bimforge-0.1.81-py3-none-any.whl"):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    pr.write_state({"runtime": rt.name,
                    "wheels": {"bimforge": {"version": "0.1.81",
                                            "path": wheel_path}}})
    return rt


def test_an_unknown_extra_is_refused_by_name(home, capsys):
    assert pr.ensure_extra("nope") == 2
    assert "unknown extra" in capsys.readouterr().err


def test_ensure_extra_without_a_runtime_says_how_to_get_one(home, capsys):
    assert pr.ensure_extra("solids") == 1
    assert "no plugin runtime yet" in capsys.readouterr().err


def test_ensure_extra_installs_from_the_recorded_wheel_never_the_registry(
        home, tmp_path, monkeypatch, capsys):
    """`pip install bimforge[solids]` would reach PyPI and could resolve a
    different version than the plugin bundles. The recorded wheel path is the
    only acceptable source."""
    wheel = tmp_path / "bimforge-0.1.81-py3-none-any.whl"
    wheel.write_text("", encoding="utf-8")
    _ready_runtime(home, str(wheel))
    seen = []
    monkeypatch.setattr(pr, "_pip", lambda py, args: seen.append(args) or True)
    assert pr.ensure_extra("solids") == 0
    assert seen == [[f"{wheel}[solids]"]]
    assert pr.read_state()["extras"] == {"bimforge": ["solids"]}
    assert "installed" in capsys.readouterr().out


def test_ensure_extra_is_idempotent(home, tmp_path, monkeypatch, capsys):
    wheel = tmp_path / "bimforge-0.1.81-py3-none-any.whl"
    wheel.write_text("", encoding="utf-8")
    _ready_runtime(home, str(wheel))
    monkeypatch.setattr(pr, "_pip", lambda *a: True)
    pr.ensure_extra("solids")
    capsys.readouterr()
    seen = []
    monkeypatch.setattr(pr, "_pip", lambda py, args: seen.append(args) or True)
    assert pr.ensure_extra("solids") == 0
    assert seen == [], "reinstalled an extra that was already recorded"
    assert "already installed" in capsys.readouterr().out


def test_ensure_extra_flips_only_the_capability_asked_for(home, tmp_path, monkeypatch):
    """Per-capability readiness is what stops a correct base install looking
    broken (the nine-module all-or-nothing probe)."""
    wheel = tmp_path / "bimforge-0.1.81-py3-none-any.whl"
    wheel.write_text("", encoding="utf-8")
    _ready_runtime(home, str(wheel))
    monkeypatch.setattr(pr, "_pip", lambda *a: True)
    pr.ensure_extra("solids")
    assert pr.read_state()["extras"]["bimforge"] == ["solids"]
    pr.ensure_extra("terrain")
    assert pr.read_state()["extras"]["bimforge"] == ["solids", "terrain"]


def test_a_vanished_wheel_asks_for_a_restart_rather_than_reaching_out(
        home, tmp_path, monkeypatch, capsys):
    _ready_runtime(home, "/gone/bimforge-0.1.81-py3-none-any.whl")
    monkeypatch.setattr(pr, "_pip",
                        lambda *a: pytest.fail("ran pip with no wheel to install"))
    assert pr.ensure_extra("solids") == 1
    assert "restart the session" in capsys.readouterr().err


def test_every_on_demand_extra_names_a_real_wheel():
    assert set(pr.EXTRA_OWNER.values()) <= set(pr.BASE_EXTRAS)


# ---- the CLI the hooks and the MCP launcher use ------------------------------

def test_python_path_reports_the_runtime_and_fails_when_there_is_none(home, capsys):
    assert pr.main(["python-path"]) == 1
    rt = pr.build_runtime(sys.executable, "py-test", [])
    pr.write_state({"runtime": rt.name})
    assert pr.main(["python-path"]) == 0
    assert capsys.readouterr().out.strip() == str(pr.venv_python(rt))


def test_python_path_ignores_a_runtime_that_is_recorded_but_gone(home, capsys):
    """A pruned or hand-deleted runtime must not be handed to the MCP launcher."""
    pr.write_state({"runtime": "py3.12-0.1.81"})
    assert pr.runtime_python() is None
    assert pr.main(["python-path"]) == 1


def test_an_unknown_subcommand_is_a_usage_error(home, capsys):
    assert pr.main(["frobnicate"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_serve_without_a_script_is_a_usage_error(home, capsys):
    assert pr.main(["serve"]) == 2


def test_the_interpreter_gets_a_shim_too(home):
    """Nine skills run `python -c "import estimating_tools..."`. The wheels are
    now only in the plugin's runtime, so those skills need a path to ITS
    interpreter or they import nothing."""
    rt = pr.build_runtime(sys.executable, "py-test", [])
    pr.write_python_shim(rt)
    shim = pr.bin_dir() / "est-python"
    assert shim.is_file()
    assert str(pr.venv_python(rt)) in shim.read_text(encoding="utf-8")


@pytest.mark.skipif(WINDOWS, reason="POSIX shim execution")
def test_the_interpreter_shim_is_the_runtimes_interpreter(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    pr.write_python_shim(rt)
    out = subprocess.run([str(pr.bin_dir() / "est-python"), "-c",
                          "import sys; print(sys.executable)"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    assert Path(out.stdout.strip()).resolve() == pr.venv_python(rt).resolve()


def test_refreshing_bin_keeps_our_own_two_shims(home):
    rt = pr.build_runtime(sys.executable, "py-test", [])
    _stub_console_script(rt, "est-bim")
    pr._refresh_bin(rt, {"runtime": rt.name})
    for name in ("ensure-extra", "est-python", "est-bim"):
        assert (pr.bin_dir() / name).is_file(), name


# ---- the hook must not hold a session shut -----------------------------------

def test_claim_wait_cannot_hang_a_session_start():
    """`_claim` waits inside a SessionStart hook, so CLAIM_WAIT is a cap on how
    long opening a session can stall.

    It was 1800 -- half an hour -- while the comment beside it said waiting
    "costs seconds". A live Windows machine produced a runtime named
    `py3.14-0.1.82-<pid>`, and that name is only reachable after this wait is
    exhausted, so the stall was real rather than theoretical.
    """
    assert pr.CLAIM_WAIT <= 300.0, (
        "CLAIM_WAIT runs in a SessionStart hook; minutes are the ceiling, not "
        "tens of minutes")


def test_abandoned_after_stays_generous_because_age_is_a_coarse_signal():
    """The opposite bound, and the reason it is not also small: `_age` reads the
    runtime directory's mtime, which does not move while pip writes deep inside
    it. Shrink this and a live slow build starts looking abandoned -- and the
    abandoned branch calls `rmtree` on it."""
    assert pr.ABANDONED_AFTER >= 1800.0
    assert pr.ABANDONED_AFTER > pr.CLAIM_WAIT, (
        "a waiting session must give up and build alongside BEFORE it would "
        "judge the peer abandoned and delete it")
