import json

import pytest

from estimating_tools.feedback import cli


def test_build_prints_a_sanitized_payload(capsys, tmp_path):
    err = tmp_path / "err.txt"
    err.write_text("\n".join(f"frame {i} in /ho" "me/estimator/x.py" for i in range(60))
                   + "\nValueError: token=abc\n")
    rc = cli.main([
        "build", "--product", "estimating-plugin", "--kind", "bug",
        "--title", "<b>Crash</b> on push",
        "--body", "It <script>x</script>crashed in /Us" "ers/estimator/bids.\r\n\r\n\r\n**Steps**",
        "--plugin-version", "0.1.87", "--os", "macOS 15", "--skill", "push-takeoff",
        "--cli-command", r"C:\Users\estimator\est-import x.xlsx",
        "--error-file", str(err), "--error-lines", "5",
        "--context", "retries=3", "--context", "flag=true", "--context", "note=plain text",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Crash on push"
    assert payload["body"] == "It xcrashed in ~/bids.\n\n**Steps**"
    ctx = payload["context"]
    assert ctx["plugin_version"] == "0.1.87"
    assert ctx["os"] == "macOS 15"
    assert ctx["skill"] == "push-takeoff"
    assert ctx["cli_command"] == r"~\est-import x.xlsx"
    assert ctx["retries"] == 3 and ctx["flag"] is True and ctx["note"] == "plain text"
    excerpt = ctx["error_excerpt"]
    assert excerpt.startswith("... (56 earlier lines trimmed)")
    assert "/ho" "me/estimator" not in excerpt and "~/x.py" in excerpt
    assert excerpt.endswith("ValueError: token=[redacted]")
    # What build prints is what check accepts.
    out = tmp_path / "p.json"
    out.write_text(json.dumps(payload))
    assert cli.main(["check", str(out)]) == 0


def test_build_writes_with_out_and_reads_body_file(capsys, tmp_path):
    body = tmp_path / "body.md"
    body.write_text("Please add **dark mode**.\n")
    out = tmp_path / "feedback-draft-2026-10-17.json"
    rc = cli.main(["build", "--product", "bidmanager", "--kind", "feature-request",
                   "--title", "Dark mode", "--body-file", str(body), "--out", str(out)])
    assert rc == 0
    assert "WROTE:" in capsys.readouterr().out
    assert json.loads(out.read_text())["body"] == "Please add **dark mode**."


def test_repeated_build_keeps_the_existing_draft(capsys, tmp_path):
    out = tmp_path / "feedback-draft-2026-10-17.json"
    args = ["build", "--product", "bidmanager", "--kind", "bug", "--body", "Failed"]
    assert cli.main([*args, "--title", "First report", "--out", str(out)]) == 0
    original = out.read_bytes()
    capsys.readouterr()
    assert cli.main([*args, "--title", "Second report", "--out", str(out)]) == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "choose a new filename" in captured.err
    assert "WROTE:" not in captured.out
    assert out.read_bytes() == original
    assert cli.main([*args, "--title", "Third report", "--out", str(out)]) == 1
    assert out.read_bytes() == original
    assert cli.main([*args, "--title", "Second report", "--out",
                     str(tmp_path / "feedback-draft-second.json")]) == 0


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity", "1e999", '{"values":[NaN]}'])
def test_build_refuses_non_finite_context_numbers(capsys, tmp_path, raw):
    out = tmp_path / "feedback-draft.json"
    assert cli.main(["build", "--product", "bidmanager", "--kind", "bug", "--title", "T",
                     "--body", "B", "--context", f"elapsed={raw}", "--out", str(out)]) == 1
    captured = capsys.readouterr()
    assert "context.elapsed" in captured.err
    assert "must be a finite number" in captured.err
    assert not captured.out
    assert not out.exists()


def test_check_and_drafts_refuse_non_finite_context_numbers(capsys, tmp_path):
    draft = tmp_path / "feedback-draft-invalid.json"
    draft.write_text('{"product":"bidmanager","kind":"bug","title":"T","body":"B",'
                     '"context":{"elapsed":NaN}}')
    assert cli.main(["check", str(draft)]) == 1
    assert "context.elapsed must be a finite number" in capsys.readouterr().err
    assert cli.main(["drafts", str(tmp_path)]) == 1
    assert "NEEDS REBUILD" in capsys.readouterr().out


def test_build_redacts_credentials_and_writes_a_checkable_payload(capsys, tmp_path):
    error = tmp_path / "error.txt"
    # utf-8 explicitly: the CLI reads UTF-8, and the platform default (cp1252
    # on Windows) cannot even write the zero-width space below
    error.write_text('{"password": "hunter2"}\ntoken\u200b=opaque-credential\n', encoding="utf-8")
    out = tmp_path / "feedback-draft.json"
    assert cli.main([
        "build", "--product", "bidmanager", "--kind", "bug", "--title", "Crash",
        "--body", '<scr<script>ipt>Failed</scr<script>ipt> PASSWORD="hunter2"',
        "--context", "password=hunter2",
        "--context", 'request={"access_token":"opaque-credential","attempt":1}',
        "--error-file", str(error), "--out", str(out),
    ]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["body"] == 'Failed PASSWORD="[redacted]"'
    assert payload["context"] == {
        "password": "[redacted]",
        "request": {"access_token": "[redacted]", "attempt": 1},
        "error_excerpt": '{"password": "[redacted]"}\ntoken=[redacted]',
    }
    assert "hunter2" not in out.read_text(encoding="utf-8")
    assert "opaque-credential" not in out.read_text(encoding="utf-8")
    assert cli.main(["check", str(out)]) == 0
    assert "OK:" in capsys.readouterr().out


def test_build_to_stdout_survives_a_console_that_is_not_utf8():
    """Without --out the payload goes to stdout. A Windows console is often
    cp1252, which cannot encode e.g. "≥"; printing must not crash there, and
    what is printed must still be the same JSON."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run(
        [sys.executable, "-m", "estimating_tools.feedback.cli", "build",
         "--product", "bidmanager", "--kind", "bug",
         "--title", "Slope ≥ 2%", "--body", "Fails ≥ 3 tries"],
        capture_output=True, env=env)
    assert proc.returncode == 0, proc.stderr.decode("cp1252", "replace")
    payload = json.loads(proc.stdout.decode("cp1252"))
    assert payload["title"] == "Slope ≥ 2%"


def test_build_refuses_a_bad_field(capsys):
    rc = cli.main(["build", "--product", "bidmanager", "--kind", "bug",
                   "--title", "T", "--body", "x" * 20_001])
    assert rc == 1
    assert "body is too long" in capsys.readouterr().err


def test_build_reports_a_missing_file(capsys, tmp_path):
    rc = cli.main(["build", "--product", "bidmanager", "--kind", "bug",
                   "--title", "T", "--body-file", str(tmp_path / "nope.md")])
    assert rc == 1
    assert "no such file" in capsys.readouterr().err


def test_check_fails_an_unsanitized_payload(capsys, tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"product": "bidmanager", "kind": "bug", "title": "T",
                             "body": "<b>raw</b>", "context": {}, "status": "fixed"}))
    assert cli.main(["check", str(p)]) == 1
    assert "unexpected field(s): status" in capsys.readouterr().err
    p.write_text("{not json")
    assert cli.main(["check", str(p)]) == 1
    assert "not JSON" in capsys.readouterr().err


def test_drafts_lists_each_file_with_its_state(capsys, tmp_path):
    good = {"product": "bidmanager", "kind": "bug", "title": "T", "body": "B", "context": {}}
    (tmp_path / "feedback-draft-2026-10-01.json").write_text(json.dumps(good))
    (tmp_path / "feedback-draft-2026-10-02.json").write_text(
        json.dumps({**good, "body": "<i>x</i>"}))
    (tmp_path / "unrelated.json").write_text("{}")
    rc = cli.main(["drafts", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "feedback-draft-2026-10-01.json: ready" in out
    assert "feedback-draft-2026-10-02.json: NEEDS REBUILD -- body is not sanitized" in out
    assert "unrelated" not in out


def test_drafts_with_none_is_fine(capsys, tmp_path):
    assert cli.main(["drafts", str(tmp_path)]) == 0
    assert "no feedback-draft-*.json" in capsys.readouterr().out
