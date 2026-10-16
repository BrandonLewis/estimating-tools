"""Loopback browser surface for the artifact editor (non-Apps hosts).

One process-lifetime HTTP server on 127.0.0.1:<random port>. Each
``open_session`` mints a token-guarded session and supersedes the previous one
(stale saves answer 409 so the page's copy fallback engages). Loopback bind +
random URL token + Host-header check keep other local processes, other tabs,
and DNS-rebinding pages out. Pure stdlib; the async MCP server awaits the
threading.Event via ``anyio.to_thread``.
"""
from __future__ import annotations

import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_MAX_SAVE_BYTES = 4 * 1024 * 1024


class EditSession:
    def __init__(self, page_html: str) -> None:
        self.token = secrets.token_urlsafe(16)
        self.page_html = page_html
        self.url = ""                        # set by open_session
        self.saved_markdown: str | None = None
        self._saved = threading.Event()
        self._lock = threading.Lock()

    def record_save(self, markdown: str) -> None:
        with self._lock:
            self.saved_markdown = markdown   # repeat saves: latest wins
        self._saved.set()

    def wait_for_save(self, timeout: float) -> str | None:
        if self._saved.wait(timeout):
            with self._lock:
                return self.saved_markdown
        return None


_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_session: EditSession | None = None
# Single-generation memory: only the immediately-previous session gets the
# tailored 409; older tabs fall through to 404 and the page's copy fallback.
_prev_token: str | None = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:      # stdio server: keep stderr quiet
        pass

    def _reply(self, code: int, body: str, ctype: str = "text/plain") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _drain_body(self) -> None:
        """Read and discard the declared request body before an error reply.

        Windows resets the connection if we close with unread data, so the
        client would see ECONNABORTED instead of our status code. Bounded by
        the declared Content-Length; chunked to avoid one giant allocation.
        Capped at 2 * _MAX_SAVE_BYTES: legitimate clients (even a 413-bound
        save just over the limit) stay under the cap and get clean replies;
        a liar declaring more gets a fail-fast close instead of streaming
        forever through the 403/404/409 paths.
        """
        try:
            remaining = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True     # undrainable: unknown length
            return
        if remaining > 2 * _MAX_SAVE_BYTES:
            self.close_connection = True
            return
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)

    def _gate(self) -> EditSession | None:
        """Return the live session for this request path, else reply and None."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            self._drain_body()
            self._reply(403, "forbidden")
            return None
        with _lock:
            session, prev = _session, _prev_token
        token = self.path.split("/", 2)[1] if self.path.count("/") >= 2 else ""
        # compare_digest: constant-time; bytes form tolerates non-ASCII paths.
        token_b = token.encode("utf-8")
        if session is not None and secrets.compare_digest(token_b, session.token.encode("utf-8")):
            return session
        self._drain_body()
        if prev is not None and secrets.compare_digest(token_b, prev.encode("utf-8")):
            self._reply(409, "session superseded — reopen the editor from the conversation")
        else:
            self._reply(404, "not found")
        return None

    def do_GET(self) -> None:
        session = self._gate()
        if session is None:
            return
        if self.path == f"/{session.token}/":
            self._reply(200, session.page_html, ctype="text/html")
        else:
            self._drain_body()
            self._reply(404, "not found")

    def do_POST(self) -> None:
        session = self._gate()
        if session is None:
            return
        if self.path != f"/{session.token}/save":
            self._drain_body()
            self._reply(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            # Unknown length: can't drain meaningfully — reply and hard-close.
            self.close_connection = True
            self._reply(400, "bad request")
            return
        if length < 0:
            self.close_connection = True
            self._reply(400, "bad request")
            return
        if length > _MAX_SAVE_BYTES:
            self._drain_body()               # drain before the reply (RST fix)
            self._reply(413, "artifact too large")
            return
        try:
            markdown = self.rfile.read(length).decode("utf-8")
        except UnicodeDecodeError:
            self._reply(400, "bad request")  # body fully read — no drain needed
            return
        session.record_save(markdown)
        self._reply(200, "saved")


def _start_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def open_session(page_html: str) -> tuple[EditSession, str]:
    """Serve ``page_html`` under a fresh token, superseding any prior session."""
    global _server, _session, _prev_token
    with _lock:
        if _server is None:
            _server = _start_server()
        if _session is not None:
            _prev_token = _session.token
        session = EditSession(page_html)
        port = _server.server_address[1]
        session.url = f"http://127.0.0.1:{port}/{session.token}/"
        _session = session
        return session, session.url


def current_session() -> EditSession | None:
    with _lock:
        return _session


def await_save(session: EditSession, timeout: float) -> str | None:
    return session.wait_for_save(timeout)


def open_browser(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def shutdown() -> None:
    """Tear down server + sessions (tests; harmless if never started)."""
    global _server, _session, _prev_token
    with _lock:
        server, _server, _session, _prev_token = _server, None, None, None
    if server is not None:
        server.shutdown()
        server.server_close()
