#!/usr/bin/env python3
"""Rewrite bare tool invocations in SKILL.md to their shim paths, or --check them.

WHY. The plugins' tools are not on `PATH` and never reliably were -- on a
measured machine `PATH` carried none of them. They live in the plugins' own
runtime, so the only way a skill can reach one is by naming its shim under
`~/.estimating/bin/`. See
docs/superpowers/specs/2026-09-27-plugin-runtime-design.md.

WHAT COUNTS AS AN INVOCATION. Only code: a fenced block, or an inline backtick
span (which may wrap across lines). Prose that NAMES a tool is left alone --
`# Draw a Control Sheet (est-sheets control)` is a heading, "est-bim stays
deterministic" is a sentence, and a frontmatter `description:` is neither a
command nor a place for a 19-character path. An inline span holding nothing but
the tool's name is a mention too ("the `est-bim` CLI"); a span with arguments
after it is a command.

`python -c` / `python -m` reaching for our packages is rewritten to
`est-python`: the ambient interpreter does not have the wheels at all any more,
which is the point of the runtime.

This is a generator over hand-written prose, so it is deliberately conservative
and idempotent: running it twice changes nothing, and `--check` is the CI gate.

Examples:
    python scripts/shim_skill_paths.py           # rewrite in place
    python scripts/shim_skill_paths.py --check   # CI drift gate, writes nothing
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_GLOB = "plugins/*/skills/*/SKILL.md"

#: Must equal `plugin_runtime.bin_dir()`; a test asserts it.
BIN = "~/.estimating/bin/"

#: Every console script our two wheels declare, plus the runtime's own shims.
SCRIPTS = ["est-bim", "est-sheets", "est-estimate", "est-takeoff", "est-import",
           "est-hist", "est-gantt", "est-schedule",
           "est-scaffold", "est-intake", "est-rebar", "est-quotespace", "est-quotes",
           "est-letterhead", "est-artifact-app", "asm-import", "asm-load",
           "dir-import", "dir-sync", "rate-import", "costcode-import",
           "profile-init", "m2m-token", "est-feedback", "est-python", "ensure-extra"]

SCRIPT_RE = re.compile(r"(?<![\w./-])(" + "|".join(map(re.escape, SCRIPTS))
                       + r")(?![\w./-])")
PYTHON_RE = re.compile(r"(?<![\w./-])python3?(?=\s+-[cm]\b)")
OURS_RE = re.compile(r"estimating_tools|bimforge")
FENCE_RE = re.compile(r"^\s*(?:>\s*)*(?:```|~~~)")
#: An inline span, possibly wrapping across lines.
INLINE_RE = re.compile(r"(`+)(.+?)(\1)", re.DOTALL)


def rewrite_code(text: str, *, mention_ok: bool) -> str:
    """Prefix invocations in one chunk of code."""
    def script(m):
        if mention_ok and text.strip() == m.group(1):
            return m.group(1)          # naming the tool, not running it
        return BIN + m.group(1)

    out = SCRIPT_RE.sub(script, text)
    if OURS_RE.search(out):
        out = PYTHON_RE.sub(BIN + "est-python", out)
    return out


def rewrite(md: str) -> str:
    chunks, buf, in_fence = [], [], False
    for line in md.split("\n"):
        if FENCE_RE.match(line):
            chunks.append(("fence" if in_fence else "prose", "\n".join(buf)))
            chunks.append(("marker", line))
            buf, in_fence = [], not in_fence
            continue
        buf.append(line)
    chunks.append(("fence" if in_fence else "prose", "\n".join(buf)))

    out = []
    for kind, text in chunks:
        if kind == "marker":
            out.append(text)
        elif kind == "fence":
            out.append(rewrite_code(text, mention_ok=False))
        else:
            out.append(INLINE_RE.sub(
                lambda m: m.group(1) + rewrite_code(m.group(2), mention_ok=True)
                + m.group(3), text))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify every skill is already shimmed; write nothing")
    args = ap.parse_args(argv)

    sources = sorted(REPO_ROOT.glob(SRC_GLOB))
    if not sources:
        print(f"no SKILL.md under {REPO_ROOT}/{SRC_GLOB}", file=sys.stderr)
        return 1

    stale = []
    for md in sources:
        src = md.read_text(encoding="utf-8")
        new = rewrite(src)
        if new == src:
            continue
        if args.check:
            stale.append(str(md.relative_to(REPO_ROOT)))
            continue
        md.write_text(new, encoding="utf-8")
        print(f"shimmed {md.relative_to(REPO_ROOT)}")

    if args.check:
        if stale:
            print("DRIFT: these skills invoke a tool by its bare name, which is "
                  "not on PATH:", file=sys.stderr)
            for s in stale:
                print(f"  {s}", file=sys.stderr)
            print("Run: python scripts/shim_skill_paths.py", file=sys.stderr)
            return 1
        print(f"{len(sources)} skills name their tools by shim path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
