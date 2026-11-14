import json, shutil, subprocess, sys, tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/build_perplexity_plugins.py"
CFG = json.loads((ROOT / "perplexity/bundles.json").read_text())


# Build outside pytest's basetemp: bundles are real plugins (plugin.json +
# dist/*.whl), and plugin_runtime's sibling-plugin wheel glob would find them
# from other tests' temp plugin roots (test_plugin_runtime / test_ensure_tools).
@pytest.fixture
def isolated_out():
    d = Path(tempfile.mkdtemp(prefix="pplx-build-"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="module")
def built():
    out = Path(tempfile.mkdtemp(prefix="pplx-build-"))
    r = subprocess.run([sys.executable, str(SCRIPT), "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    yield out
    shutil.rmtree(out, ignore_errors=True)


@pytest.mark.parametrize("bundle", list(CFG["bundles"]))
def test_bundle_layout(built, bundle):
    spec, d = CFG["bundles"][bundle], built / bundle
    assert (d / ".claude-plugin/plugin.json").is_file()
    assert (built / f"{bundle}.zip").is_file()
    assert not (d / "docs").exists() and not (d / "CHANGELOG.md").exists()
    assert sorted(p.name for p in (d / "skills").iterdir()) == sorted(spec["skills"])
    for x in CFG["excluded"]:
        assert not (d / "skills" / x).exists()
    for a in spec["agents"]:
        assert (d / "agents" / Path(a).name).is_file()
    mcp = json.loads((d / ".mcp.json").read_text())
    assert mcp and all(v["url"].startswith("https://") for v in mcp.values())  # no stdio


def run_with(out, mutate):
    cfg = json.loads(json.dumps(CFG)); mutate(cfg)
    p = out / "bundles.json"; p.write_text(json.dumps(cfg))
    return subprocess.run([sys.executable, str(SCRIPT), "--out", str(out / "o"), "--config", str(p)],
                          capture_output=True, text=True)


def test_unassigned_skill_fails(isolated_out):
    r = run_with(isolated_out, lambda c: c["bundles"]["estimating-buyout"]["skills"].remove("draft-an-rfi"))
    assert r.returncode == 1 and "draft-an-rfi" in r.stdout


def test_missing_agent_is_a_clean_error(isolated_out):
    r = run_with(isolated_out, lambda c: c["bundles"]["estimating-buyout"]["agents"].append("nope/agents/x.md"))
    assert r.returncode == 1 and "ERROR:" in r.stdout and "Traceback" not in r.stderr


def test_text_size_limit_enforced(isolated_out):
    r = run_with(isolated_out, lambda c: c["limits"].update(max_text_file_bytes=1000))
    assert r.returncode == 1 and "text file too large" in r.stdout
