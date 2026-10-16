"""Generate per-client MCP config from servers.manifest.yaml.

Usage:
  python manifest/generate.py --client claude   # writes plugins/estimating-core/.mcp.json
  python manifest/generate.py --client cowork    # writes it/cowork-connector.md
  python manifest/generate.py --client gemini|cursor|codex  # writes it/<client> snippet
  python manifest/generate.py --check            # regen to memory, diff vs committed (CI guard)

Servers may declare a `clients` list to limit which renderers include them
(absent = all clients). Plugin-local stdio servers (transport: stdio) are
claude-plugin-only — remote clients cannot launch a process that ships inside
the plugin.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest" / "servers.manifest.yaml"
CLAUDE_OUT = ROOT / "plugins" / "estimating-core" / ".mcp.json"
COWORK_OUT = ROOT / "it" / "cowork-connector.md"
GEMINI_OUT = ROOT / "it" / "gemini-settings.snippet.json"
CURSOR_OUT = ROOT / "it" / "cursor-mcp.json"
CODEX_OUT = ROOT / "it" / "codex-config.toml.snippet"


def _servers():
    return yaml.safe_load(MANIFEST.read_text())["servers"]


def _for(client):
    # Absent `clients` field = all clients (today's behavior for the http servers).
    return [s for s in _servers()
            if client in s.get("clients", ["claude", "cowork", "gemini", "cursor", "codex"])]


def _url(s) -> str:
    # Resolve the server URL at generation time: the `url_env` override wins, else
    # the committed default. None of the target config formats expands a shell
    # "${VAR:-default}" (a plugin .mcp.json takes it literally; the rest are plain
    # JSON/TOML), so the override must be baked in here rather than emitted as an
    # expression. CI runs with no override set, so committed outputs stay on the
    # defaults and --check remains stable.
    return os.environ.get(s.get("url_env", ""), s["url_default"])


def render_claude() -> str:
    servers = {}
    for s in _for("claude"):
        if s["transport"] == "stdio":
            # Plugin-local stdio server: launched from inside the plugin, no url/headers.
            # An empty args list is omitted — self-contained launchers take no arguments.
            servers[s["id"]] = {"type": "stdio", "command": s["command"]}
            if s["args"]:
                servers[s["id"]]["args"] = s["args"]
            continue
        # Concrete URL: a plugin's .mcp.json supports ${ENV_VAR} but NOT the bash
        # "${VAR:-default}" default syntax — that form is taken literally, breaking the URL.
        entry = {"type": s["transport"], "url": _url(s)}
        # OAuth-primary: header-less so Claude Code runs the server's OAuth flow.
        # Only non-oauth servers carry a static ApiKey header (none today).
        auth = s.get("auth", {})
        if not auth.get("oauth") and auth.get("apikey_env"):
            # Header env expansion: use plain ${ENV_VAR}. The bash default form
            # "${VAR:-default}" is taken literally in a plugin .mcp.json, so it must
            # not appear here or the Authorization value ends up non-functional.
            entry["headers"] = {"Authorization": "ApiKey ${%s}" % auth["apikey_env"]}
        servers[s["id"]] = entry
    # A standalone plugin `.mcp.json` uses the FLAT shape (server names at the top
    # level, no "mcpServers" wrapper) — every official plugin ships it this way; the
    # wrapper is only the envelope form inside `plugin.json` (claude-code#63694).
    # Gemini/Cursor below legitimately keep their own "mcpServers" wrapper.
    return json.dumps(servers, indent=2) + "\n"


def render_cowork() -> str:
    lines = ["# Cowork Connector Setup", "",
             "Cowork connects from Anthropic's cloud and supports **remote + OAuth only**",
             "(no custom headers). Register each server below as an org-level Custom Connector",
             "(Team/Enterprise Owners), then members click Connect and sign in via SSO.", ""]
    for s in _for("cowork"):
        lines += [f"## {s['id']}", "",
                  f"- **URL:** {_url(s)}",
                  f"- **Auth:** OAuth 2.1 (per-user SSO)",
                  f"- **Description:** {s['description']}", ""]
    return "\n".join(lines)


def render_gemini() -> str:
    servers = {
        s["id"]: {"httpUrl": _url(s),
                  "oauth": {"authProviderType": "dynamic_discovery"}}
        for s in _for("gemini")
    }
    return json.dumps({"mcpServers": servers}, indent=2) + "\n"


def render_cursor() -> str:
    servers = {s["id"]: {"url": _url(s)} for s in _for("cursor")}
    return json.dumps({"mcpServers": servers}, indent=2) + "\n"


def _bearer_env(s) -> str:
    # Sanitize to a valid env-var name: non-[A-Za-z0-9_] -> _ (today's ids are clean).
    return re.sub(r"[^A-Za-z0-9_]", "_", s["id"].upper()) + "_BEARER"


def render_codex() -> str:
    blocks = [
        f'[mcp_servers.{s["id"]}]\n'
        f'url = "{_url(s)}"\n'
        f'bearer_token_env_var = "{_bearer_env(s)}"\n'
        for s in _for("codex")
    ]
    return "\n".join(blocks)


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic bytes on every platform (LF, UTF-8) — the outputs are committed
    # and guarded by --check, so Windows must not emit CRLF.
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="generate")
    ap.add_argument("--client", choices=["claude", "cowork", "gemini", "cursor", "codex"])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    targets = {
        CLAUDE_OUT: render_claude(),
        COWORK_OUT: render_cowork(),
        GEMINI_OUT: render_gemini(),
        CURSOR_OUT: render_cursor(),
        CODEX_OUT: render_codex(),
    }
    if args.check:
        drift = [p.name for p, text in targets.items() if not p.exists() or p.read_text() != text]
        if drift:
            print("drift in: " + ", ".join(drift), file=sys.stderr)
            return 1
        return 0
    paths = {"claude": CLAUDE_OUT, "cowork": COWORK_OUT, "gemini": GEMINI_OUT,
             "cursor": CURSOR_OUT, "codex": CODEX_OUT}
    if args.client:
        write(paths[args.client], targets[paths[args.client]])
    else:
        ap.error("provide --client or --check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
