from __future__ import annotations

import http.client
import io
import json
import stat
import sys
import urllib.error

import pytest

from estimating_tools.exchange import client


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ESTIMATING_HOME", str(tmp_path))
    return tmp_path


class _Resp(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Calls(list):
    """The requests a fake saw, with the timeout each was given."""

    def __init__(self):
        super().__init__()
        self.timeouts = []


def _capture(monkeypatch, body, status=200):
    calls = _Calls()

    def fake_open(req, timeout=0):
        calls.append(req)
        calls.timeouts.append(timeout)
        if status >= 400:
            raise urllib.error.HTTPError(
                req.full_url, status, "err", {}, io.BytesIO(json.dumps(body).encode()))
        return _Resp(body, status)

    monkeypatch.setattr(client, "_open", fake_open)
    return calls


def _raising(monkeypatch, exc):
    def fake_open(req, timeout=0):
        raise exc

    monkeypatch.setattr(client, "_open", fake_open)


def _login():
    client.login("https://www.bidsheet.ai", "abc123")


def test_login_stores_the_token_privately(home):
    p = client.login("https://www.bidsheet.ai", "abc123")
    assert p == home / "bidsheet" / "token.json"
    data = json.loads(p.read_text())
    assert data == {"host": "https://www.bidsheet.ai", "token": "abc123"}
    if sys.platform != "win32":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert [f.name for f in p.parent.iterdir()] == ["token.json"]


def test_fetch_gets_the_workbook_with_the_token_and_items(home, monkeypatch):
    _login()
    calls = _capture(monkeypatch, {"estimate": {"id": 7}, "items": []})
    doc = client.fetch(7, item_ids=[3, 4])
    assert doc["estimate"]["id"] == 7
    req = calls[0]
    assert req.full_url == "https://www.bidsheet.ai/api/estimates/7/workbook/?item_ids=3%2C4"
    assert req.get_header("Authorization") == "Token abc123"
    assert req.get_method() == "GET"


def test_apply_posts_ops_dry_run_and_request_id(home, monkeypatch):
    _login()
    calls = _capture(monkeypatch, {"created": {}, "deleted": [], "totals": {}})
    result = client.apply(7, [{"op": "x"}], dry_run=False, request_id="r-1")
    body = json.loads(calls[0].data)
    assert body == {"ops": [{"op": "x"}], "dry_run": False, "request_id": "r-1"}
    assert calls[0].full_url == "https://www.bidsheet.ai/api/estimates/7/workbook/apply/"
    assert calls[0].get_header("Content-type") == "application/json"
    assert result.dry_run is False and result.created == {}


def test_apply_defaults_to_a_dry_run_and_a_fresh_request_id(home, monkeypatch):
    _login()
    calls = _capture(monkeypatch, {"created": {}, "deleted": [], "totals": {}})
    client.apply(7, [])
    body = json.loads(calls[0].data)
    assert body["dry_run"] is True and len(body["request_id"]) == 36


def test_http_errors_become_client_errors_with_the_server_message(home, monkeypatch):
    _login()
    _capture(monkeypatch,
             {"error": "row changed", "op_index": 2, "conflicts": [{"ref": "resource:3"}]},
             status=409)
    with pytest.raises(client.ClientError) as exc:
        client.apply(7, [{"op": "x"}], request_id="r-8")
    assert exc.value.status == 409 and "row changed" in str(exc.value)
    assert exc.value.body["op_index"] == 2
    assert exc.value.request_id == "r-8"


def test_no_token_is_a_clear_error(home):
    with pytest.raises(client.ClientError, match="est-estimate login"):
        client.fetch(7)


def test_a_host_other_than_the_stored_one_is_refused(home, monkeypatch):
    _login()
    calls = _capture(monkeypatch, {"estimate": {}, "items": []})
    with pytest.raises(client.ClientError, match="login --host https://staging.example"):
        client.fetch(7, host="https://staging.example")
    assert calls == []


@pytest.mark.parametrize("host", ["https://www.bidsheet.ai", "https://www.bidsheet.ai/"])
def test_the_stored_host_given_explicitly_works(home, monkeypatch, host):
    _login()
    calls = _capture(monkeypatch, {"estimate": {}, "items": []})
    client.fetch(7, host=host)
    assert calls[0].full_url.startswith("https://www.bidsheet.ai/api/")


@pytest.mark.parametrize("given", ["https://WWW.bidsheet.ai", "HTTPS://www.BidSheet.AI/",
                                   "https://www.bidsheet.ai"])
def test_a_host_name_is_matched_case_insensitively(home, given):
    assert client._check_host(given) == "https://www.bidsheet.ai"
    client.login(given, "abc123")
    assert client._credentials("https://www.bidsheet.ai") == ("https://www.bidsheet.ai", "abc123")


def test_http_host_is_refused(home):
    with pytest.raises(ValueError, match="https"):
        client.login("http://www.bidsheet.ai", "abc")


@pytest.mark.parametrize("host", ["https://", "https:foo", "https://x.example/a",
                                  "https://x.example?q=1", "https://x.example/#f", 5])
def test_malformed_hosts_are_refused(home, host):
    with pytest.raises(ValueError, match="https origin"):
        client.login(host, "abc")


def test_a_trailing_slash_is_stored_without_it_and_the_token_is_stripped(home):
    p = client.login("https://www.bidsheet.ai/", "  abc123\n")
    assert json.loads(p.read_text()) == {"host": "https://www.bidsheet.ai", "token": "abc123"}


def test_an_empty_token_is_refused(home):
    with pytest.raises(ValueError, match="empty token"):
        client.login("https://www.bidsheet.ai", "   ")


def test_a_corrupt_token_file_is_a_client_error(home):
    _login()
    for bad in ("{not json", "[]", '{"host": 3, "token": "t"}',
                '{"host": "http://x.example", "token": "t"}',
                '{"host": "https://x.example", "token": ""}', '{"host": "https://x.example"}'):
        client.token_path().write_text(bad)
        with pytest.raises(client.ClientError, match="unreadable"):
            client.fetch(7)


def test_a_malformed_plan_is_a_client_error_that_carries_the_request_id(home, monkeypatch):
    _login()
    _capture(monkeypatch, {"created": {"new:r1": "resource"}, "deleted": [], "totals": {}})
    with pytest.raises(client.ClientError) as exc:
        client.apply(7, [{"op": "x"}], dry_run=False, request_id="r-9")
    assert "r-9" in str(exc.value) and "malformed" in str(exc.value)
    assert exc.value.request_id == "r-9"


def test_a_plan_of_the_wrong_shape_is_a_client_error(home, monkeypatch):
    _login()
    _capture(monkeypatch, {"created": ["a"], "deleted": [], "totals": {}})
    with pytest.raises(client.ClientError) as exc:
        client.apply(7, [], request_id="r-5")
    assert exc.value.request_id == "r-5"


def test_a_mismatched_echoed_request_id_is_a_client_error(home, monkeypatch):
    _login()
    _capture(monkeypatch, {"created": {}, "deleted": [], "totals": {}, "request_id": "other"})
    with pytest.raises(client.ClientError, match="echoed request other") as exc:
        client.apply(7, [], request_id="r-1")
    assert exc.value.request_id == "r-1"


@pytest.mark.parametrize("exc,text", [
    (urllib.error.URLError("connection reset"), "could not reach"),
    (TimeoutError("timed out"), "outcome is unknown"),
    (http.client.RemoteDisconnected("closed"), "outcome is unknown"),
    (http.client.IncompleteRead(b"x"), "outcome is unknown"),
])
def test_a_failure_after_the_post_carries_the_request_id(home, monkeypatch, exc, text):
    _login()
    _raising(monkeypatch, exc)
    with pytest.raises(client.ClientError) as e:
        client.apply(7, [{"op": "x"}], dry_run=False, request_id="r-9")
    assert e.value.status is None and e.value.request_id == "r-9"
    assert text in str(e.value)


@pytest.mark.parametrize("err", [http.client.IncompleteRead(b""), TimeoutError("timed out"),
                                 ConnectionResetError("reset")])
def test_an_error_body_that_cannot_be_read_carries_the_status_and_request_id(
        home, monkeypatch, err):
    _login()

    class _Unreadable(io.BytesIO):
        def read(self, *a, **k):
            raise err

    def fake_open(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 500, "err", {}, _Unreadable())

    monkeypatch.setattr(client, "_open", fake_open)
    with pytest.raises(client.ClientError) as e:
        client.apply(7, [{"op": "x"}], dry_run=False, request_id="r-10")
    assert e.value.status == 500 and e.value.request_id == "r-10" and e.value.sent is True
    assert "answered 500" in str(e.value) and type(err).__name__ in str(e.value)
    assert "outcome is unknown" in str(e.value)


def test_a_non_json_success_body_carries_the_request_id(home, monkeypatch):
    _login()

    class Html(_Resp):
        def read(self, *a):
            return b"<html>proxy</html>"

    monkeypatch.setattr(client, "_open", lambda req, timeout=0: Html({}))
    with pytest.raises(client.ClientError, match="not JSON") as exc:
        client.apply(7, [], dry_run=False, request_id="r-4")
    assert exc.value.status is None and exc.value.request_id == "r-4"


def test_a_non_object_answer_is_a_client_error_that_carries_the_request_id(home, monkeypatch):
    _login()
    _capture(monkeypatch, [1, 2])
    with pytest.raises(client.ClientError, match="JSON object") as exc:
        client.apply(7, [], dry_run=False, request_id="r-3")
    assert exc.value.request_id == "r-3"


def test_a_redirect_is_refused_not_followed(home, monkeypatch):
    _login()
    calls = []

    def fake_open(req, timeout=0):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 302, "Found",
                                     {"Location": "https://elsewhere.example/x"}, io.BytesIO(b""))

    monkeypatch.setattr(client, "_open", fake_open)
    with pytest.raises(client.ClientError, match="elsewhere.example") as exc:
        client.apply(7, [], request_id="r-2")
    assert exc.value.status == 302 and exc.value.request_id == "r-2" and len(calls) == 1


