"""The bulk leg of the contract (part 1): fetch the read model and apply a
change set over REST, as the user, to and from files. The agent runs this
and never relays a payload (rule 14). Every apply carries a request_id
(rule 12; BidManager #1676)."""
from __future__ import annotations

import http.client
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from estimating_tools.exchange.types import ApplyResult

HOME_ENV = "ESTIMATING_HOME"
APP = ".estimating"
TIMEOUT = 120
APPLY_TIMEOUT = 300


class ClientError(RuntimeError):
    """A refusal or a transport failure. ``status`` is the HTTP status when
    the server answered, else None; ``body`` is the server's JSON when it
    sent one; ``request_id`` is the apply's id when the error came from an
    apply, so the CLI can tell the user how to replay it. ``sent`` is True
    once the request was handed to the network (always when the server
    answered with a status): only then can the outcome be unknown. A local
    refusal (no token, an unreadable token file, another host) is never sent."""

    def __init__(self, message: str, *, status: int | None = None, body: dict | None = None,
                 request_id: str | None = None, sent: bool = False):
        super().__init__(message)
        self.status = status
        self.body = body or {}
        self.request_id = request_id
        self.sent = bool(sent) or status is not None


def _home() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else Path.home() / APP


def token_path() -> Path:
    return _home() / "bidsheet" / "token.json"


def _check_host(host: str) -> str:
    bad = ValueError("the BidSheet.ai host must be an https origin such as "
                     "https://www.bidsheet.ai")
    if not isinstance(host, str):
        raise bad
    u = urllib.parse.urlparse(host.strip().rstrip("/"))
    if u.scheme != "https" or not u.netloc or u.path or u.query or u.fragment or u.params:
        raise bad
    return f"https://{u.netloc.lower()}"      # a host name is case-insensitive


