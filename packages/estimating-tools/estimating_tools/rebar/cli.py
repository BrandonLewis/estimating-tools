"""est-rebar — bar bending schedule (BBS) + ACI development/lap length CLI.

  est-rebar schedule <bars.yaml> [--out-dir .] [--xlsx]
                      [--takeoff out.json --organization-id N
                       [--cost-code C] [--item-number I] [--schedule S]
                       [--project-ref R]]
  est-rebar develop --size 5 --fc 4000 [--fy 60000] [--top-bar] [--epoxy]
                     [--lightweight] [--lap A|B]

Bars YAML shape: ``{title, marks: [{mark, size, count, legs_in: [...],
hooks: [...], note}]}`` (``size`` is the bar number, e.g. ``5`` for #5) — see
``estimating_tools.rebar.schedule.BarMark``/``BarSchedule``.

Deterministic, stdlib + pyyaml only (openpyxl for ``--xlsx`` is the lazy
``excel`` extra). Every anticipated failure (missing/invalid YAML, an
unmapped/invalid marks list, a bad bar size/hook/duplicate mark, a bad splice
class, ``--takeoff`` without ``--organization-id``, missing openpyxl) prints
one clean line and returns 1 — the house style used by
``estimating_tools.intake.cli`` and friends. This tool is an ESTIMATING AID
(see ``rebar/detailing.py`` and ``rebar/develop.py`` docstrings); it is not a
design or detailing tool."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from estimating_tools.rebar.develop import development_length_in, lap_length_in
from estimating_tools.rebar.model import BarSize
from estimating_tools.rebar.schedule import BarMark, BarSchedule

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    return _SLUG_RE.sub("-", title.lower()).strip("-") or "schedule"


def _int_count(m: dict, label) -> int:
    raw = m.get("count", 1)
    if isinstance(raw, bool) or not (
        isinstance(raw, int) or (isinstance(raw, float) and raw.is_integer())
    ):
        raise ValueError(f"mark {label!r}: count must be a whole number, got {raw!r}")
    return int(raw)


def _build_schedule(data: dict) -> BarSchedule:
    """Parse a bars-YAML mapping into a BarSchedule. Raises ValueError on bad
    shape/values — callers print + rc 1."""
    marks_data = data.get("marks")
    if not isinstance(marks_data, list):
        raise ValueError("bars YAML must have a 'marks' list")

    marks = []
    for i, m in enumerate(marks_data):
        if not isinstance(m, dict):
            raise ValueError(f"mark at index {i} must be a mapping, got {type(m).__name__}")
        label = m.get("mark", f"index {i}")
        try:
            marks.append(BarMark(
                mark=m["mark"], size=BarSize(int(m["size"])), count=_int_count(m, label),
                legs_in=[float(x) for x in m["legs_in"]],
                hooks=list(m.get("hooks", [])), note=m.get("note", ""),
            ))
        except KeyError as exc:
            raise ValueError(f"mark {label!r}: missing required field {exc}") from exc
        except (ValueError, TypeError) as exc:
            msg = str(exc)
            raise ValueError(msg if msg.startswith(f"mark {label!r}") else f"mark {label!r}: {msg}") from exc
    return BarSchedule(title=data.get("title") or "Bar Schedule", marks=marks)


def cmd_schedule(args) -> int:
    if args.takeoff and args.organization_id is None:
        print("--takeoff requires --organization-id")
        return 1

    try:
        text = Path(args.bars_yaml).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"no such file: {args.bars_yaml}")
        return 1
    except OSError as exc:
        print(f"error reading {args.bars_yaml}: {exc}")
        return 1

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        print(f"invalid YAML in {args.bars_yaml}: {exc}")
        return 1

    if not isinstance(data, dict):
        print(f"bars YAML must be a mapping, got {type(data).__name__}")
        return 1

    try:
        schedule = _build_schedule(data)
    except ValueError as exc:
        print(exc)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(schedule.title)

    md_path = out_dir / f"{slug}.md"
    md_path.write_text(schedule.to_markdown(), encoding="utf-8")
    print(f"wrote {md_path}")

    if args.xlsx:
        xlsx_path = out_dir / f"{slug}.xlsx"
        try:
            schedule.to_xlsx(xlsx_path)
        except ImportError as exc:
            print(exc)
            return 1
        print(f"wrote {xlsx_path}")

    if args.takeoff:
        rows = schedule.to_takeoff_rows(
            cost_code=args.cost_code, item_number=args.item_number,
            schedule=args.schedule_name,
        )
        payload = {
            "organization_id": args.organization_id,
            "project_ref": args.project_ref,
            "rows": rows,
        }
        Path(args.takeoff).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.takeoff}")

    return 0


def cmd_develop(args) -> int:
    try:
        size = BarSize(args.size)
    except ValueError as exc:
        print(exc)
        return 1

    try:
        ld = development_length_in(
            size, fc_psi=args.fc, fy_psi=args.fy, top_bar=args.top_bar,
            epoxy=args.epoxy, lightweight=args.lightweight,
        )
        lap = lap_length_in(
            size, fc_psi=args.fc, fy_psi=args.fy, top_bar=args.top_bar,
            epoxy=args.epoxy, lightweight=args.lightweight, splice_class=args.lap,
        )
    except ValueError as exc:
        print(exc)
        return 1

    print(f"ld = {ld:.2f} in")
    print(f"lap (Class {args.lap}) = {lap:.2f} in")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="est-rebar",
        description="Rebar bar-bending schedules and ACI development/lap "
                    "lengths (estimating aid, not a design tool).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("schedule", help="build a bar bending schedule (BBS) from a bars YAML")
    s.add_argument("bars_yaml")
    s.add_argument("--out-dir", default=".")
    s.add_argument("--xlsx", action="store_true", help="also write a styled .xlsx BBS")
    s.add_argument("--takeoff", default=None, metavar="JSON",
                   help="write a CanonicalTakeoff JSON with an LBS quantity row")
    s.add_argument("--organization-id", type=int, default=None,
                   help="required with --takeoff")
    s.add_argument("--cost-code", default=None)
    s.add_argument("--item-number", default=None)
    s.add_argument("--schedule", dest="schedule_name", default=None,
                   help="schedule label recorded on the takeoff row")
    s.add_argument("--project-ref", default=None)
    s.set_defaults(func=cmd_schedule)

    d = sub.add_parser("develop", help="ACI development + lap lengths for one bar size")
    d.add_argument("--size", type=int, required=True, help="bar size number, e.g. 5 for #5")
    d.add_argument("--fc", type=float, required=True, help="f'c, psi")
    d.add_argument("--fy", type=float, default=60000.0, help="fy, psi (default 60000)")
    d.add_argument("--top-bar", action="store_true", help="top-bar reinforcement (psi_t = 1.3)")
    d.add_argument("--epoxy", action="store_true", help="epoxy-coated bar (psi_e = 1.5)")
    d.add_argument("--lightweight", action="store_true", help="lightweight concrete (lambda = 0.75)")
    d.add_argument("--lap", choices=["A", "B"], default="B", help="splice class (default B)")
    d.set_defaults(func=cmd_develop)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
