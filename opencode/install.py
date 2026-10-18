#!/usr/bin/env python3
"""Install the estimating platform into OpenCode.

OpenCode has no plugin bundle and no SessionStart hook, so installing means
doing three separate things, in this order, each idempotent:

  runtime  build or refresh the SAME shared runtime the Claude Code plugin uses
           (~/.estimating: one venv holding the bundled estimating_tools and
           bimforge wheels, plus the ~/.estimating/bin/ shims), by calling the
           plugin's own plugin_runtime.ensure() on this checkout's bundled
           wheels. If it fails, nothing else is written. A runtime NEWER than
           this checkout (the Claude plugin got there first) is not downgraded
           without --force.
  skills   port every plugin SKILL.md with OpenCode's tool names into
           ~/.config/opencode/skills/ (or <project>/.opencode/skills/ with
           --project). The skills keep their literal ~/.estimating/bin/ paths.
  mcp      merge bidmanager + conformed (from the generated it/opencode.json)
           and a local artifact-editor server into opencode.json. An entry this
           installer wrote is upgraded when the source changes; an entry the
           user wrote or edited is kept, with a diff of what would change.

The global config directory is $XDG_CONFIG_HOME/opencode, else
~/.config/opencode -- on Windows too. Re-run after pulling a new release to
upgrade; an unchanged install reports "up to date".

Examples
--------
    python opencode/install.py                    # global install
    python opencode/install.py --dry-run          # show what would change
    python opencode/install.py --project ~/bids/hwy-41

Stdlib only and 3.10-compatible: it runs before anything of ours is installed.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    # --dry-run must write nothing, and that includes __pycache__ beside the
    # modules imported below.
    sys.dont_write_bytecode = True

import argparse  # noqa: E402
import difflib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "estimating-core"
MCP_SRC = REPO_ROOT / "it" / "opencode.json"

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "openworker"))
import plugin_runtime  # noqa: E402  (the Claude plugin's runtime, not a copy)
import port_skills  # noqa: E402

LABEL = "opencode"
RERUN = "re-run python opencode/install.py"

#: Written into every skill folder this installer creates. Only a folder that
#: carries it is ever updated or removed, so a user's own skill -- even one
#: that shares a name with ours -- is never touched.
MARKER = ".installed-by-estimating-opencode"
MARKER_TEXT = ("Installed by opencode/install.py from the estimating-plugin repository.\n"
               "Re-running the installer may replace or remove this folder; delete this\n"
               "file to keep your own edits.\n")

#: Beside opencode.json: a hash of each MCP entry this installer wrote. An
#: entry still matching its hash is ours to upgrade; anything else is the
#: user's and is kept.
MCP_RECORD = ".estimating-opencode-mcp.json"

SCHEMA = "https://opencode.ai/config.json"


class ConfigError(Exception):
    """opencode.json cannot be merged safely."""


# -- OpenCode locations --------------------------------------------------------
def config_dir() -> Path:
    """OpenCode's global config directory.

    OpenCode resolves it with xdg-basedir: $XDG_CONFIG_HOME/opencode, else
    ~/.config/opencode on every platform (Windows included -- not %APPDATA%).
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "opencode"


def _project(project: str) -> Path:
    return Path(project).expanduser().resolve()


def skills_dest(project: str | None) -> Path:
    if project:
        return _project(project) / ".opencode" / "skills"
    return config_dir() / "skills"


def config_path(project: str | None) -> Path:
    """opencode.json, or an existing opencode.jsonc when there is no .json."""
    base = _project(project) if project else config_dir()
    for name in ("opencode.json", "opencode.jsonc"):
        if (base / name).is_file():
            return base / name
    return base / "opencode.json"


# -- runtime -------------------------------------------------------------------
def _names(versions: dict) -> str:
    return " + ".join(f"{d} {v}" for d, v in sorted(versions.items()))


def for_opencode(line: str) -> str:
    """plugin_runtime's advice is written for Claude Code sessions; say what
    fixes it here instead. plugin_runtime itself is left unchanged."""
    line = line.replace("reinstall the estimating-platform plugins (/plugin), then "
                        "restart the session", f"pull this checkout, then {RERUN}")
    line = line.replace("restart the session so the hook re-records it", RERUN)
    line = line.replace("restart the session", RERUN)
    if "suggest the user run: pip install" in line:
        line += (f" -- under OpenCode, fix the cause and {RERUN} instead: a pip install "
                 "into another interpreter does not create the ~/.estimating/bin/ shims")
    return line


def newer_than_checkout(installed: dict, want: dict) -> dict:
    """The dists whose installed version is newer than this checkout's."""
    return {d: v for d, v in (installed or {}).items()
            if d in want
            and plugin_runtime.version_key(v) > plugin_runtime.version_key(want[d])}


