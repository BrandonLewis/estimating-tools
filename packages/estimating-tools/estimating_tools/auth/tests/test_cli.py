import io
import textwrap
import urllib.error

import pytest

from estimating_tools.auth import cli

MANIFEST = textwrap.dedent("""\
    servers:
      - id: bidmanager
        url_env: BIDMANAGER_MCP_URL
        url_default: "https://bidsheet.ai/mcp/"
        transport: http
        auth:
          oauth: true
          m2m:
            token_url: "https://www.bidsheet.ai/oauth/token"
            token_url_env: BIDMANAGER_TOKEN_URL
            scope: mcp
            client_id_env: BIDMANAGER_CLIENT_ID
            client_secret_env: BIDMANAGER_CLIENT_SECRET
""")


@pytest.fixture()
def manifest(tmp_path):
    p = tmp_path / "servers.manifest.yaml"
    p.write_text(MANIFEST)
    return str(p)


def test_prints_token_on_success(manifest, monkeypatch, capsys):
    monkeypatch.setenv("BIDMANAGER_CLIENT_ID", "cid")
    monkeypatch.setenv("BIDMANAGER_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(cli, "_fetch_token",
                        lambda req: '{"access_token": "tok-123", "token_type": "Bearer"}')
    rc = cli.main(["--server", "bidmanager", "--manifest", manifest])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "tok-123"


def test_header_flag_emits_authorization_line(manifest, monkeypatch, capsys):
    monkeypatch.setenv("BIDMANAGER_CLIENT_ID", "cid")
    monkeypatch.setenv("BIDMANAGER_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(cli, "_fetch_token",
                        lambda req: '{"access_token": "tok-123", "token_type": "Bearer"}')
    rc = cli.main(["--server", "bidmanager", "--manifest", manifest, "--header"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "Authorization: Bearer tok-123"


def test_missing_credentials_exits_without_calling_network(manifest, monkeypatch, capsys):
    monkeypatch.delenv("BIDMANAGER_CLIENT_ID", raising=False)
    monkeypatch.delenv("BIDMANAGER_CLIENT_SECRET", raising=False)
    called = []
    monkeypatch.setattr(cli, "_fetch_token", lambda req: called.append(1) or "{}")
    rc = cli.main(["--server", "bidmanager", "--manifest", manifest])
    assert rc == 1
    assert called == []                                   # never hits the network
    err = capsys.readouterr().err
    assert "BIDMANAGER_CLIENT_ID" in err                  # tells the operator which vars to set


def test_unknown_server_exits(manifest, capsys):
    rc = cli.main(["--server", "nope", "--manifest", manifest])
    assert rc == 1


def test_parse_failure_does_not_leak_token(manifest, monkeypatch, capsys):
    monkeypatch.setenv("BIDMANAGER_CLIENT_ID", "cid")
    monkeypatch.setenv("BIDMANAGER_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(cli, "_fetch_token",
                        lambda req: '{"access_token": "LEAKED-TOKEN-XYZ", "token_type": "mac"}')
    rc = cli.main(["--server", "bidmanager", "--manifest", manifest])
    assert rc == 1
    assert "LEAKED-TOKEN-XYZ" not in capsys.readouterr().err


def test_httperror_surfaces_server_error_not_secret(manifest, monkeypatch, capsys):
    monkeypatch.setenv("BIDMANAGER_CLIENT_ID", "cid")
    monkeypatch.setenv("BIDMANAGER_CLIENT_SECRET", "csecret-value")
    def _raise(req):
        raise urllib.error.HTTPError(
            req["url"], 401, "Unauthorized", {},
            io.BytesIO(b'{"error":"invalid_client","error_description":"bad client"}'))
    monkeypatch.setattr(cli, "_fetch_token", _raise)
    rc = cli.main(["--server", "bidmanager", "--manifest", manifest])
    err = capsys.readouterr().err
    assert rc == 1
    assert "invalid_client" in err and "bad client" in err
    assert "csecret-value" not in err


def test_token_url_defaults_when_env_unset(manifest, monkeypatch, capsys):
    # No BIDMANAGER_TOKEN_URL in the environment -> the manifest default is used.
    monkeypatch.delenv("BIDMANAGER_TOKEN_URL", raising=False)
    monkeypatch.setenv("BIDMANAGER_CLIENT_ID", "cid")
    monkeypatch.setenv("BIDMANAGER_CLIENT_SECRET", "csecret")
    seen = {}
    monkeypatch.setattr(cli, "build_token_request",
                        lambda url, cid, sec, scope: seen.update(url=url) or
                        {"url": url, "data": b"", "headers": {}})
    monkeypatch.setattr(cli, "_fetch_token",
                        lambda req: '{"access_token": "tok", "token_type": "Bearer"}')
    rc = cli.main(["--server", "bidmanager", "--manifest", manifest])
    assert rc == 0
    assert seen["url"] == "https://www.bidsheet.ai/oauth/token"


def test_token_url_env_overrides_manifest_default(manifest, monkeypatch, capsys):
    # A set BIDMANAGER_TOKEN_URL repoints the token endpoint without editing files.
    monkeypatch.setenv("BIDMANAGER_TOKEN_URL", "https://staging.bidsheet.ai/oauth/token")
    monkeypatch.setenv("BIDMANAGER_CLIENT_ID", "cid")
    monkeypatch.setenv("BIDMANAGER_CLIENT_SECRET", "csecret")
    seen = {}
    monkeypatch.setattr(cli, "build_token_request",
                        lambda url, cid, sec, scope: seen.update(url=url) or
                        {"url": url, "data": b"", "headers": {}})
    monkeypatch.setattr(cli, "_fetch_token",
                        lambda req: '{"access_token": "tok", "token_type": "Bearer"}')
    rc = cli.main(["--server", "bidmanager", "--manifest", manifest])
    assert rc == 0
    assert seen["url"] == "https://staging.bidsheet.ai/oauth/token"


def test_manifest_without_servers_key_exits(tmp_path, capsys):
    p = tmp_path / "m.yaml"
    p.write_text("other: 1\n")
    rc = cli.main(["--server", "bidmanager", "--manifest", str(p)])
    assert rc == 1 and "servers" in capsys.readouterr().err


def test_manifest_with_null_servers_exits_cleanly(tmp_path, capsys):
    # 'servers:' present but null (not a list) -> clean exit 1, not an uncaught TypeError
    p = tmp_path / "m.yaml"
    p.write_text("servers:\n")
    rc = cli.main(["--server", "bidmanager", "--manifest", str(p)])
    assert rc == 1 and "servers" in capsys.readouterr().err
