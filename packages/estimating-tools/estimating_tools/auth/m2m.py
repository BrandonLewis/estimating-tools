"""Pure OAuth client_credentials token-request builder + response parser.
No network, no env, no manifest — the CLI supplies values and performs the POST.
"""
from __future__ import annotations

import base64
import json
from urllib.parse import quote_plus, urlencode, urlparse


def build_token_request(
    token_url: str, client_id: str, client_secret: str, scope: str = "mcp"
) -> dict:
    """Build the client_credentials token POST (client_secret_basic).

    Returns {"url", "data" (bytes), "headers"}. The secret appears only in the
    Basic Authorization header — never in the body or URL. Raises ValueError for a
    non-https token_url or empty credentials (messages never include the secret).
    """
    if urlparse(token_url).scheme != "https":
        raise ValueError("token_url must use https")
    if not client_id or not client_secret:
        raise ValueError("client_id and client_secret are required")
    # RFC 6749 §2.3.1: form-urlencode id and secret before joining with ':' and
    # base64-encoding, so a reserved char (':', space) in a secret can't break the pair.
    cred = f"{quote_plus(client_id)}:{quote_plus(client_secret)}"
    basic = base64.b64encode(cred.encode()).decode()
    data = urlencode({"grant_type": "client_credentials", "scope": scope}).encode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    return {"url": token_url, "data": data, "headers": headers}


def parse_token_response(body: str | dict) -> str:
    """Return the bearer access_token from a token-endpoint response.

    Raises ValueError carrying the server's error/error_description on an error body,
    or a generic message when access_token is missing / token_type is not Bearer.
    Never includes request credentials.
    """
    data = body if isinstance(body, dict) else json.loads(body)
    if "error" in data:
        desc = data.get("error_description", "")
        raise ValueError(
            f"token endpoint error: {data['error']}" + (f": {desc}" if desc else "")
        )
    token = data.get("access_token")
    if not token:
        raise ValueError("token response missing access_token")
    if (data.get("token_type") or "").lower() != "bearer":
        raise ValueError(f"unexpected token_type: {data.get('token_type')!r}")
    return token
