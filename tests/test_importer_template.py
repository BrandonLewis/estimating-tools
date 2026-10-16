import importlib.util
from pathlib import Path

from estimating_tools.importers.model import CanonicalEstimate
from estimating_tools.importers.registry import Importer

ROOT = Path(__file__).resolve().parents[1]
TMPL = ROOT / "templates" / "importer" / "importer.py"


def _load_template_module():
    spec = importlib.util.spec_from_file_location("_tmpl_importer", TMPL)
    assert spec is not None and spec.loader is not None, f"could not load template module from {TMPL}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_template_defines_a_conforming_importer():
    mod = _load_template_module()
    imp = mod.ExampleImporter()
    assert isinstance(imp, Importer)          # satisfies the runtime-checkable protocol
    assert isinstance(imp.name, str) and imp.name
    # parse returns a CanonicalEstimate (the template returns a tiny stub)
    out = imp.parse(Path("ignored"))
    assert isinstance(out, CanonicalEstimate)
