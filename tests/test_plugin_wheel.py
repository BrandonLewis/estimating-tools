"""Tests for the bundled plugin wheel: extras contract + build-script compare logic."""
from pathlib import Path

import pytest

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - 3.10 CI leg
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "packages" / "estimating-tools" / "pyproject.toml"

import sys

sys.path.insert(0, str(ROOT / "scripts"))
from build_plugin_wheel import diff_wheels  # noqa: E402


@pytest.mark.skipif(tomllib is None, reason="tomllib requires Python 3.11+")
def test_plugin_core_extra_matches_skill_dependency_union():
    """plugin-core = what estimating-core skills import + the bundled MCP server's runtime ("mcp")."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    # mcp is pinned to the 2.x majors: the artifact-editor server was migrated to
    # the 2.x low-level request-handler API (#184) so estimating-tools no longer
    # downgrades mcp in the shared BidSheet.ai venv (which needs mcp>=2).
    # ruamel.yaml: build-estimate-workbook's read-back flow runs
    # `est-estimate read-back --write`, which rewrites the spec round-trip.
    assert set(extras["plugin-core"]) == {
        "openpyxl", "jsonschema", "pdfplumber", "mcp>=2,<3", "ruamel.yaml>=0.18,<0.20"
    }


import zipfile


def _make_wheel(tmp_path, filename, files, date_time=(2026, 1, 1, 0, 0, 0)):
    """files: {archive_name: text}. date_time varies to prove timestamp insensitivity."""
    path = tmp_path / filename
    with zipfile.ZipFile(path, "w") as zf:
        for arcname, text in files.items():
            info = zipfile.ZipInfo(arcname, date_time=date_time)
            zf.writestr(info, text)
    return path


BASE = {
    "estimating_tools/__init__.py": "print('hi')\n",
    "estimating_tools/importers/mapping_artifact.py": "X = 1\n",
    "estimating_tools-0.1.2.dist-info/METADATA": (
        "Metadata-Version: 2.4\nName: estimating_tools\nVersion: 0.1.2\n"
        "Requires-Python: >=3.10\n"
        "Requires-Dist: pyyaml\nProvides-Extra: plugin-core\nGenerator: bdist_wheel 1.0\n"
    ),
    "estimating_tools-0.1.2.dist-info/entry_points.txt": "[console_scripts]\nest-import = x:main\n",
    "estimating_tools-0.1.2.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: something-volatile\n",
    "estimating_tools-0.1.2.dist-info/RECORD": "volatile,hashes,here\n",
}


def test_diff_wheels_ignores_timestamps_and_volatile_metadata(tmp_path):
    a = _make_wheel(tmp_path, "a.whl", BASE, date_time=(2026, 1, 1, 0, 0, 0))
    changed = dict(BASE)
    changed["estimating_tools-0.1.2.dist-info/WHEEL"] = "Wheel-Version: 1.0\nGenerator: other\n"
    changed["estimating_tools-0.1.2.dist-info/RECORD"] = "different,volatile,lines\n"
    b = _make_wheel(tmp_path, "b.whl", changed, date_time=(2026, 7, 11, 12, 30, 0))
    assert diff_wheels(a, b) == []


def test_diff_wheels_flags_code_entrypoint_and_deps_changes(tmp_path):
    a = _make_wheel(tmp_path, "a.whl", BASE)
    changed = dict(BASE)
    changed["estimating_tools/importers/mapping_artifact.py"] = "X = 2\n"
    changed["estimating_tools/newmod.py"] = "Y = 1\n"
    changed["estimating_tools-0.1.2.dist-info/entry_points.txt"] = (
        "[console_scripts]\nest-import = x:main\nest-new = y:main\n"
    )
    changed["estimating_tools-0.1.2.dist-info/METADATA"] = (
        "Metadata-Version: 2.4\nName: estimating_tools\nVersion: 0.1.2\n"
        "Requires-Python: >=3.12\n"
        "Requires-Dist: pyyaml\nRequires-Dist: extradep\nProvides-Extra: plugin-core\n"
    )
    b = _make_wheel(tmp_path, "b.whl", changed)
    diffs = diff_wheels(a, b)
    assert any("mapping_artifact.py" in d for d in diffs)
    assert any("newmod.py" in d for d in diffs)
    assert any("entry_points" in d for d in diffs)
    assert any("METADATA" in d for d in diffs)


def test_diff_wheels_flags_requires_python_change(tmp_path):
    a = _make_wheel(tmp_path, "a.whl", BASE)
    changed = dict(BASE)
    changed["estimating_tools-0.1.2.dist-info/METADATA"] = BASE[
        "estimating_tools-0.1.2.dist-info/METADATA"
    ].replace("Requires-Python: >=3.10", "Requires-Python: >=3.12")
    b = _make_wheel(tmp_path, "b.whl", changed)
    diffs = diff_wheels(a, b)
    assert any("METADATA" in d for d in diffs)


def test_diff_wheels_flags_unexpected_toplevel_member(tmp_path):
    a = _make_wheel(tmp_path, "a.whl", BASE)
    changed = dict(BASE)
    changed["rogue_pkg/__init__.py"] = "Z = 1\n"
    b = _make_wheel(tmp_path, "b.whl", changed)
    diffs = diff_wheels(a, b)
    assert any("rogue_pkg/__init__.py" in d for d in diffs)


def test_diff_wheels_ignores_line_ending_differences(tmp_path):
    a_files = dict(BASE)
    a_files["estimating_tools/importers/mapping_artifact.py"] = "X = 1\r\n"
    a = _make_wheel(tmp_path, "a.whl", a_files)
    b_files = dict(BASE)
    b_files["estimating_tools/importers/mapping_artifact.py"] = "X = 1\n"
    b = _make_wheel(tmp_path, "b.whl", b_files)
    assert diff_wheels(a, b) == []


def test_diff_wheels_ignores_zip_directory_entries(tmp_path):
    a = _make_wheel(tmp_path, "a.whl", BASE)
    changed = dict(BASE)
    changed["estimating_tools/"] = ""
    changed["estimating_tools/importers/"] = ""
    b = _make_wheel(tmp_path, "b.whl", changed)
    assert diff_wheels(a, b) == []


def test_diff_wheels_ignores_nonkept_metadata_lines(tmp_path):
    a = _make_wheel(tmp_path, "a.whl", BASE)
    changed = dict(BASE)
    changed["estimating_tools-0.1.2.dist-info/METADATA"] = BASE[
        "estimating_tools-0.1.2.dist-info/METADATA"
    ].replace("Metadata-Version: 2.4", "Metadata-Version: 2.5")
    b = _make_wheel(tmp_path, "b.whl", changed)
    assert diff_wheels(a, b) == []
