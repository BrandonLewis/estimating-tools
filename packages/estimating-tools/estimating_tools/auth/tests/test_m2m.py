import base64

import pytest

from estimating_tools.auth.m2m import build_token_request, parse_token_response

ID, SECRET = "client-abc", "s3cr3t-value"


def test_build_request_shape_and_basic_auth():
    req = build_token_request("https://auth.example.com/oauth/token", ID, SECRET)
    assert req["url"] == "https://auth.example.com/oauth/token"
    assert req["data"] == b"grant_type=client_credentials&scope=mcp"
    expected = "Basic " + base64.b64encode(f"{ID}:{SECRET}".encode()).decode()
    assert req["headers"]["Authorization"] == expected
    assert req["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert req["headers"]["Accept"] == "application/json"


def test_basic_auth_form_urlencodes_id_and_secret():
    # RFC 6749 §2.3.1: a reserved char (':', space) in the secret is form-urlencoded
    # before base64, so it can't be confused with the id:secret separator.
    req = build_token_request("https://a.example/t", "id", "se:cr et")
    expected = "Basic " + base64.b64encode(b"id:se%3Acr+et").decode()
    assert req["headers"]["Authorization"] == expected


def test_build_request_custom_scope_is_urlencoded():
    req = build_token_request("https://a.example/t", ID, SECRET, scope="mcp admin")
    assert req["data"] == b"grant_type=client_credentials&scope=mcp+admin"


def test_secret_only_in_basic_header_never_in_body_or_url():
    req = build_token_request("https://a.example/t", ID, SECRET)
    assert SECRET not in req["url"]
    assert SECRET.encode() not in req["data"]      # not in the form body (only base64'd in the header)


def test_non_https_token_url_raises():
    with pytest.raises(ValueError):
        build_token_request("http://insecure.example/token", ID, SECRET)
    with pytest.raises(ValueError):
        build_token_request("example.com/token", ID, SECRET)   # schemeless -> not https


def test_empty_credentials_raise_without_leaking():
    with pytest.raises(ValueError) as e1:
        build_token_request("https://a.example/t", "", SECRET)
    with pytest.raises(ValueError) as e2:
        build_token_request("https://a.example/t", ID, "")
    assert SECRET not in str(e1.value) and SECRET not in str(e2.value)


def test_parse_returns_bearer_token():
    assert parse_token_response('{"access_token": "abc123", "token_type": "Bearer"}') == "abc123"
    # lowercase token_type also accepted; dict body also accepted
    assert parse_token_response({"access_token": "z", "token_type": "bearer"}) == "z"


def test_parse_error_body_raises_with_server_error():
    with pytest.raises(ValueError) as e:
        parse_token_response('{"error": "invalid_client", "error_description": "bad secret"}')
    msg = str(e.value)
    assert "invalid_client" in msg and "bad secret" in msg


def test_parse_missing_token_or_wrong_type_raises():
    with pytest.raises(ValueError):
        parse_token_response('{"token_type": "Bearer"}')          # no access_token
    with pytest.raises(ValueError):
        parse_token_response('{"access_token": "x", "token_type": "mac"}')  # wrong type
    with pytest.raises(ValueError):
        parse_token_response('{"access_token": "x"}')           # token_type key absent
