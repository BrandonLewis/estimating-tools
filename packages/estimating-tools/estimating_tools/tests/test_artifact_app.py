"""Tests for the artifact-editor MCP App server (in-process client sessions).

Two client flavors over an in-memory transport: `connect` (declares NO
extension capabilities — i.e. a host that can't render MCP Apps) and
`connect_apps` (same transport, but the client declares the
`io.modelcontextprotocol/ui` extension — i.e. an Apps-capable host).
"""
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
from mcp.client.session import ClientSession  # noqa: E402
from mcp.shared.memory import create_client_server_memory_streams  # noqa: E402

from estimating_tools.artifact_app import server as srv  # noqa: E402
from estimating_tools.tests.test_artifacts_html import ASSEMBLY_MD, PUSH_MD  # noqa: E402

UI_EXTENSION = "io.modelcontextprotocol/ui"


@asynccontextmanager
async def _connect(server, extensions):
    """In-memory client/server session, replacing mcp 1.x's removed
    ``create_connected_server_and_client_session``.

    ``extensions`` (None for a stock host) is passed straight to the mcp 2.x
    ``ClientSession`` constructor, which advertises it on ``ClientCapabilities``
    natively (SEP-2133) — so the MCP Apps declaration round-trips without the
    1.x-era ``send_request`` interception hack.
    """
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: server.run(
                    server_read,
                    server_write,
                    server.create_initialization_options(),
                    raise_exceptions=False,
                )
            )
            try:
                async with ClientSession(
                    client_read, client_write, extensions=extensions
                ) as session:
                    await session.initialize()
                    yield session
            finally:
                tg.cancel_scope.cancel()


def connect(server):
    """A host that declares NO MCP Apps extension (the terminal case)."""
    return _connect(server, None)


def connect_apps(server, extensions=None):
    """A host declaring the MCP Apps client capability (default: the well-formed
    ``io.modelcontextprotocol/ui`` declaration for our mime type)."""
    ext = extensions if extensions is not None else {UI_EXTENSION: {"mimeTypes": [srv.APP_MIME]}}
    return _connect(server, ext)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_tool_declares_the_app_resource():
    async with connect_apps(srv.server) as client:
        tools = (await client.list_tools()).tools
        [tool] = [t for t in tools if t.name == srv.TOOL_NAME]
        dumped = tool.model_dump(by_alias=True, exclude_none=True)
        assert dumped["_meta"]["ui"]["resourceUri"] == srv.APP_RESOURCE_URI
        assert set(tool.input_schema["required"]) == {"markdown", "title"}


@pytest.mark.anyio
async def test_call_tool_returns_note_and_structured_payload():
    async with connect_apps(srv.server) as client:
        res = await client.call_tool(
            srv.TOOL_NAME,
            {"markdown": ASSEMBLY_MD, "title": "Assembly", "editable": True},
        )
        assert not res.is_error
        assert "Editor opened" in res.content[0].text
        sc = res.structured_content
        assert sc["title"] == "Assembly"
        assert sc["editable"] is True
        assert sc["lines"] == ASSEMBLY_MD.split("\n")
        assert sc["tables"] and sc["body"]
        assert 'contenteditable="true"' in sc["body"]


@pytest.mark.anyio
async def test_read_only_payload_has_no_edit_affordances():
    async with connect_apps(srv.server) as client:
        res = await client.call_tool(
            srv.TOOL_NAME, {"markdown": PUSH_MD, "title": "Plan", "editable": False}
        )
        assert not res.is_error
        assert res.structured_content["editable"] is False
        assert 'contenteditable="true"' not in res.structured_content["body"]


@pytest.mark.anyio
async def test_malformed_markdown_is_a_loud_tool_error():
    async with connect_apps(srv.server) as client:
        res = await client.call_tool(
            srv.TOOL_NAME, {"markdown": "| a | b |\n| oops |", "title": "x"}
        )
        assert res.is_error
        assert "line" in res.content[0].text


@pytest.mark.anyio
async def test_resource_serves_the_app_html():
    async with connect_apps(srv.server) as client:
        listed = (await client.list_resources()).resources
        [r] = [x for x in listed if str(x.uri) == srv.APP_RESOURCE_URI]
        assert r.mime_type == srv.APP_MIME
        read = await client.read_resource(srv.APP_RESOURCE_URI)
        text = read.contents[0].text
        assert "GRID-CORE begin" in text
        assert "ui/initialize" in text


@pytest.mark.anyio
async def test_apps_capable_client_sees_tool_and_resource():
    async with connect_apps(srv.server) as client:
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == [srv.TOOL_NAME]
        resources = (await client.list_resources()).resources
        assert [str(r.uri) for r in resources] == [srv.APP_RESOURCE_URI]


@pytest.mark.anyio
async def test_capability_less_client_sees_browser_tools_no_resource():
    """Non-Apps hosts (the terminal) get browser mode: the editor tool plus
    collect_artifact_edits, and still no ui:// resource (nothing renders it)."""
    async with connect(srv.server) as client:
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == [srv.TOOL_NAME, srv.COLLECT_TOOL_NAME]
        [editor] = [t for t in tools if t.name == srv.TOOL_NAME]
        assert "browser" in editor.description
        assert "wait_seconds" in editor.input_schema["properties"]
        assert (await client.list_resources()).resources == []


