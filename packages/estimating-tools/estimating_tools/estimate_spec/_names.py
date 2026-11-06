"""Name matching shared by the assembly generator and the push planner.

An earlier, hand-scripted assembly push cut long component names (package lines of
118 and 125 characters were stored at 113), so a component name and a spec line name
are the same when identical, or when one is a prefix of the other and the shorter is
at least `NAME_PREFIX_MIN` characters (ruling 37).
"""
from __future__ import annotations

NAME_PREFIX_MIN = 100   # a shorter name that prefixes the other was cut by the old push


def same_name(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= NAME_PREFIX_MIN and long_.startswith(short)
