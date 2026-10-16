"""The xlsx determinism helpers, independent of any workbook generator."""
from __future__ import annotations

import zipfile
from datetime import datetime

import openpyxl
import pytest

from estimating_tools.xlsx_determinism import BUILD_STAMP, normalize_xlsx


def _write(path, value):
    wb = openpyxl.Workbook()
    wb.properties.created = wb.properties.modified = BUILD_STAMP
    wb.active["A1"] = value
    wb.save(path)
    normalize_xlsx(path)


def test_build_stamp_is_a_fixed_datetime():
    assert isinstance(BUILD_STAMP, datetime)


def test_same_content_is_byte_identical(tmp_path):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    _write(a, "hello")
    _write(b, "hello")
    assert a.read_bytes() == b.read_bytes()


def test_different_content_differs(tmp_path):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    _write(a, "hello")
    _write(b, "goodbye")
    assert a.read_bytes() != b.read_bytes()


def test_every_zip_member_carries_the_pinned_timestamp(tmp_path):
    path = tmp_path / "a.xlsx"
    _write(path, "hello")
    expected = BUILD_STAMP.timetuple()[:6]
    for info in zipfile.ZipFile(path).infolist():
        assert info.date_time == expected, f"{info.filename} has {info.date_time}"


def test_cip_alias_still_points_at_the_same_stamp():
    """cip.py kept CIP_BUILD_STAMP as an alias; it must not drift."""
    from estimating_tools.estimate_spec import cip
    assert cip.CIP_BUILD_STAMP is BUILD_STAMP
