"""Stdio MCP server exposing the artifact editor as an MCP App.

Extension: io.modelcontextprotocol/ui (MCP Apps, spec 2026-01-26). The server is
stateless: parse a canonical render into the grid payload, hand it to the app as
structuredContent (app-only; the model sees one summary line). All ui/* protocol
traffic runs between the app iframe and the host — never through this process.
"""
from __future__ import annotations

import argparse
from importlib.metadata import version as _dist_version
from importlib.resources import files

import anyio
import anyio.to_thread
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from estimating_tools.artifact_app import browser
from estimating_tools.artifacts_html import build_payload, to_editable_html

TOOL_NAME = "open_artifact_editor"
COLLECT_TOOL_NAME = "collect_artifact_edits"
APP_RESOURCE_URI = "ui://estimating/editor.html"
APP_MIME = "text/html;profile=mcp-app"
_UI_META = {"ui": {"resourceUri": APP_RESOURCE_URI}}
_PERMISSIONS_META = {"ui": {"permissions": {"clipboardWrite": {}}}}

DEFAULT_WAIT_SECONDS = 120
MAX_WAIT_SECONDS = 570        # keep below plausible host tool-timeouts; calibrated in Task 6
_SAVED_PREFIX = "Saved ✓ — edited canonical block follows. Parse and push it now (Save = the user's consent; no confirmation needed).\n\n"

server = Server("estimating-artifact-editor",
                version=_dist_version("estimating_tools"))


def _client_supports_apps(ctx) -> bool:
    """True when the client declared the MCP Apps extension for our mime type.

    Hosts advertise MCP Apps support via ``capabilities.extensions`` in the
    initialize request. mcp 2.x carries a native ``extensions`` field on
    ``ClientCapabilities`` (SEP-2133); the getattr also tolerates a peer that
    omits it. ``ctx`` is the per-request ``ServerRequestContext`` the low-level
    runner hands each handler — its ``session.client_params`` holds the
    initialize params. A peer that somehow reached a handler without them fails
    closed.

    The extension declaration carries a REQUIRED ``mimeTypes`` list per the
    MCP Apps spec; a host could declare the extension key without supporting
    our profile, so check membership rather than mere presence. A missing or
    malformed ``mimeTypes`` list fails closed to the safe 0.1.5 fallback.
    """
    client_params = getattr(ctx.session, "client_params", None)
    caps = getattr(client_params, "capabilities", None)
    extensions = getattr(caps, "extensions", None) or {}
    declared = extensions.get("io.modelcontextprotocol/ui")
    if not isinstance(declared, dict):
        return False
    return APP_MIME in (declared.get("mimeTypes") or [])


def _app_html() -> str:
    return (
        files("estimating_tools.artifact_app").joinpath("app.html").read_text("utf-8")
    )


async def list_tools(ctx, params=None) -> types.ListToolsResult:
    # Gate on the MCP Apps client capability: hosts that can render MCP Apps get
    # the single inline editor tool (below). Hosts that can't (e.g. the Claude
    # Code terminal) instead get the browser-mode pair — open_artifact_editor +
    # collect_artifact_edits — so the editor opens in a real browser rather than
    # a "successful" inline call that renders nowhere.
    if not _client_supports_apps(ctx):
        return types.ListToolsResult(tools=[
            types.Tool(
                name=TOOL_NAME,
                description=(
                    "Open an estimating artifact (a canonical render block) as an "
                    "editable grid in the user's web browser (served from a local "
                    "loopback session). The call waits for the user's Save and "
                    "returns the edited canonical block directly — parse and push "
                    "it when it returns. If the wait expires the editor stays "
                    "open; call collect_artifact_edits after the user says they "
                    "saved. Pass editable=false for read-only plan renders."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "markdown": {
                            "type": "string",
                            "description": "The render output, verbatim.",
                        },
                        "title": {"type": "string"},
                        "editable": {"type": "boolean", "default": True},
                        "wait_seconds": {
                            "type": "number",
                            "default": DEFAULT_WAIT_SECONDS,
                            "description": (
                                "How long to wait for the user's Save before "
                                f"returning 'still open' (max {MAX_WAIT_SECONDS})."
                            ),
                        },
                    },
                    "required": ["markdown", "title"],
                },
            ),
            types.Tool(
                name=COLLECT_TOOL_NAME,
                description=(
                    "Retrieve the saved edits from the currently open browser "
                    "artifact editor (after open_artifact_editor returned 'still "
                    "open'). Returns the edited canonical block if the user "
                    "has saved; otherwise says no save has arrived yet."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
        ])
    return types.ListToolsResult(tools=[
        types.Tool(
            name=TOOL_NAME,
            description=(
                "Open an estimating artifact (a canonical render block) as an "
                "editable grid inline in the conversation. The user's Save "
                "arrives as a chat message containing the canonical markdown "
                "block. Pass editable=false for read-only plan renders."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "markdown": {
                        "type": "string",
                        "description": "The render output, verbatim.",
                    },
                    "title": {"type": "string"},
                    "editable": {"type": "boolean", "default": True},
                },
                "required": ["markdown", "title"],
            },
            _meta=_UI_META,
        )
    ])


