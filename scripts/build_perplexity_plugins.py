#!/usr/bin/env python3
"""Build pruned, import-ready Perplexity plugins from plugins/*.

Reads perplexity/bundles.json and writes one folder + zip per bundle into
the output dir. Only user-facing payload ships: SKILL.md trees, agents, the
runtime scripts + bundled wheels, and an HTTPS-only .mcp.json. Dev material
(docs/, plans, CHANGELOG, tests) never enters because nothing outside the
selected paths is copied.

Fails (exit 1) if any skill is unassigned or double-assigned, or a bundle
breaks Perplexity's import limits (skill count, file count, total size,
per-text-file size, MCP server count).

    python scripts/build_perplexity_plugins.py --out build/perplexity [--version 0.1.99]
"""
from __future__ import annotations

import argparse, json, shutil, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
CONFIG = ROOT / "perplexity" / "bundles.json"
BINARY_SUFFIXES = {".whl", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".xlsx"}  # .dxf is text
SKIP_NAMES = {"__pycache__", ".DS_Store"}
# Runtime files a bundle carries; the stdio artifact-editor launcher is dropped
RUNTIME_SCRIPTS = {"ensure_tools.py", "plugin_runtime.py"}


def all_skills() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in sorted(PLUGINS.glob("*/skills/*")):
        if (d / "SKILL.md").is_file():
            if d.name in found:
                raise SystemExit(f"skill name collision: {d.name}")
            found[d.name] = d
    return found


def check_assignment(cfg: dict, skills: dict[str, Path]) -> list[str]:
    errs, seen = [], {}
    shared = set(cfg.get("shared", []))
    for name in cfg["excluded"]:
        seen.setdefault(name, []).append("excluded")
    for b, spec in cfg["bundles"].items():
        for s in spec["skills"]:
            seen.setdefault(s, []).append(b)
    for s, where in seen.items():
        if s not in skills:
            errs.append(f"'{s}' listed in {where} but no such skill exists")
        if len(where) > 1 and not (s in shared and "excluded" not in where):
            errs.append(f"'{s}' assigned more than once: {where}")
    for s in skills:
        if s not in seen:
            errs.append(f"new skill '{s}' is not assigned to a bundle or excluded")
    for b, spec in cfg["bundles"].items():
        for a in spec.get("agents", []):
            if not (PLUGINS / a).is_file():
                errs.append(f"{b}: agent '{a}' not found under plugins/")
        for key in ("runtime_from", "mcp_from"):
            if key in spec and not (PLUGINS / spec[key]).is_dir():
                errs.append(f"{b}: {key} '{spec[key]}' is not a plugin")
    return errs


def warn_excluded_refs(cfg: dict, skills: dict[str, Path]) -> None:
    """Shipped skills that name an excluded skill would point users at nothing."""
    excluded = set(cfg["excluded"])
    for spec in cfg["bundles"].values():
        for s in spec["skills"]:
            text = (skills[s] / "SKILL.md").read_text(encoding="utf-8")
            for x in sorted(excluded):
                if x in text:
                    print(f"  warning: shipped skill '{s}' mentions excluded skill '{x}'")


def copytree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=lambda _d, names: [n for n in names if n in SKIP_NAMES or n.endswith(".pyc")])


def https_mcp(plugin: str) -> dict:
    p = PLUGINS / plugin / ".mcp.json"
    if not p.exists():
        return {}
    servers = json.loads(p.read_text(encoding="utf-8"))
    servers = servers.get("mcpServers", servers)
    return {k: v for k, v in servers.items()
            if v.get("type") in ("http", "sse") and str(v.get("url", "")).startswith("https://")}


def build_bundle(name: str, spec: dict, skills: dict[str, Path], out: Path, version: str) -> Path:
    dst = out / name
    shutil.rmtree(dst, ignore_errors=True)
    (dst / ".claude-plugin").mkdir(parents=True)
    rt = PLUGINS / spec["runtime_from"]
    src_manifest = json.loads((rt / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    manifest = {**src_manifest, "name": name, "displayName": spec["displayName"],
                "description": spec["description"], "version": version or src_manifest["version"]}
    (dst / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for s in spec["skills"]:
        copytree(skills[s], dst / "skills" / s)
    for a in spec.get("agents", []):
        (dst / "agents").mkdir(exist_ok=True)
        shutil.copy2(PLUGINS / a, dst / "agents" / Path(a).name)
    if (rt / "dist").is_dir():
        copytree(rt / "dist", dst / "dist")
    (dst / "scripts").mkdir()
    for f in RUNTIME_SCRIPTS:
        if (rt / "scripts" / f).exists():
            shutil.copy2(rt / "scripts" / f, dst / "scripts" / f)
    if (rt / "hooks").is_dir():  # harmless where unsupported; keeps Claude Code parity
        copytree(rt / "hooks", dst / "hooks")

    servers = https_mcp(spec.get("mcp_from", spec["runtime_from"]))
    if servers:
        (dst / ".mcp.json").write_text(json.dumps(servers, indent=2) + "\n", encoding="utf-8")
    return dst


def check_limits(dst: Path, limits: dict, n_skills: int) -> list[str]:
    errs = []
    files = [p for p in dst.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    if n_skills > limits["max_skills"]:
        errs.append(f"{n_skills} skills > {limits['max_skills']}")
    if len(files) > limits["max_files"]:
        errs.append(f"{len(files)} files > {limits['max_files']}")
    if total > limits["max_total_bytes"]:
        errs.append(f"{total} bytes > {limits['max_total_bytes']}")
    for p in files:
        if p.suffix.lower() not in BINARY_SUFFIXES and p.stat().st_size > limits["max_text_file_bytes"]:
            errs.append(f"text file too large: {p.relative_to(dst)} ({p.stat().st_size} bytes)")
    mcp = dst / ".mcp.json"
    if mcp.exists() and len(json.loads(mcp.read_text())) > limits["max_mcp_servers"]:
        errs.append("too many MCP servers")
    print(f"  {dst.name}: {n_skills} skills, {len(files)} files, {total/1e6:.2f} MB")
    return errs


def zip_dir(src: Path) -> Path:
    zp = src.with_suffix(".zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())
    return zp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/perplexity")
    ap.add_argument("--version", default="")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    skills = all_skills()
    errs = check_assignment(cfg, skills)
    if errs:
        print("\n".join("ERROR: " + e for e in errs)); return 1
    warn_excluded_refs(cfg, skills)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    for name, spec in cfg["bundles"].items():
        dst = build_bundle(name, spec, skills, out, args.version)
        errs += [f"{name}: {e}" for e in check_limits(dst, cfg["limits"], len(spec["skills"]))]
        zip_dir(dst)
    if errs:
        print("\n".join("ERROR: " + e for e in errs)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
