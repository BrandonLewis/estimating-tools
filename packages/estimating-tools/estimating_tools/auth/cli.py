"""m2m-token: mint a short-lived OAuth client_credentials bearer token for a manifest
MCP server. Credentials come from the environment only (never CLI args); nothing is
written to disk. Usage: TOKEN=$(m2m-token --server bidmanager)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from estimating_tools.auth.m2m import build_token_request, parse_token_response

DEFAULT_MANIFEST = "manifest/servers.manifest.yaml"


def _load_server(manifest_path: str, server_id: str) -> dict:
    data = yaml.safe_load(Path(manifest_path).read_text())
    if not isinstance(data, dict) or not isinstance(data.get("servers"), list):
        raise ValueError("manifest has no 'servers' list")
    servers = data["servers"]
    for s in servers:
        if s["id"] == server_id:
            return s
    raise KeyError(server_id)


def _fetch_token(req: dict) -> str:
    """POST the token request. The only network touch; default TLS verification
    (do NOT pass an unverified SSL context). Returns the raw response body."""
    request = urllib.request.Request(
        req["url"], data=req["data"], headers=req["headers"], method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 (https enforced upstream)
        return resp.read().decode()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="m2m-token",
        description="Mint an OAuth client_credentials bearer token for a manifest MCP server.",
    )
    ap.add_argument("--server", required=True, help="server id from the manifest")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST, help="path to servers.manifest.yaml")
    ap.add_argument("--header", action="store_true",
                    help="emit the full 'Authorization: Bearer <token>' line")
    args = ap.parse_args(argv)

    try:
        server = _load_server(args.manifest, args.server)
    except FileNotFoundError:
        print(f"m2m-token: manifest not found: {args.manifest}", file=sys.stderr); return 1
    except yaml.YAMLError:
        print(f"m2m-token: invalid manifest YAML: {args.manifest}", file=sys.stderr); return 1
    except ValueError as e:
        print(f"m2m-token: {e}", file=sys.stderr); return 1
    except KeyError:
        print(f"m2m-token: unknown server: {args.server}", file=sys.stderr); return 1

    m2m = server.get("auth", {}).get("m2m")
    if not m2m:
        print(f"m2m-token: server {args.server!r} has no m2m config", file=sys.stderr)
        return 1

    client_id = os.environ.get(m2m["client_id_env"], "")
    client_secret = os.environ.get(m2m["client_secret_env"], "")
    if not client_id or not client_secret:
        print(
            f"m2m-token: set {m2m['client_id_env']} and {m2m['client_secret_env']} "
            "in the environment (secret store)",
            file=sys.stderr,
        )
        return 1

    # token_url_env repoints the OAuth token endpoint without editing the manifest
    # (mirrors the credential env reads above and generate.py's url_env). Falls back
    # to the committed default when unset.
    token_url = os.environ.get(m2m.get("token_url_env", ""), m2m["token_url"])
    try:
        req = build_token_request(
            token_url, client_id, client_secret, m2m.get("scope", "mcp")
        )
        token = parse_token_response(_fetch_token(req))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = json.loads(e.read().decode(errors="replace"))
            code = body.get("error", "")
            desc = body.get("error_description", "")
            detail = ": ".join(filter(None, [code, desc]))
        except Exception:
            detail = ""
        print(
            f"m2m-token: token request failed (HTTP {e.code})"
            + (f": {detail}" if detail else ""),
            file=sys.stderr,
        )
        return 1
    except (ValueError, urllib.error.URLError) as e:
        print(f"m2m-token: {e}", file=sys.stderr)
        return 1

    print(f"Authorization: Bearer {token}" if args.header else token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