@pytest.mark.anyio
async def test_wrong_mime_type_client_gets_browser_mode():
    """A host may declare the extension key without supporting our profile —
    the gate must check the declared mimeTypes list, not just key presence."""
    async with connect_apps(
        srv.server, extensions={UI_EXTENSION: {"mimeTypes": ["text/html"]}}
    ) as client:
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == [srv.TOOL_NAME, srv.COLLECT_TOOL_NAME]
        assert (await client.list_resources()).resources == []


@pytest.mark.anyio
async def test_browser_mode_open_then_save_then_collect(monkeypatch):
    """Non-Apps call flow: open (no real browser), no save in the window →
    'still open'; then a save lands and collect returns the block."""
    import urllib.request

    from estimating_tools.artifact_app import browser

    opened_urls: list[str] = []
    monkeypatch.setattr(browser, "open_browser", lambda url: opened_urls.append(url) or True)
    try:
        async with connect(srv.server) as client:
            res = await client.call_tool(
                srv.TOOL_NAME,
                {"markdown": PUSH_MD, "title": "Plan", "wait_seconds": 0},
            )
            assert not res.is_error
            assert "still open" in res.content[0].text.lower()
            [url] = opened_urls
            assert url in res.content[0].text

            no_save = await client.call_tool(srv.COLLECT_TOOL_NAME, {})
            assert "no save yet" in no_save.content[0].text.lower()

            req = urllib.request.Request(
                url + "save", data="| edited |".encode("utf-8"), method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
            collected = await client.call_tool(srv.COLLECT_TOOL_NAME, {})
            assert not collected.is_error
            assert collected.content[0].text.endswith("| edited |")
    finally:
        browser.shutdown()


@pytest.mark.anyio
async def test_browser_mode_save_within_wait_returns_block(monkeypatch):
    """The long-poll happy path: a save that lands during the wait comes back
    as the tool result."""
    import threading
    import time
    import urllib.request

    from estimating_tools.artifact_app import browser

    def save_soon(url: str) -> bool:
        def _post():
            time.sleep(0.2)
            req = urllib.request.Request(
                url + "save", data="| edited |".encode("utf-8"), method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        threading.Thread(target=_post, daemon=True).start()
        return True

    monkeypatch.setattr(browser, "open_browser", save_soon)
    try:
        async with connect(srv.server) as client:
            res = await client.call_tool(
                srv.TOOL_NAME,
                {"markdown": PUSH_MD, "title": "Plan", "wait_seconds": 10},
            )
            assert not res.is_error
            assert res.content[0].text.endswith("| edited |")
            assert "Saved ✓" in res.content[0].text
    finally:
        browser.shutdown()


@pytest.mark.anyio
async def test_browser_mode_collect_without_session():
    from estimating_tools.artifact_app import browser

    browser.shutdown()
    async with connect(srv.server) as client:
        res = await client.call_tool(srv.COLLECT_TOOL_NAME, {})
        assert res.is_error
        assert "no active editor session" in res.content[0].text.lower()


@pytest.mark.anyio
async def test_browser_mode_grammar_error_is_loud(monkeypatch):
    from estimating_tools.artifact_app import browser

    monkeypatch.setattr(browser, "open_browser", lambda url: True)
    async with connect(srv.server) as client:
        res = await client.call_tool(
            srv.TOOL_NAME, {"markdown": "| a | b |\n| oops |", "title": "x"}
        )
        assert res.is_error
        assert "line" in res.content[0].text


@pytest.mark.anyio
async def test_browser_mode_read_only_render_no_wait(monkeypatch):
    from estimating_tools.artifact_app import browser

    monkeypatch.setattr(browser, "open_browser", lambda url: True)
    try:
        async with connect(srv.server) as client:
            res = await client.call_tool(
                srv.TOOL_NAME,
                {"markdown": PUSH_MD, "title": "Plan", "editable": False},
            )
            assert not res.is_error
            assert "Read-only render" in res.content[0].text
    finally:
        browser.shutdown()


def test_version_flag_exits_without_stdio(capsys):
    from estimating_tools.artifact_app.server import main

    assert main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out and all(part.isdigit() for part in out.split("."))


def _grid_core(text: str) -> str:
    start = text.index("/* GRID-CORE begin")
    end = text.index("/* GRID-CORE end */", start)
    return text[start:end]


def test_grid_core_is_byte_identical_across_surfaces():
    from importlib.resources import files

    from estimating_tools.artifacts_html import _PAGE

    app = files("estimating_tools.artifact_app").joinpath("app.html").read_text("utf-8")
    core = _grid_core(app)
    assert core == _grid_core(_PAGE)
    assert "exportMarkdown" in core
    assert "focusin" in core  # select-on-focus: typing replaces, tabbing keeps
    assert app.count("/* GRID-CORE begin") == 1 and _PAGE.count("/* GRID-CORE begin") == 1


def test_app_html_is_self_contained_and_speaks_the_protocol():
    from importlib.resources import files

    app = files("estimating_tools.artifact_app").joinpath("app.html").read_text("utf-8")
    for needle in (
        "ui/initialize",
        "ui/notifications/initialized",
        "ui/notifications/tool-result",
        "ui/message",
        "ui/resource-teardown",
        "Save & send to chat",
    ):
        assert needle in app, needle
    assert "http://" not in app and "https://" not in app
    assert "src=" not in app and "<link" not in app
