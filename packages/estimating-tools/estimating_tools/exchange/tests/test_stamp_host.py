"""The host a build stamps (``exchange.stamp.bare_host``): the engine's, so a
template pack's build imports no pack; HeavyBook re-exports it."""
from __future__ import annotations

import pytest

from estimating_tools.exchange import stamp


@pytest.mark.parametrize("given, want", [
    ("", "www.bidsheet.ai"), ("  ", "www.bidsheet.ai"), ("www.x.ai", "www.x.ai"),
    ("HTTPS://WWW.X.ai/a?q#f", "www.x.ai"), ("https://x.ai:8443/p", "x.ai:8443"),
])
def test_a_host_is_reduced_to_its_bare_lowercase_name(given, want):
    assert stamp.bare_host(given) == want


def test_a_scheme_other_than_https_is_refused():
    with pytest.raises(ValueError, match="must be https"):
        stamp.bare_host("http://x.ai")


def test_heavybook_re_exports_it():
    from estimating_tools.heavybook import pack as hb_pack

    assert hb_pack.bare_host is stamp.bare_host and hb_pack.DEFAULT_HOST == stamp.DEFAULT_HOST