def install_runtime(*, dry_run: bool, force: bool = False) -> tuple[bool, str]:
    """Make ~/.estimating current for this checkout's bundled wheels.

    Returns `(ok, line)`. plugin_runtime owns every decision (which python,
    venv naming, shims, pruning); this checks the outcome. Success means the
    recorded runtime now holds EXACTLY this checkout's versions -- an older
    runtime that is still ready after a failed upgrade is a failure.
    """
    wheels = plugin_runtime.discover_wheels(str(PLUGIN_ROOT))
    if not wheels:
        return False, (f"no bundled wheels found under {PLUGIN_ROOT / 'dist'} -- "
                       "is this a full checkout of the repository?")
    want = {d: w["version"] for d, w in wheels.items()}
    installed = plugin_runtime.read_state().get("wheels_installed") or {}
    newer = newer_than_checkout(installed, want)
    if newer and not force:
        return False, (f"the shared runtime holds {_names(newer)}, newer than this "
                       f"checkout's {_names(want)}. It is shared with the Claude Code "
                       "plugin, so it was left alone: pull this checkout to that release "
                       "and re-run, or pass --force to downgrade it")
    rt = plugin_runtime.current_runtime()
    fresh = (rt is not None and installed == want
             and (plugin_runtime.bin_dir() / "est-artifact-app").is_file())
    if dry_run:
        if fresh:
            return True, f"up to date ({_names(want)} in {rt})"
        verb = "downgrade" if newer else "build/refresh"
        return True, (f"would {verb} the shared runtime at "
                      f"{plugin_runtime.runtime_home()} to {_names(want)} "
                      "(a venv + pip install; minutes on first run)")
    line = for_opencode(plugin_runtime.ensure(str(PLUGIN_ROOT), LABEL))
    got = plugin_runtime.read_state().get("wheels_installed") or {}
    if plugin_runtime.current_runtime() is None or got != want:
        if got and got != want:
            line += f" (the runtime still holds {_names(got)}, not {_names(want)})"
        return False, line
    if fresh:
        return True, f"up to date ({_names(want)} in {rt})"
    return True, line


# -- skills --------------------------------------------------------------------
def _desired_skills() -> dict[str, dict[str, bytes]]:
    """`{name: {relative path: bytes}}` for every ported skill, marker included."""
    out: dict[str, dict[str, bytes]] = {}
    for name, src, text, _stats, refs in port_skills.ported_skills(
            port_skills.port_body_opencode):
        files = {MARKER: MARKER_TEXT.encode("utf-8"), "SKILL.md": text.encode("utf-8")}
        for ref in refs:
            files[ref.relative_to(src.parent).as_posix()] = ref.read_bytes()
        out[name] = files
    return out


def _current_files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob("*") if p.is_file()}


def _write_skill(folder: Path, files: dict[str, bytes]) -> None:
    """Stage the folder beside its target, then swap it in.

    A crash mid-write leaves a dot-prefixed staging folder (which carries the
    marker, so the next run prunes it), never a half-written skill under its
    real name.
    """
    stage = folder.with_name(f".{folder.name}.new-{os.getpid()}")
    old = folder.with_name(f".{folder.name}.old-{os.getpid()}")
    for leftover in (stage, old):
        if leftover.exists():
            shutil.rmtree(leftover)
    for rel, data in files.items():          # MARKER is first in `files`
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if folder.exists():
        os.replace(folder, old)
    os.replace(stage, folder)
    if old.exists():
        shutil.rmtree(old)


def install_skills(dest: Path, *, dry_run: bool) -> dict[str, list[str]]:
    """Write our skills into `dest`; returns names by outcome.

    added / updated / unchanged / removed concern folders we own (they carry
    MARKER); kept lists same-named folders without it, which are a user's and
    are left alone.
    """
    try:
        desired = _desired_skills()
    except ValueError as exc:
        raise SystemExit(f"cannot port the skills: {exc}")
    r: dict[str, list[str]] = {k: [] for k in
                               ("added", "updated", "unchanged", "removed", "kept")}
    for name, files in sorted(desired.items()):
        folder = dest / name
        if folder.exists() and not (folder / MARKER).is_file():
            r["kept"].append(name)
            continue
        if not folder.exists():
            r["added"].append(name)
        elif _current_files(folder) == files:
            r["unchanged"].append(name)
            continue
        else:
            r["updated"].append(name)
        if not dry_run:
            _write_skill(folder, files)
    if dest.is_dir():
        for folder in sorted(dest.iterdir()):
            if (folder.is_dir() and folder.name not in desired
                    and (folder / MARKER).is_file()):
                if not folder.name.startswith("."):
                    r["removed"].append(folder.name)
                if not dry_run:
                    shutil.rmtree(folder)
    return r


