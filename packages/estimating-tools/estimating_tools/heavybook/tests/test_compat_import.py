"""The package is ``heavybook``; ``heavycivil`` is a one-release shim that
resolves to the same modules and warns."""
from __future__ import annotations

import importlib
import pkgutil
import sys
import warnings


def test_heavybook_is_the_package():
    import estimating_tools.heavybook as hb
    assert hb.FORMAT_NAME == "heavybook"
    assert "heavycivil" in hb.ACCEPTED_FORMATS and "heavybook" in hb.ACCEPTED_FORMATS


def test_heavycivil_shim_resolves_submodules_and_warns():
    for name in list(sys.modules):
        if name.startswith("estimating_tools.heavycivil"):
            del sys.modules[name]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # An import statement, not importlib.import_module: stacklevel=2 must land on the caller.
        import estimating_tools.heavycivil.columns as old
    import estimating_tools.heavybook.columns as new
    assert old.CR is new.CR
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert any(w.filename == __file__ for w in caught if issubclass(w.category, DeprecationWarning))


def test_every_heavybook_submodule_is_aliased_to_the_same_object():
    import estimating_tools.heavybook as hb
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        importlib.import_module("estimating_tools.heavycivil")
    rels = [m.name[len("estimating_tools.heavybook."):]
            for m in pkgutil.walk_packages(hb.__path__, "estimating_tools.heavybook.")
            if m.name != "estimating_tools.heavybook.tests"
            and not m.name.startswith("estimating_tools.heavybook.tests.")]
    assert rels
    for rel in rels:
        old = importlib.import_module("estimating_tools.heavycivil." + rel)
        new = importlib.import_module("estimating_tools.heavybook." + rel)
        assert old is new, rel
