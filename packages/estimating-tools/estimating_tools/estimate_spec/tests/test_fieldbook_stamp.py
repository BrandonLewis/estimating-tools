"""A fieldbook book built from the read model carries the exchange stamp
(contract part 5): detection property, stamp JSON, baseline chunks; a book
built from a spec carries the legacy stamp only."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from estimating_tools.estimate_spec import build as B
from estimating_tools.estimate_spec import identity
from estimating_tools.estimate_spec.tests import _exchange as X
from estimating_tools.estimate_spec.tests._fieldbook import build, fieldbook_pack
from estimating_tools.exchange import baseline
from estimating_tools.exchange import stamp as exchange_stamp


def _props(wb):
    return {p.name: p.value for p in wb.custom_doc_props.props}


def test_the_book_carries_the_exchange_stamp():
    wb = X.generate()
    ws = wb[exchange_stamp.SHEET]
    assert ws.sheet_state == "hidden"
    stamp = exchange_stamp.parse(json.loads(ws["A1"].value))
    assert (stamp.pack["name"], stamp.contract, stamp.estimate_id) == ("fieldbook", "1", 1)
    assert stamp.declaration["kinds"] == {"TASK": "ACTIVITY", "CREW": "RESOURCE",
                                          "LINE": "RESOURCE"}
    assert baseline.decode(exchange_stamp.chunks_of(ws), stamp.baseline) == X.payload()
    assert wb.defined_names[exchange_stamp.NAME].attr_text == "'_wb'!$A$1"
    props = _props(wb)
    assert props["estimate_format"] == "fieldbook 2"
    assert (props["estimate_id"], props["bidsheet_host"], props["exported_at"]) == (
        "1", X.HOST, X.EXPORTED_AT)
    assert "estimate_spec_sha" not in props
    assert "est.layout" in wb.defined_names


def test_a_spec_book_carries_no_exchange_stamp():
    wb = build()
    assert exchange_stamp.SHEET not in wb.sheetnames
    assert "estimate_spec_sha" in _props(wb)


def test_the_read_models_names_are_not_the_specs_to_check():
    """'Laborer (local)' is no seed trade: the spec schema would refuse it."""
    with pytest.raises(ValueError, match="schema violation"):
        B.generate(X.config(), fieldbook_pack())


def test_a_payload_the_model_refuses_is_refused():
    doc = X.payload()
    del doc["estimate"]
    with pytest.raises(ValueError):
        X.generate(doc=doc)


def test_only_a_stamped_build_takes_a_baseline():
    base = identity.Baseline(payload=X.payload(), host=X.HOST, exported_at=X.EXPORTED_AT)
    with pytest.raises(ValueError, match="a build from the read model is stamped"):
        B.generate(X.config(), fieldbook_pack(), stamp=False, exchange=base)


def test_the_export_time_defaults_to_now_in_utc():
    before = datetime.now(timezone.utc).replace(microsecond=0)
    stamped = identity.Baseline(payload=X.payload()).exported_at
    after = datetime.now(timezone.utc)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", stamped)
    when = datetime.strptime(stamped, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before <= when <= after