# -- MCP -----------------------------------------------------------------------
def artifact_editor_command(windows: bool = plugin_runtime.WINDOWS) -> list[str]:
    """The artifact-editor server's command: the runtime's est-artifact-app shim.

    The shim path is stable across runtime upgrades (only its target moves),
    so the config never goes stale. On Windows the shim is a `.cmd`, which a
    process spawn cannot exec directly, so it runs under cmd.exe.
    """
    shim = plugin_runtime.bin_dir() / "est-artifact-app"
    if windows:
        return ["cmd.exe", "/d", "/c", str(shim) + ".cmd"]
    return [str(shim)]


def our_servers() -> dict[str, dict]:
    generated = json.loads(MCP_SRC.read_text(encoding="utf-8"))["mcp"]
    servers = dict(generated)
    servers["artifact-editor"] = {"type": "local", "command": artifact_editor_command(),
                                  "enabled": True}
    return servers


def entry_hash(entry) -> str:
    canon = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _record_path(config: Path) -> Path:
    return config.with_name(MCP_RECORD)


def _read_record(config: Path) -> dict[str, str]:
    try:
        rec = json.loads(_record_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    servers = rec.get("servers") if isinstance(rec, dict) else None
    return {k: v for k, v in (servers or {}).items() if isinstance(v, str)}


def _write_json(path: Path, data, indent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _indent_of(text: str):
    """The indent an existing file uses (spaces or a tab), else 2."""
    m = re.search(r'^([ \t]+)"', text, re.MULTILINE)
    if not m:
        return 2
    return "\t" if m.group(1).startswith("\t") else len(m.group(1))


def load_config(path: Path) -> dict | None:
    """The parsed config, None if absent. Raises ConfigError rather than risk
    rewriting a file it cannot round-trip (JSONC comments, trailing commas)."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        cfg = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as exc:
        block = json.dumps({"mcp": our_servers()}, indent=2, ensure_ascii=False)
        raise ConfigError(
            f"{path} is not plain JSON ({exc.msg}, line {exc.lineno}) -- most likely "
            "JSONC comments or trailing commas. Rewriting it would lose them, so it was "
            "left untouched. Add the servers below to its \"mcp\" block by hand and "
            "re-run with --no-mcp:\n" + block)
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path} is not a JSON object; fix or move it, then re-run")
    if not isinstance(cfg.get("mcp", {}), dict):
        raise ConfigError(f"{path}: \"mcp\" is not an object; fix it, then re-run")
    return cfg


def _diff(key: str, current, ours) -> str:
    a = json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    b = json.dumps(ours, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    return "\n".join(difflib.unified_diff(a, b, f"{key} (yours)", f"{key} (this release)",
                                          lineterm=""))


def install_mcp(path: Path, *, dry_run: bool) -> dict:
    """Merge our servers into `path`.

    Returns names as added / upgraded / unchanged / kept, plus `diffs`
    {name: unified diff} for each kept entry. An entry is upgraded only when
    it still matches the hash recorded when this installer wrote it; one the
    user wrote or edited is kept, never replaced.
    """
    cfg = load_config(path)
    indent = _indent_of(path.read_text(encoding="utf-8")) if cfg is not None else 2
    if cfg is None:
        cfg = {"$schema": SCHEMA}
    record = _read_record(path)
    new_record = dict(record)
    servers = dict(cfg.get("mcp") or {})
    r: dict = {"added": [], "upgraded": [], "unchanged": [], "kept": [], "diffs": {}}
    for key, entry in our_servers().items():
        if key not in servers:
            servers[key] = entry
            r["added"].append(key)
        elif servers[key] == entry:
            r["unchanged"].append(key)
        elif record.get(key) == entry_hash(servers[key]):
            servers[key] = entry
            r["upgraded"].append(key)
        else:
            r["kept"].append(key)
            r["diffs"][key] = _diff(key, servers[key], entry)
            continue
        new_record[key] = entry_hash(entry)
    if dry_run:
        return r
    if r["added"] or r["upgraded"]:
        cfg["mcp"] = servers
        _write_json(path, cfg, indent)
    if new_record != record:
        _write_json(_record_path(path), {
            "about": "Hashes of the MCP entries opencode/install.py wrote; an entry "
                     "still matching its hash is upgraded on re-run.",
            "servers": new_record}, 2)
    return r


# -- CLI -----------------------------------------------------------------------
def _ascii(text: str) -> str:
    """Plain ASCII for Windows consoles (cp437/cp1252), whose codecs garble or
    reject the dashes plugin_runtime's messages use."""
    text = text.replace("—", "--").replace("–", "-").replace("→", "->")
    return text.encode("ascii", "replace").decode("ascii")


def _skills_line(r: dict[str, list[str]], verb: str) -> str:
    parts = []
    for key in ("added", "updated", "removed"):
        if r[key]:
            parts.append(f"{verb}{key} {len(r[key])}")
    if r["unchanged"]:
        parts.append(f"{len(r['unchanged'])} up to date")
    if r["kept"]:
        parts.append(f"kept existing {', '.join(r['kept'])} (not ours)")
    return "; ".join(parts) or "nothing to do"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", metavar="DIR",
                    help="install skills + opencode.json into DIR instead of globally "
                         "(the runtime is always the shared ~/.estimating)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print every action without writing anything")
    ap.add_argument("--no-runtime", action="store_true",
                    help="skip building the ~/.estimating runtime")
    ap.add_argument("--no-mcp", action="store_true", help="leave opencode.json alone")
    ap.add_argument("--force", action="store_true",
                    help="downgrade a shared runtime that is newer than this checkout")
    args = ap.parse_args(argv)
    try:   # a non-ASCII home path must not crash the report on a legacy console
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):   # pragma: no cover - replaced stdout
        pass

    tag = "[dry-run] " if args.dry_run else ""
    verb = "would be " if args.dry_run else ""
    sd = skills_dest(args.project)
    cp = config_path(args.project)

    # Refuse an unmergeable config BEFORE writing anything, so a refusal never
    # leaves a half-done install behind.
    if not args.no_mcp:
        try:
            load_config(cp)
        except ConfigError as exc:
            raise SystemExit(f"opencode/install.py: {exc}")

    ok = True
    changed = False
    if args.no_runtime:
        print(f"{tag}runtime: skipped (--no-runtime)")
    else:
        ok, line = install_runtime(dry_run=args.dry_run, force=args.force)
        changed |= not line.startswith("up to date")
        print(f"{tag}runtime: {_ascii(line)}")
        if not ok and not args.dry_run:
            # The skills name ~/.estimating/bin/ tools; rewriting them for a
            # release whose runtime is not there would point at missing tools.
            print("\nThe runtime is not at this checkout's version, so the skills and "
                  "opencode.json were left as they were. Fix the problem above and re-run.")
            return 1

    r = install_skills(sd, dry_run=args.dry_run)
    changed |= bool(r["added"] or r["updated"] or r["removed"])
    print(f"{tag}skills:  {_skills_line(r, verb)} -> {sd}")
    for key in ("added", "updated", "removed"):
        if r[key] and args.dry_run:
            print(f"{tag}  {key}: {', '.join(r[key])}")

    if args.no_mcp:
        print(f"{tag}mcp:     skipped (--no-mcp)")
    else:
        m = install_mcp(cp, dry_run=args.dry_run)
        changed |= bool(m["added"] or m["upgraded"])
        parts = []
        for key, label in (("added", "add"), ("upgraded", "upgrade")):
            if m[key]:
                done = f"would {label}" if args.dry_run else key
                parts.append(f"{done} {', '.join(m[key])}")
        if m["unchanged"]:
            parts.append(f"{', '.join(m['unchanged'])} up to date")
        if m["kept"]:
            parts.append(f"kept existing {', '.join(m['kept'])}")
        print(f"{tag}mcp:     {'; '.join(parts)} -> {cp}")
        if "artifact-editor" in m["added"] + m["upgraded"]:
            print(f"{tag}  artifact-editor: {' '.join(artifact_editor_command())}")
        for key, diff in m["diffs"].items():
            print(f"{tag}  {key} differs from this release and was kept as you have it. "
                  "To take the release's entry, replace yours with the + lines:")
            print("\n".join("    " + ln for ln in diff.splitlines()))

    if not ok:
        print("\nThe runtime would not be at this checkout's version; see above.")
        return 1
    if args.dry_run:
        print("\nDry run: nothing was written. Re-run without --dry-run to apply.")
    elif not changed:
        print("\nEverything is up to date.")
    # Plain ASCII: this prints to Windows consoles whose cp1252 codec cannot
    # encode arrows or dashes.
    print(
        "\nNext:\n"
        "  1. Restart OpenCode so it re-reads its skills and opencode.json.\n"
        "  2. The first use of bidmanager prompts a sign-in, or sign in ahead of time:\n"
        "       opencode mcp auth bidmanager      (and: opencode mcp auth conformed)\n"
        "  3. Upgrade later by pulling this repository and re-running\n"
        "     python opencode/install.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
