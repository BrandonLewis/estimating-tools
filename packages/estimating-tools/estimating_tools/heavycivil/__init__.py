"""Compatibility shim: ``estimating_tools.heavycivil`` is
``estimating_tools.heavybook`` (renamed 2026-10-31). Removed one release
after the rename ships. Importing any submodule here imports the heavybook
one and registers it under both names."""
from __future__ import annotations

import importlib
import pkgutil
import sys
import warnings

_NEW = "estimating_tools.heavybook"
warnings.warn("estimating_tools.heavycivil is now estimating_tools.heavybook",
              DeprecationWarning, stacklevel=2)
_pkg = importlib.import_module(_NEW)
globals().update({k: v for k, v in vars(_pkg).items() if not k.startswith("__")})
__path__ = list(_pkg.__path__)  # lets ``import estimating_tools.heavycivil.columns`` find the files

# Eager on purpose: lazy aliasing would bring back duplicate module objects through ``__path__``.
for _m in pkgutil.walk_packages(_pkg.__path__, f"{_NEW}."):
    if _m.name == f"{_NEW}.tests" or f"{_NEW}.tests." in _m.name:
        continue
    _rel = _m.name[len(_NEW) + 1:]
    sys.modules[f"estimating_tools.heavycivil.{_rel}"] = importlib.import_module(_m.name)


def __getattr__(name):
    return getattr(_pkg, name)
