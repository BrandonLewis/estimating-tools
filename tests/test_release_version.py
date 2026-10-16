import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release_version.py"
PY = sys.executable


def _current_version() -> str:
    pp = (ROOT / "packages/estimating-tools/pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pp, re.M)
    assert m is not None, "could not find the version line in pyproject.toml"
    return m.group(1)


def _run(ref_name: str):
    env = {**os.environ, "GITHUB_REF_NAME": ref_name}
    return subprocess.run(
        [PY, str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30
    )


def test_matching_tag_passes():
    r = _run(f"v{_current_version()}")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "version consistency OK" in r.stdout


def test_mismatched_tag_fails_and_lists_files():
    r = _run("v9.9.9")
    assert r.returncode != 0
    assert "pyproject.toml" in r.stdout            # names the offending file(s)
    assert "9.9.9" in r.stdout