def login(host: str, token: str) -> Path:
    """Store the user's API token for ``host``. The file is created private
    (mode 600, directory 700); on Windows the mode is a no-op and the profile
    directory's ACL protects the file."""
    host = _check_host(host)
    if not isinstance(token, str) or not token.strip():
        raise ValueError("an empty token")
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"host": host, "token": token.strip()}))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _credentials(host: str | None) -> tuple[str, str]:
    """The stored (host, token); a different ``host`` is refused, never paired with the token."""
    path = token_path()
    if not path.is_file():
        raise ClientError("no BidSheet.ai token stored -- run `est-estimate login` first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stored = _check_host(data["host"])
        token = data["token"]
        if not isinstance(token, str) or not token.strip():
            raise ValueError("empty token")
    except (OSError, ValueError, KeyError, TypeError):
        raise ClientError("the stored BidSheet.ai token file is unreadable -- run "
                          "`est-estimate login` again") from None
    if host is not None:
        wanted = _check_host(host)
        if wanted != stored:
            raise ClientError(f"the stored token is for {stored}; run "
                              f"`est-estimate login --host {wanted}` to use {wanted}")
    return stored, token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the Authorization header."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(req, timeout):
    """The one network seam (tests patch it)."""
    return _OPENER.open(req, timeout=timeout)


def _request(method: str, url: str, token: str, body: dict | None = None,
             *, request_id: str | None = None, timeout: int = TIMEOUT) -> dict:
    """One JSON request; every failure is a ClientError that keeps ``request_id``."""
    data = None
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _open(req, timeout) as resp:
            raw = resp.read()
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise ClientError("BidSheet.ai answered with something that is not JSON",
                              request_id=request_id, sent=True) from None
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ClientError(f"BidSheet.ai redirected to {exc.headers.get('Location')}; "
                              "set the host to the final URL",
                              status=exc.code, request_id=request_id, sent=True) from None
        try:
            raw_err = exc.read().decode("utf-8", "replace")
        except (OSError, http.client.HTTPException) as err:
            # The status arrived but the body did not (a reset, a timeout, a
            # short read): after a committed POST that is an unknown outcome.
            raise ClientError(f"BidSheet.ai answered {exc.code} but its answer could not be "
                              f"read ({type(err).__name__}); the outcome is unknown",
                              status=exc.code, request_id=request_id, sent=True) from None
        try:
            parsed = json.loads(raw_err)
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            parsed = {"error": raw_err[:500]}
        message = parsed.get("error") or parsed.get("detail")
        if not message:
            message = json.dumps(parsed)[:300] if parsed else f"HTTP {exc.code}"
        raise ClientError(f"BidSheet.ai refused ({exc.code}): {message}",
                          status=exc.code, body=parsed, request_id=request_id, sent=True) from None
    except urllib.error.URLError as exc:
        raise ClientError(f"could not reach BidSheet.ai: {exc.reason}",
                          request_id=request_id, sent=True) from None
    except (OSError, http.client.HTTPException) as exc:
        raise ClientError(f"no answer from BidSheet.ai ({type(exc).__name__}); "
                          "the outcome is unknown", request_id=request_id, sent=True) from None
    if not isinstance(parsed, dict):
        raise ClientError("BidSheet.ai answered with something that is not a JSON object",
                          request_id=request_id, sent=True)
    return parsed


#: Item ids per request. Keeps the request line far under gunicorn's 4 KB
#: default (a 600-item book's ids would pass it); the pages are merged here.
FETCH_PAGE = 100


def fetch(estimate_id, item_ids=None, *, host: str | None = None) -> dict:
    """``GET /api/estimates/{id}/workbook/`` as the user. With ``item_ids``,
    a page: at most ``FETCH_PAGE`` ids per request, the pages merged
    (``model.merge_pages``) and the ids recorded under ``_fetch`` so a
    build knows the payload is a page. Raises ``ClientError``; a page set
    that does not merge (the estimate changed between requests) raises the
    ``PayloadError`` (a ``ValueError``) from ``merge_pages``."""
    from estimating_tools.exchange.model import merge_pages

    ids = [int(i) for i in item_ids] if item_ids else None
    if ids is not None and not ids:
        raise ValueError("no item ids given")
    host, token = _credentials(host)
    base = f"{host}/api/estimates/{int(estimate_id)}/workbook/"
    if ids is None:
        return _request("GET", base, token)
    pages = []
    for start in range(0, len(ids), FETCH_PAGE):
        chunk = ids[start:start + FETCH_PAGE]
        query = urllib.parse.urlencode({"item_ids": ",".join(str(i) for i in chunk)})
        pages.append(_request("GET", base + "?" + query, token))
    doc = merge_pages(pages)
    doc["_fetch"] = {"item_ids": ids}
    return doc


def apply(estimate_id, ops: list, *, dry_run: bool = True, request_id: str | None = None,
          host: str | None = None) -> ApplyResult:
    """``POST /api/estimates/{id}/workbook/apply/``. Dry run unless told
    otherwise; always with a request_id (a server that predates #1676
    ignores it). A malformed plan from the server is a ClientError that
    carries the request_id, so a committed apply can still be replayed."""
    host, token = _credentials(host)
    request_id = request_id or str(uuid.uuid4())
    body = {"ops": list(ops), "dry_run": bool(dry_run), "request_id": request_id}
    plan = _request("POST", f"{host}/api/estimates/{int(estimate_id)}/workbook/apply/", token,
                    body, request_id=request_id,
                    timeout=TIMEOUT if dry_run else APPLY_TIMEOUT)
    echoed = plan.get("request_id")
    if echoed is not None and echoed != request_id:
        raise ClientError(f"BidSheet.ai echoed request {echoed} for request {request_id}",
                          request_id=request_id, body=plan, sent=True)
    plan.setdefault("request_id", request_id)
    try:
        return ApplyResult.from_plan(plan, dry_run=bool(dry_run))
    except (ValueError, TypeError) as exc:
        raise ClientError(f"BidSheet.ai answered request {request_id} with a plan this client "
                          f"cannot read: {exc}", request_id=request_id, body=plan,
                          sent=True) from None
