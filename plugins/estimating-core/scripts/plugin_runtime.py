#!/usr/bin/env python3
"""The plugins' own Python runtime: one shared venv at a fixed, host-independent path.

Spec: docs/superpowers/specs/2026-09-27-plugin-runtime-design.md

WHY THIS EXISTS. Four mechanisms used to locate the interpreter that must import
our wheels, and they disagreed: the SessionStart hooks resolved one from the cwd
($VIRTUAL_ENV -> $CLAUDE_PROJECT_DIR/.venv -> ./.venv -> ./venv -> sys.executable),
skills invoked bare console scripts on PATH, the artifact-editor MCP launcher
exec'd bare `python3`, and a consumer project used its own venv. Which
interpreter received the wheel was a function of where the shell was standing.

THREE CONSTRAINTS shape every choice below, and each one kills an obvious fix:

1. `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PROJECT_DIR` are NOT in the agent's shell
   environment -- the host expands them in hooks.json/.mcp.json only. A skill
   cannot name the plugin's own directory, so the runtime path must be a
   CONSTANT, not something discovered.
2. The system interpreter is PEP-668 externally managed on the mainstream
   targets (Debian/Ubuntu/WSL, Homebrew). `pip install` into it fails, and so
   does `--user`. But PEP-668 does not apply inside a fresh venv, and stdlib
   `venv` is always available. That is the opening this module uses.
3. PATH is not a channel we control, and editing shell configuration is
   intrusive and subtle. So nothing here writes to shell config; callers use
   absolute paths under `bin_dir()`.

ONE PATH ON EVERY PLATFORM, and no `XDG_DATA_HOME`. The design's whole value is
that a skill can hardcode the shim path, so the path must be a constant for the
SAME reason it cannot be `${CLAUDE_PLUGIN_ROOT}/...`: an environment variable in
the equation reintroduces exactly the defect this module exists to remove -- the
hook would resolve `$XDG_DATA_HOME/...` while the skill text says a literal
path, and they would differ on any machine that sets it. `%LOCALAPPDATA%` loses
the same way, and additionally is not expanded by the Git Bash the agent's shell
usually is on Windows.

So the root is `~/.estimating` on every platform. `~` is expanded by sh, bash,
zsh, Git Bash and PowerShell alike, and a dot-directory in $HOME is the
convention its neighbours already use -- `~/.claude`, `~/.cargo`, `~/.nvm`,
`~/.pyenv`. It is SHORT on purpose: this path appears in 116 command lines
across 37 SKILL.md files, and `~/.local/share/estimating-platform/bin/est-bim`
made every one of them harder to read than the command it was running.
`ESTIMATING_RUNTIME_HOME` remains for tests and for an operator who must
relocate the tree -- an explicit opt-in that also opts out of skill text being
literally correct.

STDLIB ONLY, and 3.10-compatible: this runs before anything is installed, on
whatever interpreter the host happened to start the hook with.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: Escape hatch for tests and for operators who must relocate the runtime.
HOME_ENV = "ESTIMATING_RUNTIME_HOME"

APP = ".estimating"

#: bimforge's own dependency `ifcopenshell` is `>=3.10,<3.15`, so "newest
#: available" is the wrong rule -- a 3.15 interpreter would build a venv whose
#: install then fails. The ceiling is exclusive.
PY_MIN = (3, 10)
PY_MAX_EXCLUSIVE = (3, 15)

WINDOWS = os.name == "nt"

#: Installed at session start. Deliberately NOT `bimforge[all]`, which pulls
#: build123d and the OCP CAD kernel: those are the `solids` extra, installed on
#: first use by `bin/ensure-extra`. See "Extras on demand, per capability".
BASE_EXTRAS = {
    "bimforge": ("bim", "draw"),
    "estimating_tools": ("plugin-core",),
}

#: Which wheel owns each on-demand extra. `ensure-extra <name>` needs this to
#: know which recorded wheel to install from; the names are the heavy ones plus
#: every extra a skill might reasonably ask for.
EXTRA_OWNER = {
    "solids": "bimforge",
    "terrain": "bimforge",
    "bim": "bimforge",
    "draw": "bimforge",
    "excel": "estimating_tools",
    "pdf": "estimating_tools",
    "docgen": "estimating_tools",
    "schedule": "estimating_tools",
    "estimate_spec": "estimating_tools",
    "profiles": "estimating_tools",
    "intake": "estimating_tools",
    "importers": "estimating_tools",
    "ies": "estimating_tools",
    "lighting": "estimating_tools",
    "thermal": "estimating_tools",
}

#: Names in a venv's bin/ that are the venv's own plumbing, not our tools.
_NOT_A_TOOL_PREFIXES = ("python", "pip", "activate", "Activate", "easy_install",
                        "wheel", "deactivate")


# ---- where things live ------------------------------------------------------

def runtime_home() -> Path:
    """The fixed root. Same string on every machine, in Claude Code and the
    desktop app, on POSIX and Windows, whatever the cwd -- see the module
    docstring for why no environment variable takes part in this."""
    override = os.environ.get(HOME_ENV)
    if override:
        return Path(override)
    return Path.home() / APP


def bin_dir() -> Path:
    """Where the shims live. The only path skills ever name."""
    return runtime_home() / "bin"


def runtimes_dir() -> Path:
    return runtime_home() / "runtimes"


def state_file() -> Path:
    return runtime_home() / "state.json"


def vendored_self() -> Path:
    """This module's copy inside the runtime root.

    `bin/ensure-extra` execs THIS path, never the plugin's copy: a marketplace
    update moves the plugin cache directory out from under an existing shim, and
    a shim that stops working after an update is the failure mode the fixed root
    exists to prevent.
    """
    return runtime_home() / "plugin_runtime.py"


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if WINDOWS else "bin")


def venv_python(venv: Path) -> Path:
    return venv_bin(venv) / ("python.exe" if WINDOWS else "python")


def runtime_name(py: tuple, version: str) -> str:
    """Runtimes are keyed by (python minor, platform version) -- ONE runtime for
    all plugins, holding both wheels. Per-plugin runtimes were rejected: see the
    spec's "One shared runtime" section."""
    return "py%d.%d-%s" % (py[0], py[1], version)


