"""CLI: render a markdown-with-frontmatter draft onto a .docx letterhead template.

Usage:
  est-letterhead <draft.md> [-o out.docx] [--template path.docx]
  # or, equivalently:
  python -m estimating_tools.docgen.letterhead_cli <draft.md> ...

The draft is the file the draft-an-rfi skill writes: YAML frontmatter
(project, to, subject, references, ...) followed by the markdown body.
Template resolution: ``--template`` wins; otherwise the active profile's
``letterhead.template`` (via ``profiles.wires.to_letterhead``), whose other
letterhead fields (company_name, address, ...) merge UNDER the draft's own
frontmatter. Rendering is ``docgen.docxtpl_engine.render_letterhead``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split ``---``-fenced YAML frontmatter from the markdown body.

    No frontmatter fence -> ({}, whole text). A fenced block that is not a
    YAML mapping raises ValueError.
    """
    import yaml

    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    try:
        raw = yaml.safe_load(text[3:end])
    except yaml.YAMLError as exc:
        raise ValueError(f"draft frontmatter is not valid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("draft frontmatter is not a YAML mapping")
    body = text[end + len("\n---"):]
    return raw, body.lstrip("\r\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="est-letterhead",
        description="Render a markdown draft (YAML frontmatter + body) onto "
                    "a .docx letterhead template.")
    ap.add_argument("draft", help="markdown draft with YAML frontmatter")
    ap.add_argument("-o", "--out",
                    help="output .docx path (default: the draft's path with "
                         "a .docx suffix)")
    ap.add_argument("--template",
                    help=".docx template (default: the active profile's "
                         "letterhead.template via ESTIMATING_PROFILES)")
    args = ap.parse_args(argv)

    draft_path = Path(args.draft)
    if not draft_path.is_file():
        print(f"error: no such draft: {draft_path}", file=sys.stderr)
        return 1
    try:
        frontmatter, body_md = split_frontmatter(
            draft_path.read_text(encoding="utf-8"))
        if not frontmatter:
            # a draft missing its --- fence silently renders a blank header;
            # make the miss loud without refusing (some letters ARE body-only)
            print("warning: no '---'-fenced YAML frontmatter found in "
                  f"{draft_path.name}; the letterhead header fields will be "
                  "empty unless the profile supplies them", file=sys.stderr)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    lh_front: dict = {}
    if args.template:
        template_path = Path(args.template)
        if not template_path.is_file():
            print(f"error: template not found: {template_path}",
                  file=sys.stderr)
            return 1
    else:
        from estimating_tools import profiles
        from estimating_tools.profiles import wires

        try:
            template_path, lh_front = wires.to_letterhead(profiles.load())
        except ValueError:
            print("error: no template — pass --template <path.docx> or add "
                  "letterhead.template (a .docx file) to the active profile "
                  "(ESTIMATING_PROFILES)", file=sys.stderr)
            return 1
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    from estimating_tools.docgen.docxtpl_engine import render_letterhead

    out_path = Path(args.out) if args.out else draft_path.with_suffix(".docx")
    # profile letterhead fields merge UNDER the draft's own frontmatter
    render_letterhead(template_path, out_path, {**lh_front, **frontmatter},
                      body_md)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
