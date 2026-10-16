"""Make the plugins' shared Python runtime current. Run by the SessionStart hook.

The whole body is `plugin_runtime.ensure()`; this file is the hook's stable entry
point and nothing more. It used to resolve an interpreter from the cwd
($VIRTUAL_ENV -> $CLAUDE_PROJECT_DIR/.venv -> ./.venv -> ./venv ->
sys.executable) and pip-install into whatever that turned out to be, which made
the installed version a function of where the shell was standing and, on a
PEP-668 system interpreter, made it fail outright. See
docs/superpowers/specs/2026-09-27-plugin-runtime-design.md.

WHAT CHANGED FOR A READER OF THIS FILE:

- The wheels go into ONE venv at a fixed path
  (`~/.estimating/`), never into the user's project venv.
  A consumer project that imports the wheel as a library declares and installs
  it itself -- the plugin stops guessing at that.
- The runtime holds the wheels of EVERY installed plugin, so this hook and
  estimating-core's hook converge on the same runtime instead of reinstalling over each
  other once per session.
- Readiness is per capability. The heavy extras (`solids` -> build123d/OCP,
  `terrain`) are installed on first use by
  `~/.estimating/bin/ensure-extra <name>`, so a correct
  base install stops looking broken -- the old nine-module all-or-nothing probe
  reinstalled every session because `build123d` was absent.

Never fails the session: every exit is 0. stdout is agent-visible session
context -- exactly one line saying what is available or what to suggest to the
user (issue #88 EP-8).
"""
from __future__ import annotations

import os
import sys

LABEL = "calc-bim"


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import plugin_runtime

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    try:
        print(plugin_runtime.ensure(plugin_root, LABEL))
    except Exception as exc:                # a SessionStart hook must exit 0
        print(f"{LABEL}: the plugin runtime could not be prepared ({exc}); "
              f"tools from this plugin may be unavailable this session")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