# ---- state ------------------------------------------------------------------

def read_state() -> dict:
    try:
        state = json.loads(state_file().read_text(encoding="utf-8"))
    except Exception:
        # Absent, truncated, or hand-edited into nonsense. A corrupt state file
        # must mean "rebuild", never "crash the session".
        return {}
    # Valid JSON is not necessarily a mapping: `[]` and `"x"` parse and then
    # meet `.get(...)` in every caller. Same contract as above -- a state file
    # we cannot use is a rebuild, not an AttributeError at SessionStart.
    return state if isinstance(state, dict) else {}


def write_state(state: dict) -> None:
    state_file().parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, state_file())


# ---- finding the wheels every installed plugin bundles ----------------------

def version_key(version: str):
    try:
        return tuple(int(x) for x in version.split("."))
    except ValueError:
        return (0,)


def wheel_info(path: str):
    """`(dist, version)` from a wheel filename, or None if it is not one."""
    parts = os.path.basename(path).split("-")
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


#: Where a sibling plugin's `dist/` sits relative to one plugin's root. Both
#: layouts are real and measured:
#:   repo checkout   <repo>/plugins/<plugin>/dist/
#:   marketplace     ~/.claude/plugins/cache/<market>/<plugin>/<version>/dist/
#: The cache holds every cached version at once (observed: calc-bim 0.1.76,
#: 0.1.77, 0.1.79, 0.1.80), so the glob deliberately matches them all and the
#: highest version of each dist wins -- which is also how cache skew between
#: two plugins resolves.
_DIST_GLOBS = (
    os.path.join("dist", "*.whl"),
    os.path.join("..", "*", "dist", "*.whl"),
    os.path.join("..", "..", "*", "*", "dist", "*.whl"),
)


def _is_plugin_dist(dist_dir: str) -> bool:
    """True only for a `dist/` belonging to an actual plugin.

    Without this, the repo-checkout glob would also match any `dist/` built
    under `packages/` (a stray `python -m build` output, or -- historically --
    the PyPI name-reservation stub whose import raised). A non-plugin wheel
    must be structurally unreachable, not merely outranked on version.
    """
    return os.path.isfile(os.path.join(dist_dir, os.pardir,
                                       ".claude-plugin", "plugin.json"))


