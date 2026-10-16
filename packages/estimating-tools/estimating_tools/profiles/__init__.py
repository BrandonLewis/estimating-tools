"""Profile system: discover, load, validate, merge, and resolve org/agency profiles."""
from estimating_tools.profiles.merge import merge
from estimating_tools.profiles.model import Profile

__all__ = ["Profile", "merge", "load", "ProfileInputs", "build_profile_dir"]


def __getattr__(name):  # lazy import so `merge`/`Profile` don't pull in jsonschema
    if name == "load":
        from estimating_tools.profiles.loader import load
        return load
    if name in ("ProfileInputs", "build_profile_dir"):
        from estimating_tools.profiles import build
        return getattr(build, name)
    raise AttributeError(name)
