#!/usr/bin/env python3
"""Install the estimating platform into OpenWorker.

OpenWorker has no plugin bundle format. Its three extension surfaces are
independent, so installing means doing three separate things:

  skills   → copy `openworker/skills/*` into <state-dir>/skills/
             (or <workspace>/.coworker/skills/ with --workspace)
  mcp      → merge `openworker/mcp/mcpServers.json` into <state-dir>/mcp.json
  personas → POST openworker/personas/ to /v1/personas/install, then enable
             (needs a running server; skipped unless --server is given)

Plus one thing that is not an extension surface at all: `pip install` the
bundled estimating_tools wheel into the interpreter the OpenWorker server runs
on, because OpenWorker has no SessionStart hook to do it lazily.

<state-dir> follows coworker/secrets.py::state_dir —
  $COWORKER_STATE_DIR, else %APPDATA%\\coworker on Windows, else ~/.config/coworker.

Examples
--------
    # Local files only (skills + MCP + wheel). Restart the server afterwards.
    python openworker/install.py

    # Everything, including the Estimator persona, against a running server.
    python openworker/install.py --server http://127.0.0.1:8765

    # Per-project instead of global.
    python openworker/install.py --workspace ~/bids/hwy-41
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS_SRC = HERE / "skills"
MCP_SRC = HERE / "mcp" / "mcpServers.json"
PERSONAS_SRC = HERE / "personas"
AUTOMATIONS_SRC = HERE / "automations" / "payloads"


# -- OpenWorker locations ------------------------------------------------------
def state_dir() -> Path:
    """Mirror of coworker.secrets.state_dir — keep in step with upstream."""
    base = os.environ.get("COWORKER_STATE_DIR")
    if base:
        return Path(base).expanduser()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "coworker"
    return Path.home() / ".config" / "coworker"


def skills_dest(workspace: str | None) -> Path:
    if workspace:
        return Path(workspace).expanduser().resolve() / ".coworker" / "skills"
    return state_dir() / "skills"


def mcp_dest(workspace: str | None) -> Path:
    if workspace:
        return Path(workspace).expanduser().resolve() / ".coworker" / "mcp.json"
    return state_dir() / "mcp.json"


# -- steps ---------------------------------------------------------------------
def install_skills(dest: Path, *, dry_run: bool) -> list[str]:
    """Copy each skill folder. Overwrites ours; never touches unrelated skills."""
    names = sorted(p.name for p in SKILLS_SRC.iterdir()
                   if p.is_dir() and (p / "SKILL.md").is_file())
    extras = [p.name for p in SKILLS_SRC.iterdir() if p.is_dir() and p.name.startswith("_")]
    if dry_run:
        return names
    dest.mkdir(parents=True, exist_ok=True)
    for name in names + extras:
        target = dest / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(SKILLS_SRC / name, target)
    return names


def install_mcp(dest: Path, *, dry_run: bool) -> list[str]:
    """Merge our servers into the host's `mcpServers` map, leaving others alone.

    An existing entry with the same key is preserved, not overwritten: a user who
    pointed `bidmanager` at a staging URL or completed OAuth against it should not
    be silently reset by a re-run.
    """
    src = json.loads(MCP_SRC.read_text(encoding="utf-8"))
    ours = {k: v for k, v in src["mcpServers"].items() if not k.startswith("_")}

    existing: dict = {}
    if dest.is_file():
        try:
            existing = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"{dest} is not valid JSON — fix or move it, then re-run")
    servers = dict(existing.get("mcpServers") or {})

    added = [k for k in ours if k not in servers]
    if dry_run:
        return added
    for key in added:
        servers[key] = ours[key]
    existing["mcpServers"] = servers
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    tmp.replace(dest)
    return added


def newest_wheel(candidates):
    """The highest-VERSION wheel among `candidates`, or None if there are none.

    Ordering is numeric, not lexicographic. `sorted(...)[-1]` read correctly
    only by accident: as strings "0.1.100" sorts BELOW "0.1.62", so the first
    three-digit patch release would have silently installed a stale wheel.

    Deliberately dependency-free (no `packaging`): this script is run against
    whatever interpreter the OpenWorker server uses, before anything of ours
    is installed, so it cannot assume third-party imports. A name with no
    dotted version sorts lowest rather than raising — a stray file must never
    outrank a real wheel.
    """
    def version_key(path):
        m = re.search(r"-(\d+(?:\.\d+)*)", path.name)
        return tuple(int(p) for p in m.group(1).split(".")) if m else ()
    return max(candidates, key=version_key, default=None)


def install_wheel(*, dry_run: bool) -> str:
    # estimating_tools hard-depends on bimforge (the split-out CAD/BIM package),
    # and neither is on PyPI, so both bundled wheels must be named in one pip
    # invocation — the local bimforge wheel satisfies the dependency.
    est_wheel = newest_wheel((SKILLS_SRC / "_dist").glob("estimating_tools-*.whl"))
    bimforge_wheel = newest_wheel((SKILLS_SRC / "_dist").glob("bimforge-*.whl"))
    if est_wheel is None:
        return "no bundled estimating_tools wheel found; skills will use their install fallback"
    if bimforge_wheel is None:
        return "no bundled bimforge wheel found; skills will use their install fallback"
    specs = [str(bimforge_wheel), f"{est_wheel}[plugin-core]"]
    if dry_run:
        return f"would pip install {' '.join(specs)}"
    for extra in ([], ["--user"]):
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", *extra, *specs]
        if subprocess.run(cmd, capture_output=True).returncode == 0:
            return f"installed {bimforge_wheel.name} + {est_wheel.name} into {sys.executable}"
    return (f"could not install {bimforge_wheel.name} + {est_wheel.name} into {sys.executable}; "
            "skills will use their install fallback")


# -- server-side steps ---------------------------------------------------------
def read_token(server: str, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    env = os.environ.get("OPENWORKER_TOKEN")
    if env:
        return env
    port = server.rsplit(":", 1)[-1].strip("/")
    guess = state_dir() / f"sidecar-{port}.token"
    if guess.is_file():
        return guess.read_text(encoding="utf-8").strip()
    return None


def api(server: str, token: str | None, path: str, body: dict | None = None) -> dict:
    url = server.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-OpenWorker-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path} -> HTTP {e.code}: {e.read().decode()[:400]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach {url}: {e.reason}")


def install_personas(server: str, token: str | None, *, enable: bool) -> list[dict]:
    """POST the persona directory, then enable each one.

    Personas always land disabled + unsurfaced pending consent
    (PersonaRegistry.install_from_dir). --no-enable leaves them that way so the
    capabilities can be reviewed in Settings ▸ Personas first.
    """
    res = api(server, token, "/v1/personas/install", {"dir": str(PERSONAS_SRC)})
    if not res.get("ok"):
        raise SystemExit(f"persona install failed: {res.get('error')}")
    consent = res.get("consent") or []
    if enable:
        for c in consent:
            api(server, token, f"/v1/personas/{c['id']}",
                {"enabled": True, "surfaced": True})
    return consent


def install_automations(server: str, token: str | None, *, dry_run: bool) -> list[str]:
    """POST each payload not already present (matched by title). The list
    endpoint accepts {"automations": [...]} or a bare list; any other dict
    shape is an error (silently iterating its keys would empty `have` and
    defeat idempotence). Existing automations are never updated by a
    re-install — delete the automation on the server and re-run to pick up
    seed changes."""
    res = api(server, token, "/v1/automations")
    if isinstance(res, dict):
        if "automations" not in res:
            raise SystemExit(f"unexpected /v1/automations response shape: {sorted(res)}")
        existing = res["automations"]
    else:
        existing = res
    if not isinstance(existing, list):
        raise SystemExit("unexpected /v1/automations response shape: expected "
                         f"a list of automations, got {type(existing).__name__}")
    have = {a.get("title") for a in existing if isinstance(a, dict)}
    installed = []
    for path in sorted(AUTOMATIONS_SRC.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "title" not in payload:
            raise SystemExit(f"{path.name}: automation payload missing 'title'")
        if payload["title"] in have:
            continue
        installed.append(payload["title"])
        if not dry_run:
            api(server, token, "/v1/automations", payload)
    return installed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", help="install per-workspace instead of globally")
    ap.add_argument("--server", help="OpenWorker server base URL, e.g. http://127.0.0.1:8765 "
                                     "(required to install personas)")
    ap.add_argument("--token", help="server token; defaults to $OPENWORKER_TOKEN or "
                                    "<state-dir>/sidecar-<port>.token")
    ap.add_argument("--no-enable", action="store_true",
                    help="install personas but leave them disabled pending your review")
    ap.add_argument("--no-wheel", action="store_true", help="skip the pip install step")
    ap.add_argument("--no-automations", action="store_true",
                    help="skip installing the seeded automations")
    ap.add_argument("--dry-run", action="store_true", help="report what would change")
    args = ap.parse_args(argv)

    if not SKILLS_SRC.is_dir():
        raise SystemExit(f"{SKILLS_SRC} missing — run `python openworker/port_skills.py` first")

    tag = "[dry-run] " if args.dry_run else ""
    sd = skills_dest(args.workspace)
    md = mcp_dest(args.workspace)

    names = install_skills(sd, dry_run=args.dry_run)
    print(f"{tag}skills: {len(names)} -> {sd}")

    added = install_mcp(md, dry_run=args.dry_run)
    print(f"{tag}mcp:    {', '.join(added) if added else 'no new servers'} -> {md}")

    if not args.no_wheel:
        print(f"{tag}wheel:  {install_wheel(dry_run=args.dry_run)}")

    if args.server:
        token = read_token(args.server, args.token)
        if args.dry_run:
            print(f"{tag}personas: would install {PERSONAS_SRC} via {args.server}")
        else:
            consent = install_personas(args.server, token, enable=not args.no_enable)
            for c in consent:
                state = "disabled (pending your review)" if args.no_enable else "enabled"
                print(f"persona: {c['id']:14s} tools={c['tools']} risk={c['risk']} -> {state}")
        if not args.no_automations:
            titles = install_automations(args.server, token, dry_run=args.dry_run)
            verb = "would install" if args.dry_run else "installed"
            print(f"automations: {verb} {', '.join(titles) if titles else 'none (all present)'} "
                  "(existing ones are never updated — delete on the server and "
                  "re-run to pick up seed changes)")
    else:
        print("personas: skipped (pass --server to install them)")

    # Plain ASCII: this prints to a Windows console, whose default cp1252
    # codec raises UnicodeEncodeError on characters like the arrow glyph.
    print(
        "\nNext:\n"
        "  1. Restart the OpenWorker server so it re-reads skills and mcp.json.\n"
        "  2. Settings > Connectors > MCP: click Connect on `bidmanager` (and\n"
        "     `conformed`) to run the OAuth sign-in.\n"
        "  3. Start a session with the Estimator persona and ask for a skill by name,\n"
        "     e.g. \"level the quotes on the Hwy 41 culvert package\".\n"
        "  4. Recurring work: the seeded automations install with --server (skip\n"
        "     with --no-automations); see openworker/automations/recipes.md for the\n"
        "     chat-created variants that run as the Estimator in your bid folder."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
