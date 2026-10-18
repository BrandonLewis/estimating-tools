"""Load and save a spec so that `read-back --write` keeps what the estimator wrote.

ruamel.yaml's round-trip mode (`typ="rt"`) loads mappings and sequences that
carry their comments, key order, quoting and flow/block style; `merge` edits
them in place, and `SpecYaml.dumps` writes them back. A spec that read-back
did not touch is never rewritten at all (the CLI writes only on a change), and
an unchanged block-style spec dumps byte for byte. What is not kept is
whitespace ruamel normalises when it re-emits the file: inside and before a
one-line `{ ... }` or `[ ... ]`, padding and column alignment go
(`overhead:  { labor: 0.12,  equipment: 0.1 }` comes back
`overhead: {labor: 0.12, equipment: 0.1}`), and blank lines between the rows
of a list can move or disappear where rows were added or deleted. Keys,
values, order, quoting and comments are kept.

**YAML 1.1 vs 1.2.** `build` reads a spec with PyYAML, which speaks YAML 1.1:
a plain `no`, `Off` or `yes` is a bool there and a plain `1:30` the base-60
int 90. ruamel.yaml speaks YAML 1.2, where all of those are strings. So both
directions are pinned to PyYAML's reading:

* loading -- the text is read by both; wherever a scalar reads differently,
  the round-trip tree takes PyYAML's value (so `includes_operator: no` is
  `False` to read-back, exactly as to `build`); a difference that cannot be
  patched (a mapping key such as `yes:`) refuses the spec (`SpecYamlError`);
* dumping -- a string PyYAML would not read back as that same string when
  written plain (`Yes`, `Off`, `1:30`, `~`, `null`) is double-quoted, and
  the dumped text is checked with `yaml.safe_load` against the spec it was
  dumped from; any difference refuses the write.

Only the CLI needs this module (ruamel.yaml is in the `estimate_spec`,
`plugin-core` and `all` extras); `read_back` itself works on any mapping.
"""
from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import date, datetime

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.util import load_yaml_guess_indent

_STR = "tag:yaml.org,2002:str"
_PYYAML_RESOLVER = yaml.resolver.Resolver()


class SpecYamlError(ValueError):
    """The spec cannot be read, or written, the way `build` (PyYAML) reads it."""


def yaml11_reads_as_str(text: str) -> bool:
    """Would PyYAML (YAML 1.1, what `build` uses) read `text`, written as a
    plain scalar, back as that string?"""
    return _PYYAML_RESOLVER.resolve(yaml.nodes.ScalarNode, text, (True, False)) == _STR


class _SpecRepresenter(RoundTripRepresenter):
    """ruamel's round-trip representer, but a plain string YAML 1.1 would
    misread is double-quoted."""


def _represent_str(self, data):
    if not yaml11_reads_as_str(data):
        return self.represent_scalar(_STR, data, style='"')
    return RoundTripRepresenter.represent_str(self, data)


# A subclass, so ruamel's own RoundTripRepresenter (process-wide) is untouched.
_SpecRepresenter.add_representer(str, _represent_str)


def _kind(v) -> str:
    """A value's YAML data kind -- bool, int and float kept apart (Python's
    `True == 1` must not pass for "the same data")."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, datetime):
        return "datetime"
    if isinstance(v, date):
        return "date"
    if isinstance(v, Mapping):
        return "map"
    if isinstance(v, list):
        return "seq"
    return type(v).__name__


def _key_index(m: Mapping) -> dict:
    return {(_kind(k), k): k for k in m}


def same_data(a, b) -> bool:
    """Do `a` and `b` hold the same YAML data (kinds included)?"""
    ka = _kind(a)
    if ka != _kind(b):
        return False
    if ka == "map":
        index = _key_index(b)
        return len(a) == len(b) and all(
            (_kind(k), k) in index and same_data(a[k], b[index[(_kind(k), k)]]) for k in a)
    if ka == "seq":
        return len(a) == len(b) and all(same_data(x, y) for x, y in zip(a, b))
    return a == b


def _where(path: list) -> str:
    return "$" + "".join(f"[{p!r}]" for p in path) if path else "the top level"


def _reconcile(rt, py, path: list, seen: set):
    """`rt` (ruamel's YAML 1.2 reading) with every scalar PyYAML reads
    differently replaced by PyYAML's value, in place; returns the value to
    keep at this position."""
    kr, kp = _kind(rt), _kind(py)
    if kr == kp == "map":
        if id(rt) in seen:
            return rt
        seen.add(id(rt))
        index = _key_index(py)
        if len(rt) != len(py) or any((_kind(k), k) not in index for k in rt):
            raise SpecYamlError(
                f"at {_where(path)}, the keys {sorted(map(str, rt))} read differently in YAML "
                f"1.1, which build uses ({sorted(map(str, py))}) -- quote the key")
        for k in list(rt):
            new = _reconcile(rt[k], py[index[(_kind(k), k)]], path + [k], seen)
            if new is not rt[k]:
                rt[k] = new
        return rt
    if kr == kp == "seq":
        if id(rt) in seen:
            return rt
        seen.add(id(rt))
        if len(rt) != len(py):
            raise SpecYamlError(f"at {_where(path)}, the list reads differently in YAML 1.1")
        for i, (x, y) in enumerate(zip(rt, py)):
            new = _reconcile(x, y, path + [i], seen)
            if new is not x:
                rt[i] = new
        return rt
    if kr == kp and rt == py:
        return rt
    if "map" in (kr, kp) or "seq" in (kr, kp):
        raise SpecYamlError(f"at {_where(path)}, the value reads differently in YAML 1.1")
    return py          # a scalar YAML 1.1 reads otherwise (`no`, `1:30`): build's reading


class SpecYaml:
    """A spec loaded for round-trip editing: edit `spec` in place, then `dumps()`.

    `spec` holds exactly the data `build` reads from the same text (PyYAML,
    YAML 1.1) -- see the module docstring. Raises SpecYamlError when that
    cannot be arranged."""

    def __init__(self, text: str):
        # The file's own sequence indentation (`items:\n  - recipe` vs
        # `items:\n- recipe`), so an unchanged block is written back as it was.
        _, indent, dash_offset = load_yaml_guess_indent(text)
        self._yaml = YAML(typ="rt")
        self._yaml.Representer = _SpecRepresenter
        self._yaml.preserve_quotes = True
        self._yaml.width = 4096                 # never re-wrap a long line
        self._yaml.indent(mapping=2, sequence=indent or 2, offset=dash_offset or 0)
        loaded = self._yaml.load(text)
        try:
            as_built = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecYamlError(f"PyYAML, which build uses, cannot read it: {exc}") from None
        self.spec = _reconcile(loaded, as_built, [], set())
        if not same_data(self.spec, as_built):       # belt and braces
            raise SpecYamlError("it reads differently in YAML 1.1, which build uses")

    def _dump_text(self, spec) -> str:
        out = io.StringIO()
        self._yaml.dump(spec, out)
        return out.getvalue()

    def dumps(self, spec=None) -> str:
        """`spec` (default: the loaded one, as edited) as YAML text -- refused
        (SpecYamlError) unless PyYAML reads that text back as `spec`."""
        spec = self.spec if spec is None else spec
        text = self._dump_text(spec)
        if not same_data(yaml.safe_load(text), spec):
            raise SpecYamlError(
                "the updated spec would read back differently in YAML 1.1, which build "
                "uses -- nothing written (please report this)")
        return text