def discover_wheels(plugin_root: str) -> dict:
    """`{dist: {"version": str, "path": str}}` across every installed plugin.

    The runtime is the union at the highest version present, so one hook builds
    a runtime the other plugin's skills can use too.
    """
    found: dict = {}
    for pattern in _DIST_GLOBS:
        for path in glob.glob(os.path.join(plugin_root, pattern)):
            if not _is_plugin_dist(os.path.dirname(path)):
                continue
            info = wheel_info(path)
            if info is None:
                continue
            dist, version = info
            if dist not in BASE_EXTRAS:
                continue
            best = found.get(dist)
            if best is None or version_key(version) > version_key(best["version"]):
                found[dist] = {"version": version,
                               "path": os.path.abspath(path)}
    return found


def platform_version(wheels: dict) -> str:
    """The version the runtime is named for: the highest across both wheels.

    The platform releases in lockstep, so in the steady state these agree; they
    differ only while a marketplace cache is mid-update.
    """
    return max((w["version"] for w in wheels.values()),
               key=version_key, default="0")


def install_specs(wheels: dict, dists=None) -> list:
    """pip arguments for `dists` (default: all), each wheel with its base extras.

    Both wheels go in ONE invocation when both are present: `estimating_tools`
    declares `bimforge` unconditionally and bimforge is on no registry, so the
    local wheel is the only thing that can satisfy it.
    """
    specs = []
    for dist in sorted(wheels):
        if dists is not None and dist not in dists:
            continue
        extras = BASE_EXTRAS.get(dist, ())
        suffix = "[%s]" % ",".join(extras) if extras else ""
        specs.append(wheels[dist]["path"] + suffix)
    return specs


# ---- finding an interpreter --------------------------------------------------