async def call_tool(ctx, params) -> types.CallToolResult:
    name = params.name
    arguments = params.arguments or {}
    if name == COLLECT_TOOL_NAME:
        return _collect_edits()
    if name != TOOL_NAME:
        raise ValueError(f"unknown tool: {name}")
    if _client_supports_apps(ctx):
        return _open_as_app(arguments)
    return await _open_in_browser(arguments)


def _open_as_app(arguments: dict) -> types.CallToolResult:
    markdown = arguments["markdown"]
    title = arguments["title"]
    editable = bool(arguments.get("editable", True))
    try:
        payload = build_payload(markdown, editable=editable)
    except ValueError as exc:
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=(
                        f"artifact grammar error: {exc} — fall back to the "
                        "to_editable_html artifact/file path"
                    ),
                )
            ],
            isError=True,
        )
    n = len(payload["tables"])
    note = (
        f"Editor opened: {title} — {n} table(s). Awaiting the user's edits; "
        "their Save will arrive as a chat message containing the canonical block."
        if editable
        else f"Read-only render opened: {title} — {n} table(s)."
    )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=note)],
        structuredContent={"title": title, "editable": editable, **payload},
    )


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], isError=True
    )


def _text(text: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


async def _open_in_browser(arguments: dict) -> types.CallToolResult:
    markdown = arguments["markdown"]
    title = arguments["title"]
    editable = bool(arguments.get("editable", True))
    try:
        requested = float(arguments.get("wait_seconds", DEFAULT_WAIT_SECONDS))
    except (TypeError, ValueError):
        requested = DEFAULT_WAIT_SECONDS
    wait = min(max(requested, 0.0), MAX_WAIT_SECONDS)
    try:
        page = to_editable_html(
            markdown, title=title, editable=editable, browser_save=True
        )
    except ValueError as exc:
        return _error(
            f"artifact grammar error: {exc} — fix the render block and retry"
        )
    session, url = browser.open_session(page)
    opened = await anyio.to_thread.run_sync(browser.open_browser, url)
    hint = "" if opened else " (the browser did not open — give the user the URL to open manually)"
    if not editable:
        return _text(f"Read-only render opened in the user's browser: {url}{hint}")
    # Abandoned wait threads self-expire within the wait timeout and are
    # bounded by anyio's default capacity limiter.
    saved = await anyio.to_thread.run_sync(
        browser.await_save, session, wait, abandon_on_cancel=True
    )
    if saved is None:
        return _text(
            f"Editor still open in the user's browser at {url}{hint} — no save "
            f"after {wait:.0f}s. When the user says they've saved, call "
            f"{COLLECT_TOOL_NAME}."
        )
    return _text(_SAVED_PREFIX + saved)


def _collect_edits() -> types.CallToolResult:
    session = browser.current_session()
    if session is None:
        return _error(
            "no active editor session — call open_artifact_editor first"
        )
    if session.saved_markdown is None:
        return _text(
            f"No save yet — the editor is still open at {session.url}. Ask the "
            "user to click Save & send to Claude, then call this again."
        )
    return _text(_SAVED_PREFIX + session.saved_markdown)


async def list_resources(ctx, params=None) -> types.ListResourcesResult:
    if not _client_supports_apps(ctx):  # same gate as list_tools
        return types.ListResourcesResult(resources=[])
    return types.ListResourcesResult(resources=[
        types.Resource(
            uri=APP_RESOURCE_URI,
            name="Estimating artifact editor",
            mimeType=APP_MIME,
            _meta=_PERMISSIONS_META,
        )
    ])


async def read_resource(ctx, params) -> types.ReadResourceResult:
    uri = params.uri
    if str(uri) != APP_RESOURCE_URI:
        raise ValueError(f"unknown resource: {uri}")
    return types.ReadResourceResult(contents=[
        types.TextResourceContents(
            uri=uri, text=_app_html(), mimeType=APP_MIME, _meta=_PERMISSIONS_META
        )
    ])


# mcp 2.x low-level API: request handlers are registered by wire method name
# (see mcp.server.lowlevel.Server.add_request_handler) rather than the 1.x
# @server.list_tools()/@server.call_tool() decorators, which were removed.
# Each handler takes (ServerRequestContext, validated params) and returns the
# full result type.
server.add_request_handler("tools/list", types.PaginatedRequestParams, list_tools)
server.add_request_handler("tools/call", types.CallToolRequestParams, call_tool)
server.add_request_handler("resources/list", types.PaginatedRequestParams, list_resources)
server.add_request_handler("resources/read", types.ReadResourceRequestParams, read_resource)


async def _run() -> None:
    async with stdio_server() as (read, write):
        await server.run(
            read,
            write,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
            ),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="est-artifact-app",
        description="Stdio MCP server: estimating artifact editor (MCP App).",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args = parser.parse_args(argv)
    if args.version:
        print(_dist_version("estimating_tools"))
        return 0
    anyio.run(_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
