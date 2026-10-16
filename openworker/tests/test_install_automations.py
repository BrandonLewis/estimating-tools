"""install.py automation-payload installation (idempotent by title)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install  # noqa: E402


def test_installs_only_missing_titles(monkeypatch):
    calls = []

    def fake_api(server, token, path, body=None):
        calls.append((path, body))
        if body is None:  # the GET list
            return {"automations": [{"title": "Bid-day quote sweep"}]}
        return {"ok": True}

    monkeypatch.setattr(install, "api", fake_api)
    installed = install.install_automations("http://x", None, dry_run=False)
    posted_titles = {b["title"] for p, b in calls if b is not None}
    assert "Bid-day quote sweep" not in posted_titles      # already there
    assert "Morning estimate rollup" in posted_titles       # was missing
    assert set(installed) == posted_titles


def test_dry_run_posts_nothing(monkeypatch):
    calls = []

    def fake_api(server, token, path, body=None):
        calls.append(body)
        return {"automations": []}

    monkeypatch.setattr(install, "api", fake_api)
    would = install.install_automations("http://x", None, dry_run=True)
    assert all(b is None for b in calls)                    # GET only
    assert len(would) == len(list(install.AUTOMATIONS_SRC.glob("*.json")))


def test_unexpected_dict_shape_fails_loudly(monkeypatch):
    """A dict without "automations" must not be silently iterated (which would
    empty `have` and defeat idempotence) — it must SystemExit."""
    import pytest

    def fake_api(server, token, path, body=None):
        return {"items": [], "total": 0}

    monkeypatch.setattr(install, "api", fake_api)
    with pytest.raises(SystemExit) as exc:
        install.install_automations("http://x", None, dry_run=True)
    assert "unexpected /v1/automations response shape" in str(exc.value)
    assert "items" in str(exc.value)


def test_dict_valued_automations_member_fails_loudly(monkeypatch):
    """{"automations": {...}} passes the key check but iterating the dict's
    keys would empty `have` and re-POST everything — must SystemExit."""
    import pytest

    def fake_api(server, token, path, body=None):
        return {"automations": {"Bid-day quote sweep": {"title": "Bid-day quote sweep"}}}

    monkeypatch.setattr(install, "api", fake_api)
    with pytest.raises(SystemExit) as exc:
        install.install_automations("http://x", None, dry_run=True)
    assert "unexpected /v1/automations response shape" in str(exc.value)


def test_payload_missing_title_fails_loudly(monkeypatch, tmp_path):
    import pytest

    bad = tmp_path / "no-title.json"
    bad.write_text(json.dumps({"instructions": "do things"}), encoding="utf-8")
    monkeypatch.setattr(install, "AUTOMATIONS_SRC", tmp_path)

    def fake_api(server, token, path, body=None):
        return {"automations": []}

    monkeypatch.setattr(install, "api", fake_api)
    with pytest.raises(SystemExit) as exc:
        install.install_automations("http://x", None, dry_run=True)
    assert "no-title.json" in str(exc.value)
    assert "missing 'title'" in str(exc.value)
