import json

import pytest

from estimating_tools.feedback import payload as fp


def test_build_payload_is_markdown_only_and_bounded():
    out = fp.build_payload(
        product="estimating-plugin",
        kind="bug",
        title="  <b>Crash</b> on\npush ",
        body="It <script>alert(1)</script>crashed\u200b.\r\n\r\n\r\n**Steps**<!-- x -->",
        context={"error_excerpt": "Trace <i>x</i>\u0000", "n": 2, "ok": True, "none": None},
    )
    assert out == {
        "product": "estimating-plugin",
        "kind": "bug",
        "title": "Crash on push",
        "body": "It alert(1)crashed.\n\n**Steps**",
        "context": {"error_excerpt": "Trace x", "n": 2, "ok": True, "none": None},
    }
    assert list(out) == list(fp.PAYLOAD_KEYS)


def test_a_bare_less_than_survives():
    assert fp.sanitize_body("a < b and c <= d") == "a < b and c <= d"


def test_build_is_idempotent_and_check_accepts_its_output():
    out = fp.build_payload(product="bidmanager", kind="feature-request",
                           title="Dark mode", body="Please **add** it.\n\n- a\n- b",
                           context={"plugin_version": "0.1.87"})
    assert fp.build_payload(**out) == out
    assert fp.check_payload(out) == []


@pytest.mark.parametrize("raw,expected", [
    (r"C:\Users\estimator\proj\x.py", r"~\proj\x.py"),
    ("/ho" "me/estimator/proj/x.py", "~/proj/x.py"),  # split: the public scanner reads source
    ("/Us" "ers/estimator/proj", "~/proj"),  # split: the scanner reads source
    ("see /usr/lib/python3", "see /usr/lib/python3"),
    ("Authorization: Bea" "rer abcdefghijklmnopqrstuvwxyz0123", "Authorization: Bearer [redacted-token]"),
    ("tok ey" "JhbGciOiJIUzI1NiJ9.ey" "JzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV",
     "tok [redacted-token]"),
    ("key sk-abcdefghijklmnopqrstuvwxyz", "key [redacted-token]"),
    ("gh" "p_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", "[redacted-token]"),
    ("AK" "IAABCDEFGHIJKLMNOP in env", "[redacted-token] in env"),
    ("client_secret=s3cr3t-value&x=1", "client_secret=[redacted]&x=1"),
    ("password: hunter2", "password: [redacted]"),
    ("mail someone@example.com now", "mail [email] now"),
])
def test_scrub(raw, expected):
    assert fp.scrub(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ('PASSWORD="hunter2"', 'PASSWORD="[redacted]"'),
    ("API_KEY='opaque-credential'", "API_KEY='[redacted]'"),
    ('{"password": "hunter2", "attempt": 1}',
     '{"password": "[redacted]", "attempt": 1}'),
    ("{'access_token': 'opaque-credential', 'attempt': 1}",
     "{'access_token': '[redacted]', 'attempt': 1}"),
    ('password="two words; a,b&c" next=value', 'password="[redacted]" next=value'),
    (r'password="escaped\"quote"', 'password="[redacted]"'),
    (r"password='escaped\'quote'", "password='[redacted]'"),
    ('password=abc[def]{ghi}', 'password=[redacted]'),
    ('{"token":12345,"ok":true}', '{"token":[redacted],"ok":true}'),
])
def test_scrub_quoted_credentials_preserves_surrounding_text(raw, expected):
    assert fp.scrub(raw) == expected
    assert fp.scrub(expected) == expected


@pytest.mark.parametrize("key", [
    "DB_PASSWORD", "BIDMANAGER_CLIENT_SECRET", "APP_DB_ACCESS_TOKEN",
    "CONFORMED_CLIENT_SECRET", "app-api-key",
])
def test_namespaced_secrets_are_redacted_in_text_and_nested_context(key):
    raw = f'{key}="synthetic-credential"'
    assert fp.scrub(raw) == f'{key}="[redacted]"'
    out = fp.build_payload(product="bidmanager", kind="bug", title=raw, body=raw,
                           context={"request": {key: "synthetic-credential"}})
    assert out["title"] == f'{key}="[redacted]"'
    assert out["body"] == f'{key}="[redacted]"'
    assert out["context"] == {"request": {key: "[redacted]"}}
    assert fp.check_payload(out) == []
    assert fp.check_payload({**out, "context": {"request": {key: "synthetic-credential"}}})


