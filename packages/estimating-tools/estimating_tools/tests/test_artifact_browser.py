"""Tests for the browser edit surface: page mode + loopback session server."""
import urllib.error
import urllib.request

import pytest

from estimating_tools.artifact_app import browser
from estimating_tools.artifacts_html import to_editable_html
from estimating_tools.tests.test_artifacts_html import ASSEMBLY_MD


def test_browser_save_page_has_save_button_and_bridge():
    page = to_editable_html(ASSEMBLY_MD, title="T", browser_save=True)
    assert '<button id="save">Save &amp; send to Claude</button>' in page
    assert 'fetch("save"' in page
    assert '<button id="copy">' in page          # copy fallback stays
    assert "GRID-CORE begin" in page


def test_default_page_is_unchanged_no_save_affordance():
    page = to_editable_html(ASSEMBLY_MD, title="T")
    assert 'id="save"' not in page
    assert "fetch(" not in page


def test_read_only_page_has_no_save_even_with_browser_save():
    page = to_editable_html(ASSEMBLY_MD, title="T", editable=False, browser_save=True)
    assert 'id="save"' not in page and 'id="copy"' not in page


@pytest.fixture(autouse=True)
def _reset_browser_state():
    yield
    browser.shutdown()  # kill server between tests so state never leaks


def _get(url, host=None):
    req = urllib.request.Request(url)
    if host:
        req.add_header("Host", host)
    return urllib.request.urlopen(req, timeout=5)


def _post(url, body):
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    return urllib.request.urlopen(req, timeout=5)


def test_serve_and_save_roundtrip():
    session, url = browser.open_session("<html>PAGE</html>")
    assert url.startswith("http://127.0.0.1:") and url.endswith(f"/{session.token}/")
    assert _get(url).read().decode("utf-8") == "<html>PAGE</html>"
    _post(url + "save", "| edited |")
    assert browser.await_save(session, timeout=5) == "| edited |"


def test_repeat_saves_latest_wins():
    session, url = browser.open_session("p")
    _post(url + "save", "first")
    _post(url + "save", "second")
    assert browser.await_save(session, timeout=5) == "second"


def test_await_save_times_out_to_none():
    session, url = browser.open_session("p")
    assert browser.await_save(session, timeout=0.05) is None


def test_unknown_token_is_404():
    _session, url = browser.open_session("p")
    base = url.rsplit("/", 2)[0]  # http://127.0.0.1:port
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(f"{base}/not-a-token/")
    assert e.value.code == 404


def test_superseded_session_is_409_and_new_session_works():
    _old, old_url = browser.open_session("old")
    new, new_url = browser.open_session("new")
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(old_url + "save", "stale")
    assert e.value.code == 409
    assert "superseded" in e.value.read().decode("utf-8")
    assert _get(new_url).read().decode("utf-8") == "new"
    assert old_url.rsplit("/", 2)[0] == new_url.rsplit("/", 2)[0]  # same server/port


def test_foreign_host_header_is_403():
    session, url = browser.open_session("p")
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(url, host="evil.example")
    assert e.value.code == 403


def test_current_session_accessor():
    assert browser.current_session() is None
    session, url = browser.open_session("p")
    assert browser.current_session() is session
    assert session.url == url


def test_oversized_save_is_413():
    session, url = browser.open_session("p")
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(url + "save", "x" * (4 * 1024 * 1024 + 1))
    assert e.value.code == 413


def test_non_utf8_save_body_is_400():
    session, url = browser.open_session("p")
    req = urllib.request.Request(url + "save", data=b"\xff\xfe\xfa", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_post_to_page_path_is_404():
    session, url = browser.open_session("p")
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(url, "body")
    assert e.value.code == 404
