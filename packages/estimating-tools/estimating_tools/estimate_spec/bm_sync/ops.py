"""The plan document the push and pull planners emit and the skill executes (stdlib only).

An ``Op`` names an MCP tool and its arguments. An argument value may be a placeholder
``{"$ref": "<op id>", "path": "$.id"}`` meaning "take this from that earlier op's result";
this module carries it unchanged and the skill resolves it. ``Entry`` rows are side notes
(conflicts, refusals, notices, reconciliations) the estimator reads before confirming.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from estimating_tools.artifacts import md_table

_counters: dict[str, int] = {}


def next_id(prefix: str) -> str:
    """The next op id for `prefix` (p1, p2, ...)."""
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}{_counters[prefix]}"


def reset_ids() -> None:
    _counters.clear()


@dataclass
class Op:
    id: str
    kind: str
    tool: str
    args: dict
    package: str
    note: str = ""
    # sidecar path -> result path ("$.id"), "+<x>" (append x) or, for a plugs_removed
    # path, the entry dict itself (appended as recorded)
    sidecar: dict[str, str | dict] = field(default_factory=dict)
    after: str | None = None


@dataclass
class Entry:
    kind: str  # conflict | refused | notice | reconcile
    package: str
    text: str


@dataclass
class Plan:
    direction: str  # push | pull
    spec: str
    ops: list[Op]
    entries: list[Entry]
    version: int = 1
    meta: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.ops and not any(e.kind in ("conflict", "refused") for e in self.entries)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Plan":
        d = json.loads(text)
        return cls(d["direction"], d["spec"], [Op(**o) for o in d["ops"]],
                   [Entry(**e) for e in d["entries"]], d.get("version", 1), d.get("meta", {}))


def _one_line(text: str) -> str:
    """`text` on one table row: line breaks shown as ⏎ (md_table escapes `|`)."""
    return text.replace("\r\n", "⏎").replace("\n", "⏎").replace("\r", "⏎")


def _value(v) -> str:
    if isinstance(v, dict) and "$ref" in v:
        path = str(v.get("path", ""))
        return f"{v['$ref']}.{path[2:] if path.startswith('$.') else path}"
    return _one_line(str(v))


def _detail(op: Op) -> str:
    return _one_line(op.note) if op.note else " ".join(f"{k}={_value(v)}" for k, v in op.args.items())


def render_plan(plan: Plan) -> str:
    """Markdown the estimator confirms: ops by package in plan order, then entries."""
    lines = [f"{plan.direction.capitalize()} plan: {len(plan.ops)} op(s), {len(plan.entries)} entr(ies)"]
    packages: dict[str, list[Op]] = {}
    for op in plan.ops:
        packages.setdefault(op.package, []).append(op)
    for package, ops in packages.items():
        rows = [(i, op.kind, op.tool, _detail(op)) for i, op in enumerate(ops, 1)]
        lines += ["", f"## {package}", "", md_table(["#", "op", "tool", "detail"], rows)]
    if plan.entries:
        lines += ["", "## Entries", ""]
        lines += [f"- {e.kind} {e.package}: {e.text}" for e in plan.entries]
    return "\n".join(lines) + "\n"