def test_namespace_matching_keeps_non_secret_context():
    context = {"DB_PASSWORD_POLICY": "strict", "token_count": 2, "secretary": "present"}
    out = fp.build_payload(product="bidmanager", kind="bug", title="T", body="B",
                           context=context)
    assert out["context"] == context


@pytest.mark.parametrize("raw,expected", [
    (r'File "C:\Users\Jane Doe\project\app.py", line 1',
     r'File "~\project\app.py", line 1'),
    ('"C:/Us' 'ers/Jane Doe/project/app.py" failed', '"~/project/app.py" failed'),
    ('File "/Us' 'ers/Jane Doe/project/app.py", line 1', 'File "~/project/app.py", line 1'),
    ('at /home/Jane Doe/project: failed', 'at ~/project: failed'),
    (r'"C:\Users\Jane Doe" failed', '"~" failed'),
    ('"/Us' 'ers/Jane Doe" failed', '"~" failed'),
    ('at /ho' 'me/estimator failed in /usr/lib/python3', 'at ~ failed in /usr/lib/python3'),
    (r'Home C:\Users\estimator failed in C:\Windows\System32',
     r'Home ~ failed in C:\Windows\System32'),
])
def test_home_path_scrubbing_handles_spaces_and_preserves_prose(raw, expected):
    assert fp.scrub(raw) == expected
    out = fp.build_payload(product="bidmanager", kind="bug", title="Crash", body=raw,
                           context={"error_excerpt": raw})
    assert out["body"] == expected
    assert out["context"] == {"error_excerpt": expected}
    assert fp.check_payload(out) == []


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("nested", [False, True])
def test_non_finite_context_numbers_are_rejected_with_their_path(number, nested):
    context = {"details": [number]} if nested else {"elapsed": number}
    path = "context.details[0]" if nested else "context.elapsed"
    with pytest.raises(fp.PayloadError) as error:
        fp.build_payload(product="bidmanager", kind="bug", title="T", body="B", context=context)
    assert str(error.value) == f"{path} must be a finite number."
    assert fp.check_payload({"product": "bidmanager", "kind": "bug", "title": "T", "body": "B",
                             "context": context}) == [f"{path} must be a finite number."]


def test_context_redacts_secret_values_using_normalized_keys():
    out = fp.build_payload(
        product="bidmanager", kind="bug", title="Crash", body="Request failed",
        context={
            "password": "hunter2",
            "request": {"ACCESS_TOKEN": "opaque-credential", "attempt": 1},
            "headers": [{"api_<b>key</b>": "opaque-credential"}],
            "to\u200bken": ["first", "second"],
            "client-secret": {"value": "opaque-credential"},
        },
    )
    assert out["context"] == {
        "password": "[redacted]",
        "request": {"ACCESS_TOKEN": "[redacted]", "attempt": 1},
        "headers": [{"api_key": "[redacted]"}],
        "token": "[redacted]",
        "client-secret": "[redacted]",
    }
    assert fp.check_payload(out) == []
    assert fp.build_payload(**out) == out


@pytest.mark.parametrize("value", [None, False, 12345, 1.5, "", ["first"], {"value": "second"}])
def test_context_redacts_secret_values_of_any_json_type(value):
    out = fp.build_payload(product="bidmanager", kind="bug", title="Crash", body="Failed",
                           context={"password": value})
    assert out["context"] == {"password": "[redacted]"}
    assert fp.check_payload(out) == []


@pytest.mark.parametrize("fields", [
    {"title": 'PASSWORD="hunter2"'},
    {"body": '{"password": "hunter2"}'},
    {"context": {"password": "hunter2"}},
    {"context": {"request": {"access_token": "opaque-credential"}}},
    {"context": {"error_excerpt": 'API_KEY="opaque-credential"'}},
])
def test_check_refuses_payloads_containing_unredacted_credentials(fields):
    payload = {"product": "bidmanager", "kind": "bug", "title": "Crash", "body": "Failed",
               "context": {}, **fields}
    assert fp.check_payload(payload)