def test_the_opener_does_not_build_a_redirected_request():
    handler = client._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://e.example") is None


def test_requests_send_accept_and_the_right_timeouts(home, monkeypatch):
    _login()
    calls = _capture(monkeypatch, {"estimate": {}, "items": []})
    client.fetch(7)
    assert calls[0].get_header("Accept") == "application/json"
    assert calls.timeouts[-1] == client.TIMEOUT
    calls = _capture(monkeypatch, {"created": {}, "deleted": [], "totals": {}})
    client.apply(7, [], dry_run=True)
    assert calls.timeouts[-1] == client.TIMEOUT
    client.apply(7, [], dry_run=False)
    assert calls.timeouts[-1] == client.APPLY_TIMEOUT


def test_an_error_body_that_is_not_an_object_is_wrapped(home, monkeypatch):
    _login()
    _capture(monkeypatch, ["boom"], status=500)
    with pytest.raises(client.ClientError) as exc:
        client.fetch(7)
    assert exc.value.body == {"error": '["boom"]'} and exc.value.status == 500


def test_the_detail_field_and_validation_dicts_become_the_message(home, monkeypatch):
    _login()
    _capture(monkeypatch, {"detail": "Invalid token."}, status=401)
    with pytest.raises(client.ClientError, match="Invalid token"):
        client.fetch(7)
    _capture(monkeypatch, {"ops": ["required"]}, status=400)
    with pytest.raises(client.ClientError, match="required"):
        client.fetch(7)