def _version_of(exe: str):
    """(major, minor) for `exe`, or None if it will not run or is out of range."""
    try:
        out = subprocess.run(
            [exe, "-c", "import sys; print('%d %d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        major, minor = (int(x) for x in out.stdout.split())
    except ValueError:
        return None
    return (major, minor)


def candidate_pythons() -> list:
    """Interpreters to try, best first. Explicit minors before bare names so the
    choice does not silently depend on what `python3` points at today."""
    names = ["python3.14", "python3.13", "python3.12", "python3.11", "python3.10"]
    found = [shutil.which(n) for n in names]
    found += [shutil.which("python3"), shutil.which("python"), sys.executable]
    return [f for f in found if f]


def find_python():
    """The best interpreter in [PY_MIN, PY_MAX_EXCLUSIVE), or None."""
    for exe in candidate_pythons():
        v = _version_of(exe)
        if v and PY_MIN <= v < PY_MAX_EXCLUSIVE:
            return exe, v
    return None


# ---- building a runtime -----------------------------------------------------

def _pip(python: Path, args: list) -> bool:
    cmd = [str(python), "-m", "pip", "install", "--quiet"] + args
    try:
        return subprocess.run(cmd, capture_output=True, timeout=1800).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


#: A venv directory with no `.ready` beside it is either a live build or an
#: abandoned one. Anything unready and older than this is abandoned, and is the
#: only garbage `prune` has to reason about.
#:
#: Deliberately generous, and it must stay that way: `_age` reads the RUNTIME
#: DIRECTORY's mtime, which does not change while pip writes deep inside it. A
#: legitimate slow build can therefore look old, and treating it as abandoned
#: means `rmtree` on a directory another session is still installing into.
ABANDONED_AFTER = 3600.0

#: How long a session that lost the directory claim waits for the winner before
#: building its own copy alongside it.
#:
#: This runs inside a SessionStart hook, so it is a cap on how long starting a
#: session can hang. It was 1800 -- half an hour -- against a docstring one
#: function below claiming "waiting costs seconds". A live machine proved the
#: gap: a contested claim on a slow Windows build produced a runtime named
#: `py3.14-0.1.82-<pid>`, which is only reachable after this wait runs out.
#:
#: Sized to cover a legitimate concurrent build instead: ~20s on Linux where
#: every dependency has a wheel, minutes on Windows where some are compiled.
#: Past that, building a second copy costs disk and finishes, where waiting
#: longer just holds the session shut.
CLAIM_WAIT = 300.0


def is_ready(runtime: Path) -> bool:
    """A runtime is usable only when the marker written LAST is there.

    `venv_python().is_file()` is not enough: `python -m venv` succeeds long
    before `pip install` does, so a crashed run leaves an interpreter with no
    wheels in it -- which then looks ready forever.
    """
    return venv_python(runtime).is_file() and (runtime / ".ready").is_file()


def _mark_ready(runtime: Path) -> None:
    tmp = runtime / ".ready.tmp"
    tmp.write_text("", encoding="utf-8")
    os.replace(tmp, runtime / ".ready")


def _age(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return 0.0


def _claim(name: str):
    """Claim a directory to build in. Returns `(path, must_build)` or None.

    WHY NOT `os.replace`. The obvious design -- build under a temp name and
    rename onto the final one -- does not work, and the failure is silent until
    a tool is run: `pip` bakes the BUILD-TIME absolute path into the shebang of
    every console script it installs, so a renamed venv yields
    `est-bim: exec: .../.tmp-w6g6oqs4/v/bin/python: not found`. The venv is
    therefore built where it will live, and `mkdir` -- atomic on POSIX and on
    Windows -- is what makes exactly one session the builder. A `.ready` marker,
    not the directory's existence, is what publishes it.
    """
    final = runtimes_dir() / name
    try:
        final.mkdir(parents=True)
        return final, True
    except FileExistsError:
        pass
    if is_ready(final):
        return final, False
    if _age(final) > ABANDONED_AFTER:
        # Nobody is coming back for it. Left in place it would wedge every
        # future session, so it is cleared and re-claimed.
        shutil.rmtree(final, ignore_errors=True)
        try:
            final.mkdir(parents=True)
            return final, True
        except FileExistsError:
            pass
    # Another session is building it right now -- both plugins' SessionStart
    # hooks can run at once, which is the race that actually happens. Waiting a
    # few minutes beats duplicating a 58-package install; waiting longer than
    # that does not, because this hook is holding the session start open. See
    # CLAIM_WAIT.
    deadline = time.time() + CLAIM_WAIT
    while time.time() < deadline:
        time.sleep(2.0)
        if is_ready(final):
            return final, False
        if _age(final) > ABANDONED_AFTER:
            break
    # It never finished. Build our own alongside it rather than fighting for the
    # name; `state.json` records whichever path won, and `prune` collects the
    # rest.
    mine = runtimes_dir() / ("%s-%d" % (name, os.getpid()))
    if mine.exists() and not is_ready(mine):
        shutil.rmtree(mine, ignore_errors=True)
    mine.mkdir(parents=True, exist_ok=True)
    return mine, not is_ready(mine)


def build_runtime(python: str, name: str, specs: list):
    """Create a runtime for `name` with `specs` installed. Returns it, or None.

    Built in place (see `_claim` for why a rename is not an option) and
    published by a `.ready` marker written after the install succeeds. Two
    sessions racing: one builds, the other waits for the marker.
    """
    ready = runtimes_dir() / name
    if is_ready(ready):
        return ready
    runtimes_dir().mkdir(parents=True, exist_ok=True)
    claimed = _claim(name)
    if claimed is None:                          # pragma: no cover - defensive
        return None
    target, must_build = claimed
    if not must_build:
        return target
    try:
        r = subprocess.run([python, "-m", "venv", str(target)],
                           capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        # A vanished or unusable interpreter must be a None, not a traceback:
        # every caller is a SessionStart hook that must exit 0.
        shutil.rmtree(target, ignore_errors=True)
        return None
    if r.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        return None
    # `pip install` with no arguments is a usage error, so an empty spec list
    # means "a bare venv", not "install nothing badly".
    if specs and not _pip(venv_python(target), specs):
        shutil.rmtree(target, ignore_errors=True)
        return None
    _mark_ready(target)
    return target


# ---- shims ------------------------------------------------------------------

def _dist_info_dirs(runtime: Path) -> list:
    """Every `*.dist-info` in the runtime, either platform's layout."""
    patterns = (os.path.join("lib", "python*", "site-packages", "*.dist-info"),
                os.path.join("Lib", "site-packages", "*.dist-info"))
    found = []
    for pattern in patterns:
        found += glob.glob(os.path.join(str(runtime), pattern))
    return found


def console_scripts(runtime: Path) -> list:
    """OUR console scripts, read from the two wheels' installed metadata.

    Neither listed nor scraped from `bin/`. A hardcoded list is how the skill
    instructions drifted from `[project.scripts]` in the first place; scraping
    `bin/` is worse, because a runtime's `bin/` also holds every DEPENDENCY's
    scripts -- an observed run produced shims for `jsonschema`, `mcp`,
    `uvicorn`, `ttx`, `f2py` and a dozen more, planting names we do not own in a
    directory the user may one day put on PATH. `entry_points.txt` names exactly
    the scripts our wheels declare, and it cannot drift from the wheel it is in.
    """
    import configparser

    names = set()
    for info in _dist_info_dirs(runtime):
        dist = os.path.basename(info).split("-")[0]
        if dist not in BASE_EXTRAS:
            continue
        path = os.path.join(info, "entry_points.txt")
        if not os.path.isfile(path):
            continue
        cp = configparser.ConfigParser()
        try:
            cp.read(path, encoding="utf-8")
        except configparser.Error:              # pragma: no cover - defensive
            continue
        if cp.has_section("console_scripts"):
            names.update(cp.options("console_scripts"))
    return sorted(names)


def _write_shim(name: str, command: str) -> None:
    """One shim, atomically.

    On Windows BOTH spellings are written: `<name>.cmd` for cmd.exe and
    PowerShell, and an extensionless `sh` script for the Git Bash the agent's
    shell usually is. That is what lets skill text name ONE path,
    `~/.estimating/bin/<name>`, on every platform.
    """
    bin_dir().mkdir(parents=True, exist_ok=True)
    bodies = [(name, '#!/bin/sh\n# Generated by the estimating-platform plugins.\n'
                     'exec %s "$@"\n' % command)]
    if WINDOWS:
        bodies.append((name + ".cmd",
                       '@echo off\r\nrem Generated by the estimating-platform '
                       'plugins.\r\n%s %%*\r\n' % command))
    for filename, body in bodies:
        shim = bin_dir() / filename
        tmp = shim.with_name(shim.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        if not filename.endswith(".cmd"):
            os.chmod(tmp, 0o755)
        os.replace(tmp, shim)


def write_shims(runtime: Path, scripts=None) -> list:
    """Point `bin/<script>` at `runtime`'s console scripts. Returns those written.

    Written to a temporary name and `os.replace`d into position, so a shim is
    never observed half-written. Skill paths never change across version rolls;
    only the shim's target does.
    """
    written = []
    for script in (console_scripts(runtime) if scripts is None else scripts):
        target = venv_bin(runtime) / (script + ".exe" if WINDOWS else script)
        if not target.exists():
            continue
        _write_shim(script, '"%s"' % target)
        written.append(script)
    return written


def write_extra_shim(runtime: Path) -> None:
    """`bin/ensure-extra`, which installs a heavy extra on first use.

    It runs the runtime's own python against the VENDORED copy of this module,
    so it keeps working after a marketplace update moves the plugin cache.
    """
    _write_shim("ensure-extra", '"%s" "%s" ensure-extra'
                % (venv_python(runtime), vendored_self()))


def write_python_shim(runtime: Path) -> None:
    """`bin/est-python`, the runtime's interpreter under a stable path.

    Nine skills run `python -c "import estimating_tools..."` or
    `python -m estimating_tools.pdf.extract_text`. Those used to work by
    accident, because the hook installed into whatever interpreter it resolved
    from the cwd. Now that the wheels live only in the plugin's own runtime,
    those skills need a path to ITS interpreter, or they import nothing.

    Named `est-python` rather than `python` so that what it is stays obvious in
    skill text and in a shell history.
    """
    _write_shim("est-python", '"%s"' % venv_python(runtime))


def vendor_self() -> None:
    """Copy this module next to `bin/`, for `bin/ensure-extra` to exec."""
    runtime_home().mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve()
    dst = vendored_self()
    if src == dst:
        return
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


# ---- pruning ----------------------------------------------------------------

def prune(keep: list) -> list:
    """Remove runtimes not named in `keep`. Returns what was removed.

    An unready directory younger than `ABANDONED_AFTER` is a build in flight --
    quite possibly the other plugin's hook, running right now -- and deleting it
    would break that session. Age is the only thing that distinguishes a live
    build from an abandoned one, so it is the only heuristic here.
    """
    removed = []
    if not runtimes_dir().is_dir():
        return removed
    for child in sorted(runtimes_dir().iterdir()):
        if child.name in keep:
            continue
        if not is_ready(child) and _age(child) <= ABANDONED_AFTER:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed.append(child.name)
    return removed


# ---- the hook body ----------------------------------------------------------

def _versions(wheels: dict) -> dict:
    return {dist: w["version"] for dist, w in wheels.items()}


def current_runtime():
    """The recorded runtime's path if it is present and usable, else None."""
    name = read_state().get("runtime")
    if not name:
        return None
    rt = runtimes_dir() / name
    return rt if is_ready(rt) else None


def runtime_python():
    """The recorded runtime's interpreter, or None. What `launch` resolves."""
    rt = current_runtime()
    return venv_python(rt) if rt else None


def ensure(plugin_root: str, label: str) -> str:
    """Make the shared runtime current for every wheel any plugin bundles.

    Returns ONE line of agent-visible context. Never raises: every caller is a
    SessionStart hook that must exit 0.
    """
    wheels = discover_wheels(plugin_root)
    if not wheels:
        return (f"{label}: no bundled wheels found near {plugin_root} — "
                "reinstall the estimating-platform plugins (/plugin), then "
                "restart the session")

    state = read_state()
    want = _versions(wheels)
    version = platform_version(wheels)
    rt = current_runtime()
    fresh = rt is not None and state.get("wheels_installed") == want

    if fresh:
        # The common case: a stat and a JSON read, no pip. Paths are refreshed
        # anyway because a marketplace update moves them without changing a
        # version, and `ensure-extra` installs from the recorded path.
        state["wheels"] = wheels
        write_state(state)
        _refresh_bin(rt, state)
        names = " + ".join(f"{d} {v}" for d, v in sorted(want.items()))
        return f"{label}: {names} ready ({rt})"

    found = find_python()
    if found is None:
        return (f"{label}: no Python between {PY_MIN[0]}.{PY_MIN[1]} and "
                f"{PY_MAX_EXCLUSIVE[0]}.{PY_MAX_EXCLUSIVE[1] - 1} was found, so "
                "the plugin runtime cannot be built — install one and restart "
                "the session")
    python, py = found
    name = runtime_name(py, version)
    existing = runtimes_dir() / name

    if is_ready(existing):
        # Same name, different wheel set: a second plugin arrived at the version
        # this runtime was already built for. Install into it rather than
        # rebuilding 58 packages to add one wheel.
        missing = [d for d in wheels if state.get("wheels_installed", {}).get(d)
                   != want[d]]
        if missing and not _pip(venv_python(existing), install_specs(wheels, missing)):
            return _unavailable(label, wheels, venv_python(existing))
        rt = existing
    else:
        rt = build_runtime(python, name, install_specs(wheels))
        if rt is None:
            return _unavailable(label, wheels, python)
        # `_claim` may have had to build alongside a concurrent one, so the
        # directory's name is not always `name`.
        name = rt.name

    previous = state.get("runtime")
    state = {
        "runtime": name,
        "python": str(venv_python(rt)),
        "python_version": "%d.%d" % py,
        "version": version,
        "wheels": wheels,
        "wheels_installed": want,
        "extras": state.get("extras", {}) if previous == name else {},
        # The immediately previous runtime is kept for rollback; everything
        # older goes.
        "previous": previous if previous and previous != name else state.get("previous"),
    }
    write_state(state)
    _refresh_bin(rt, state)
    prune([n for n in (name, state.get("previous")) if n])
    names = " + ".join(f"{d} {v}" for d, v in sorted(want.items()))
    return f"{label}: {names} installed into {rt}"


def _refresh_bin(runtime: Path, state: dict) -> None:
    """Rewrite the shims and the vendored module for `runtime`, and drop shims
    for scripts the wheels no longer declare."""
    vendor_self()
    state["shims"] = write_shims(runtime)
    write_extra_shim(runtime)
    write_python_shim(runtime)
    keep = set(state["shims"]) | {"ensure-extra", "est-python"}
    if bin_dir().is_dir():
        for child in bin_dir().iterdir():
            stem = child.name[:-4] if child.name.endswith(".cmd") else child.name
            if stem in keep or child.name.endswith(".tmp"):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
    write_state(state)


def _unavailable(label: str, wheels: dict, python) -> str:
    specs = " ".join('"%s"' % s for s in install_specs(wheels))
    return (f"{label}: the plugin runtime could not be built with {python} — "
            f"suggest the user run: pip install {specs}")


# ---- extras on demand -------------------------------------------------------

def ensure_extra(name: str) -> int:
    """Install one on-demand extra into the current runtime. Idempotent.

    Installs from the wheel path recorded in `state.json` and NEVER from a
    registry: the runtime must stay pinned to the exact wheel the plugin
    bundles, and a registry resolution could pick a different version.
    """
    owner = EXTRA_OWNER.get(name)
    if owner is None:
        print("ensure-extra: unknown extra %r (known: %s)"
              % (name, ", ".join(sorted(EXTRA_OWNER))), file=sys.stderr)
        return 2
    state = read_state()
    rt = current_runtime()
    if rt is None:
        print("ensure-extra: no plugin runtime yet — start a session with the "
              "estimating-platform plugins installed, which builds it",
              file=sys.stderr)
        return 1
    if name in state.get("extras", {}).get(owner, []):
        print("ensure-extra: %s[%s] already installed" % (owner, name))
        return 0
    wheel = state.get("wheels", {}).get(owner, {}).get("path")
    if not wheel or not os.path.isfile(wheel):
        print("ensure-extra: the %s wheel recorded in state.json is gone (%s) — "
              "restart the session so the hook re-records it" % (owner, wheel),
              file=sys.stderr)
        return 1
    if not _pip(venv_python(rt), ["%s[%s]" % (wheel, name)]):
        print("ensure-extra: installing %s[%s] failed (network?)" % (owner, name),
              file=sys.stderr)
        return 1
    state.setdefault("extras", {}).setdefault(owner, [])
    if name not in state["extras"][owner]:
        state["extras"][owner].append(name)
        state["extras"][owner].sort()
    write_state(state)
    print("ensure-extra: %s[%s] installed" % (owner, name))
    return 0


# ---- CLI --------------------------------------------------------------------

def _plugin_root_of(script: str) -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(script)))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "ensure"
    rest = argv[1:]

    if cmd == "ensure":
        label = rest[0] if rest else "estimating-platform"
        print(ensure(_plugin_root_of(__file__), label))
        return 0

    if cmd == "ensure-extra":
        if not rest:
            print("usage: ensure-extra <name>", file=sys.stderr)
            return 2
        return ensure_extra(rest[0])

    if cmd == "python-path":
        python = runtime_python()
        if python is None:
            return 1
        print(python)
        return 0

    if cmd == "serve":
        # The MCP launcher's whole body: make the runtime current, then hand the
        # process to its interpreter. Diagnostics go to stderr because stdout is
        # the MCP stdio protocol.
        if not rest:
            print("usage: serve <script> [args...]", file=sys.stderr)
            return 2
        print(ensure(_plugin_root_of(__file__), "estimating-core"), file=sys.stderr)
        python = runtime_python()
        if python is None:
            print("estimating-core: no plugin runtime, so the artifact-editor "
                  "server cannot start; sessions fall back to the artifact/file "
                  "display path", file=sys.stderr)
            return 1
        os.execv(str(python), [str(python)] + rest)

    print("usage: plugin_runtime.py [ensure <label>|ensure-extra <name>|"
          "python-path|serve <script>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