@pytest.mark.parametrize("raw,expected", [
    ('<scr<script>ipt>alert(1)</scr<script>ipt>', 'alert(1)'),
    ('a<em></em>\u0301', '\u00e1'),
    ('a\u200b\u0301', '\u00e1'),
    ('api_<b>key</b>=opaque-credential', 'api_key=[redacted]'),
    ('token\u200b=opaque-credential', 'token=[redacted]'),
    ('/ho<b>me</b>/estimator/project', '~/project'),
    ('some<b>one</b>@example.com', '[email]'),
])
def test_build_reaches_a_fixed_point_in_every_text_field(raw, expected):
    out = fp.build_payload(product="bidmanager", kind="bug", title=raw, body=raw,
                           context={"details": raw, "nested": [raw]})
    assert out["title"] == expected
    assert out["body"] == expected
    assert out["context"] == {"details": expected, "nested": [expected]}
    assert fp.build_payload(**out) == out
    assert fp.check_payload(out) == []


def test_sanitize_markdown_is_stable_without_scrubbing():
    raw = '<scr<script>ipt>a<em></em>\u0301</scr<script>ipt>'
    clean = fp.sanitize_markdown(raw, field="body", limit=100)
    assert clean == '\u00e1'
    assert fp.sanitize_markdown(clean, field="body", limit=100) == clean


def test_title_scrubs_credentials_exposed_by_collapsing_whitespace():
    out = fp.build_payload(product="bidmanager", kind="bug",
                           title='password="first\nsecond"', body="Request failed")
    assert out["title"] == 'password="[redacted]"'
    assert fp.check_payload(out) == []


def test_scrub_runs_on_body_title_and_context_strings():
    out = fp.build_payload(
        product="bidmanager", kind="bug", title="Fails for someone@example.com",
        body="Ran from /ho" "me/estimator/bids: token=abc123",
        context={"cli_command": r"C:\Users\estimator\est-import x.xlsx", "nested": ["/Us" "ers/estimator/y"]},
    )
    assert out["title"] == "Fails for [email]"
    assert out["body"] == "Ran from ~/bids: token=[redacted]"
    assert out["context"] == {"cli_command": r"~\est-import x.xlsx", "nested": ["~/y"]}


@pytest.mark.parametrize("kwargs,message", [
    (dict(product="nope", kind="bug", title="T", body="B"), "product must be one of"),
    (dict(product="bidmanager", kind="nope", title="T", body="B"), "kind must be one of"),
    (dict(product="bidmanager", kind="bug", title="", body="B"), "title is required"),
    (dict(product="bidmanager", kind="bug", title="T", body="<p></p>"), "body is required"),
    (dict(product="bidmanager", kind="bug", title="t" * 256, body="B"), "title is too long"),
    (dict(product="bidmanager", kind="bug", title="T", body="x" * 20_001), "body is too long"),
    (dict(product="bidmanager", kind="bug", title="T", body="B", context=["x"]),
     "context must be a JSON object"),
    (dict(product="bidmanager", kind="bug", title="T", body="B",
          context={"a": {"b": {"c": {"d": {"e": 1}}}}}), "nested too deeply"),
    (dict(product="bidmanager", kind="bug", title="T", body="B",
          context={"error_excerpt": "x" * 4_001}), "context.error_excerpt is too long"),
    (dict(product="bidmanager", kind="bug", title="T", body="B",
          context={f"k{i}": "y" * 3_000 for i in range(8)}), "context is too large"),
    (dict(product="bidmanager", kind="bug", title="T", body="B", context={"when": object()}),
     "unsupported type"),
])
def test_build_refuses_with_a_reason(kwargs, message):
    with pytest.raises(fp.PayloadError, match=message):
        fp.build_payload(**kwargs)


def test_check_payload_names_what_is_wrong():
    assert fp.check_payload("nope") == ["payload must be a JSON object, not str."]
    assert fp.check_payload({"product": "bidmanager"}) == [
        "missing field(s): kind, title, body, context."]
    assert fp.check_payload({"product": "bidmanager", "kind": "bug", "title": "T", "body": "B",
                             "context": {}, "status": "fixed"}) == [
        "unexpected field(s): status."]
    dirty = {"product": "bidmanager", "kind": "bug", "title": "T", "body": "<b>B</b>",
             "context": {"os": "mac\u200b"}}
    assert fp.check_payload(dirty) == [
        "body is not sanitized: rebuilding it changes it.",
        "context is not sanitized: rebuilding it changes it.",
    ]
    assert fp.check_payload({"product": "x", "kind": "bug", "title": "T", "body": "B",
                             "context": {}}) == ["product must be one of estimating-plugin, bidmanager; got 'x'."]


def test_context_round_trips_through_json():
    out = fp.build_payload(product="bidmanager", kind="bug", title="T", body="B",
                           context={"n": 1.5, "flags": [True, None]})
    assert json.loads(json.dumps(out["context"])) == out["context"]