def test_a_local_refusal_was_never_sent(home, monkeypatch):
    calls = _capture(monkeypatch, {})
    with pytest.raises(client.ClientError) as exc:
        client.apply(7, [{"op": "x"}], dry_run=False, request_id="r-1")
    assert exc.value.sent is False and calls == []
    _login()
    with pytest.raises(client.ClientError) as exc:
        client.apply(7, [{"op": "x"}], dry_run=False, host="https://staging.example")
    assert exc.value.sent is False and calls == []
    client.token_path().write_text("{not json")
    with pytest.raises(client.ClientError) as exc:
        client.fetch(7)
    assert exc.value.sent is False


@pytest.mark.parametrize("exc", [urllib.error.URLError("reset"), TimeoutError("timed out"),
                                 http.client.RemoteDisconnected("closed")])
def test_a_failure_after_the_handoff_was_sent(home, monkeypatch, exc):
    _login()
    _raising(monkeypatch, exc)
    with pytest.raises(client.ClientError) as e:
        client.apply(7, [{"op": "x"}], dry_run=False, request_id="r-9")
    assert e.value.sent is True and e.value.status is None


@pytest.mark.parametrize("body, status", [
    ({"error": "nope"}, 409), ([1, 2], 200),
    ({"created": {}, "deleted": [], "totals": {}, "request_id": "other"}, 200),
    ({"created": ["a"], "deleted": [], "totals": {}}, 200),
])
def test_an_answer_the_client_refuses_was_sent(home, monkeypatch, body, status):
    _login()
    _capture(monkeypatch, body, status=status)
    with pytest.raises(client.ClientError) as e:
        client.apply(7, [], dry_run=False, request_id="r-2")
    assert e.value.sent is True


def test_a_status_implies_sent():
    assert client.ClientError("x", status=500).sent is True
    assert client.ClientError("x").sent is False


def test_fetch_pages_long_item_lists(home, monkeypatch):
    _login()
    seen = []

    def fake_request(method, url, token, *args, **kwargs):
        seen.append(url)
        n = len(seen)
        return {"estimate": {"id": 1, "v": "e"}, "items": [{"id": n, "item_number": str(n)}],
                "elements": [], "activities": [], "resources": [], "crews": [],
                "rates": {}, "shares": []}

    monkeypatch.setattr(client, "_request", fake_request)
    ids = list(range(1, 251))
    doc = client.fetch(1, item_ids=ids)
    assert len(seen) == 3                       # 100 + 100 + 50
    assert all(len(u) < 1000 for u in seen)
    assert [i["id"] for i in doc["items"]] == [1, 2, 3]
    assert doc["_fetch"] == {"item_ids": ids}


def test_fetch_of_the_whole_estimate_records_nothing(home, monkeypatch):
    _login()
    monkeypatch.setattr(client, "_request",
                        lambda *a, **k: {"estimate": {"id": 1}, "items": []})
    assert "_fetch" not in client.fetch(1)
